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


def _send_meta_sync(url: str, headers: dict, data: dict) -> bool:
    """Synchronous fallback using urllib to bypass async network issues in cloud containers."""
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            if resp.status == 200:
                logger.info("Meta WhatsApp message sent via sync urllib fallback.")
                return True
            else:
                logger.error(f"Meta sync fallback error ({resp.status}): {resp.read().decode()}")
    except Exception as e:
        logger.error(f"Meta sync urllib fallback failed: {e}", exc_info=True)
    return False


async def send_meta_whatsapp_message(phone_number: str, text: str) -> bool:
    """Sends a text message reply via Meta WhatsApp Cloud API with IPv4 forcing and sync fallback."""
    formatted_text = format_text_for_whatsapp(text)
    if not settings.WHATSAPP_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("Meta WhatsApp API credentials not configured. Skipping outbound message.")
        return False

    url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
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

    # Attempt 1: httpx with forced IPv4 and retries
    try:
        transport = httpx.AsyncHTTPTransport(retries=2, local_address="0.0.0.0")
        async with httpx.AsyncClient(transport=transport, timeout=20.0) as client:
            resp = await client.post(url, headers=headers, json=data)
            if resp.status_code == 200:
                logger.info(f"Message sent successfully to {phone_number} via Meta Cloud API (httpx).")
                return True
            else:
                logger.error(f"Meta Cloud API error ({resp.status_code}): {resp.text}")
                return False
    except Exception as e:
        logger.warning(f"httpx Meta outbound failed ({e}), switching to sync urllib fallback...")

    # Attempt 2: Synchronous urllib fallback in thread pool
    return await asyncio.to_thread(_send_meta_sync, url, headers, data)


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
