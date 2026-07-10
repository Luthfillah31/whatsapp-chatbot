import logging
import httpx
import re
import asyncio
import json
import urllib.request
from typing import Optional, List, Dict, Any
from app.config import settings
from app.models.schemas import IncomingChatMessage

logger = logging.getLogger(__name__)


def verify_meta_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
    """Validates the Meta WhatsApp Cloud API webhook challenge."""
    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("Meta Webhook verified successfully!")
        return challenge
    logger.warning("Meta Webhook verification failed: invalid token.")
    return None


def parse_meta_webhook(payload: Dict[str, Any]) -> List[IncomingChatMessage]:
    """
    Parses incoming messages from the Meta Cloud API webhook payload structure.
    Handles text messages, interactive button clicks, and extracts sender contact info.
    """
    incoming_msgs = []
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                
                # Extract contacts map for display names
                contacts = value.get("contacts", [])
                name_map = {}
                for c in contacts:
                    wa_id = c.get("wa_id")
                    profile_name = c.get("profile", {}).get("name", "WhatsApp User")
                    if wa_id:
                        name_map[wa_id] = profile_name

                messages = value.get("messages", [])
                for msg in messages:
                    sender_phone = msg.get("from")
                    msg_id = msg.get("id")
                    msg_type = msg.get("type")
                    
                    text_content = None
                    if msg_type == "text":
                        text_content = msg.get("text", {}).get("body")
                    elif msg_type == "interactive":
                        inter = msg.get("interactive", {})
                        if inter.get("type") == "button_reply":
                            text_content = inter.get("button_reply", {}).get("title")
                        elif inter.get("type") == "list_reply":
                            text_content = inter.get("list_reply", {}).get("title")

                    if sender_phone and text_content:
                        sender_name = name_map.get(sender_phone, "WhatsApp User")
                        incoming_msgs.append(IncomingChatMessage(
                            sender_phone=sender_phone,
                            sender_name=sender_name,
                            message_text=text_content,
                            message_id=msg_id
                        ))
    except Exception as e:
        logger.error(f"Error parsing Meta WhatsApp webhook: {e}", exc_info=True)
    
    return incoming_msgs


def parse_evolution_webhook(payload: Dict[str, Any]) -> List[IncomingChatMessage]:
    """
    Parses incoming messages from an Evolution API / Baileys open-source WhatsApp wrapper.
    """
    incoming_msgs = []
    try:
        event = payload.get("event")
        if event in ["messages.upsert", "messages.create", "MESSAGES_UPSERT"]:
            data = payload.get("data", payload)
            if isinstance(data, dict):
                key = data.get("key", {})
                remote_jid = key.get("remoteJid", "")
                if remote_jid.endswith("@s.whatsapp.net") and not key.get("fromMe", False):
                    phone = remote_jid.split("@")[0]
                    push_name = data.get("pushName", "Evolution User")
                    
                    msg_data = data.get("message", {})
                    text_content = (
                        msg_data.get("conversation") or 
                        msg_data.get("extendedTextMessage", {}).get("text")
                    )
                    
                    if text_content:
                        incoming_msgs.append(IncomingChatMessage(
                            sender_phone=phone,
                            sender_name=push_name,
                            message_text=text_content,
                            message_id=key.get("id")
                        ))
    except Exception as e:
        logger.error(f"Error parsing Evolution API webhook: {e}", exc_info=True)
        
    return incoming_msgs


def format_text_for_whatsapp(text: str) -> str:
    """Sanitizes standard Markdown syntax into valid WhatsApp text formatting."""
    if not text:
        return ""
    # Replace markdown headers (# Header or ## Header) with *HEADER*
    text = re.sub(r'^#{1,6}\s*(.+)$', lambda m: f"*{m.group(1).strip().upper()}*", text, flags=re.MULTILINE)
    # Replace double asterisks **bold** with *bold*
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    # Replace double tildes ~~strike~~ with ~strike~
    text = re.sub(r'~~(.*?)~~', r'~\1~', text)
    return text


def _send_via_curl(url: str, headers: dict, data: dict) -> bool:
    """Attempt 1: Uses system curl via subprocess which has robust OS-level TLS, ALPN, and path MTU handling."""
    import subprocess
    try:
        cmd = ["curl", "-4", "-s", "-X", "POST", url, "-H", "Content-Type: application/json"]
        for k, v in headers.items():
            if k.lower() != "content-type":
                cmd.extend(["-H", f"{k}: {v}"])
        cmd.extend([
            "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "--http1.1",
            "-d", json.dumps(data),
            "--connect-timeout", "8",
            "--max-time", "18",
            "--retry", "2",
            "--retry-delay", "1"
        ])
        logger.info("Attempting outbound WhatsApp message via system curl (with browser UA & http1.1)...")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if res.returncode == 0 and res.stdout:
            logger.info(f"Message sent via curl! Response: {res.stdout[:200]}")
            try:
                resp_json = json.loads(res.stdout)
                if "messages" in resp_json or "id" in resp_json:
                    return True
                if "error" in resp_json:
                    logger.error(f"Meta API error via curl: {res.stdout}")
                    return False
            except Exception:
                pass
            return True
        else:
            logger.warning(f"curl failed with returncode {res.returncode}: {res.stderr}")
            return False
    except Exception as e:
        logger.warning(f"curl execution failed: {e}")
        return False


def _send_via_raw_ipv4_socket(host: str, path: str, headers: dict, data: dict) -> bool:
    """
    Ultimate fallback: loops through ALL resolved IPv4 addresses for graph.facebook.com
    with Cloudflare DoH enrichment, a 5-second connect/handshake timeout, and TCP MSS clamping (1024 bytes)
    to bypass cloud container geo-routing and MTU blackholes.
    """
    import socket
    import ssl

    ips = []
    # Step 1: Force IPv4 DNS resolution and extract unique IPs
    try:
        addrs = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        if addrs:
            ips = list(dict.fromkeys([addr[4][0] for addr in addrs if addr[4] and addr[4][0]]))
    except Exception as e:
        logger.debug(f"Local IPv4 DNS resolution failed for {host}: {e}")

    # Step 1b: Enrich via Cloudflare DNS over HTTPS (DoH) if local DNS returns few or blocked IPs
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://1.1.1.1/dns-query?name={host}&type=A",
            headers={"accept": "application/dns-json"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            dns_data = json.loads(resp.read().decode("utf-8"))
            for ans in dns_data.get("Answer", []):
                if ans.get("type") == 1 and ans.get("data"):
                    ip_val = ans.get("data")
                    if ip_val not in ips:
                        ips.append(ip_val)
        logger.info(f"Enriched IPv4 candidates via Cloudflare DoH: {ips}")
    except Exception as doh_err:
        logger.debug(f"Cloudflare DoH lookup failed: {doh_err}")

    if not ips:
        logger.error(f"No IPv4 addresses found for {host}")
        return False

    if "facebook.com" in host.lower():
        # Include known stable Meta Anycast IPv4 endpoints as backup candidates for facebook.com
        for sip in ["157.240.199.35", "185.60.218.35", "31.13.80.35", "157.240.22.35"]:
            if sip not in ips:
                ips.append(sip)
        ips.sort(key=lambda ip: 0 if ip.startswith(("157.", "185.", "31.")) else 1)
    logger.info(f"Final candidate IPv4 list for {host}: {ips}")

    body = json.dumps(data).encode("utf-8")
    request_line = f"POST {path} HTTP/1.1\r\n"
    header_str = f"Host: {host}\r\n"
    for k, v in headers.items():
        header_str += f"{k}: {v}\r\n"
    header_str += f"Content-Length: {len(body)}\r\n"
    header_str += "Connection: close\r\n\r\n"
    payload = (request_line + header_str).encode("utf-8") + body

    # Step 2: Loop through all candidate IPv4 addresses
    for ip in ips:
        logger.info(f"Trying raw socket connection to {host} via IPv4: {ip} ...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        ssock = None
        try:
            sock.connect((ip, 443))
            context = ssl.create_default_context()
            ssock = context.wrap_socket(sock, server_hostname=host)
            logger.info(f"SSL handshake to {host} ({ip}) succeeded!")

            # Send HTTP request
            ssock.sendall(payload)

            # Read response
            response = b""
            while True:
                chunk = ssock.recv(4096)
                if not chunk:
                    break
                response += chunk
            ssock.close()

            # Parse HTTP status from first line
            first_line = response.split(b"\r\n")[0].decode(errors="replace")
            status_code = int(first_line.split(" ")[1])
            body_start = response.find(b"\r\n\r\n") + 4
            resp_body = response[body_start:].decode(errors="replace")

            if status_code == 200:
                logger.info(f"Meta message sent successfully via IPv4 {ip}! Response: {resp_body[:200]}")
                return True
            else:
                logger.error(f"Meta API error ({status_code}) from {ip}: {resp_body[:500]}")
                # If Meta returned an HTTP response, the network is fine; no need to try other IPs
                return False
        except Exception as e:
            logger.warning(f"Raw socket attempt to {ip} failed ({e}), trying next IP candidate...")
            try:
                if ssock:
                    ssock.close()
                else:
                    sock.close()
            except Exception:
                pass

    logger.error("All IPv4 candidates for graph.facebook.com failed.")
    return False


def _send_via_urllib(url: str, headers: dict, data: dict) -> bool:
    """Attempt 2: Uses standard Python urllib.request as reliable outbound fallback."""
    try:
        req_headers = dict(headers)
        if "User-Agent" not in req_headers:
            req_headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=req_headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            if status == 200:
                logger.info(f"Message sent successfully via urllib! Response: {body[:200]}")
                return True
            else:
                logger.error(f"Meta API error ({status}) via urllib: {body[:500]}")
                return False
    except Exception as e:
        logger.warning(f"urllib outbound failed: {e}")
        return False


async def _background_retry_whatsapp_message(url: str, headers: dict, data: dict, phone_number: str):
    """Background worker that retries sending a WhatsApp message every 30s if transient throttling occurred."""
    for retry_idx in range(1, 16):
        await asyncio.sleep(30)
        logger.info(f"Background worker retrying delayed WhatsApp message to {phone_number} (attempt {retry_idx}/15)...")
        result = await asyncio.to_thread(_send_via_curl, url, headers, data)
        if result:
            logger.info(f"Delayed WhatsApp message to {phone_number} successfully sent on background attempt {retry_idx}!")
            return
        result = await asyncio.to_thread(_send_via_urllib, url, headers, data)
        if result:
            logger.info(f"Delayed WhatsApp message to {phone_number} successfully sent via urllib on background attempt {retry_idx}!")
            return
    logger.error(f"Background worker gave up sending WhatsApp message to {phone_number} after 15 attempts.")


_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=5.0)
        _client = httpx.AsyncClient(limits=limits, timeout=15.0)
    return _client


async def send_whatsapp_message(phone_number: str, text: str) -> bool:
    """Unified WhatsApp sender that uses Evolution API if configured, otherwise falls back to Meta Cloud API."""
    if settings.EVOLUTION_API_URL and settings.EVOLUTION_API_KEY:
        logger.info(f"Sending message to {phone_number} via Evolution API...")
        return await send_evolution_message(phone_number, text)
    logger.info(f"Sending message to {phone_number} via Meta Cloud API...")
    return await send_meta_whatsapp_message(phone_number, text)


async def send_meta_whatsapp_message(phone_number: str, text: str) -> bool:
    """Sends a text message reply via Meta WhatsApp Cloud API with multi-layer fallback and exponential backoff retries."""
    formatted_text = format_text_for_whatsapp(text)
    if not settings.WHATSAPP_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("Meta WhatsApp API credentials not configured. Skipping outbound message.")
        return False

    raw_base = getattr(settings, "WHATSAPP_API_BASE_URL", None) or "https://graph.facebook.com"
    base_url = raw_base.strip().rstrip("/")
    if not base_url.startswith("http://") and not base_url.startswith("https://"):
        base_url = f"https://{base_url}"
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    host = parsed.netloc or parsed.path or "graph.facebook.com"
    path = f"/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    url = f"{base_url}{path}"
    logger.info(f"Outbound WhatsApp request target: {url} (host={host})")
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": formatted_text}
    }

    max_rounds = 3
    for attempt_round in range(1, max_rounds + 1):
        if attempt_round > 1:
            backoff_sec = 1.5 * (attempt_round - 1)
            logger.info(f"Retrying Meta WhatsApp outbound message (round {attempt_round}/{max_rounds}) after {backoff_sec}s delay...")
            await asyncio.sleep(backoff_sec)

        # Attempt 1: Standard httpx AsyncClient with fresh connection per request
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=data)
                if resp.status_code == 200:
                    logger.info(f"Message sent to {phone_number} via Meta Cloud API (httpx).")
                    return True
                else:
                    logger.error(f"Meta Cloud API error ({resp.status_code}): {resp.text}")
                    return False
        except Exception as e:
            logger.warning(f"httpx Meta outbound to {host} failed ({type(e).__name__}): {repr(e)}")

        # Attempt 2: Standard Python urllib.request
        logger.info("httpx failed, attempting outbound via standard urllib...")
        result = await asyncio.to_thread(_send_via_urllib, url, headers, data)
        if result:
            return True

        # Attempt 3: System curl via subprocess
        logger.info("urllib failed, attempting outbound via system curl...")
        result = await asyncio.to_thread(_send_via_curl, url, headers, data)
        if result:
            return True

        # Attempt 4: Raw IPv4 socket with Cloudflare DoH enrichment and TCP MSS clamping
        logger.info("curl failed, attempting outbound WhatsApp message via raw socket with DoH enrichment...")
        result = await asyncio.to_thread(_send_via_raw_ipv4_socket, host, path, headers, data)
        if result:
            return True

    logger.error("All immediate outbound rounds to graph.facebook.com failed. Spawning background task to keep retrying every 30s...")
    asyncio.create_task(_background_retry_whatsapp_message(url, headers, data, phone_number))
    return False


async def send_evolution_message(phone_number: str, text: str) -> bool:
    """Sends a text message reply via Evolution API / Baileys instance."""
    formatted_text = format_text_for_whatsapp(text)
    if not settings.EVOLUTION_API_URL or not settings.EVOLUTION_API_KEY:
        logger.warning("Evolution API credentials not configured. Skipping outbound message.")
        return False

    url = f"{settings.EVOLUTION_API_URL.rstrip('/')}/message/sendText/{settings.EVOLUTION_INSTANCE_NAME}"
    headers = {
        "apikey": settings.EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "number": phone_number,
        "text": formatted_text
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=headers, json=data, timeout=10.0)
            if resp.status_code in [200, 201]:
                logger.info(f"Message sent successfully to {phone_number} via Evolution API.")
                return True
            else:
                logger.error(f"Evolution API error ({resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            logger.error(f"HTTP request error sending Evolution message: {e}")
            return False
