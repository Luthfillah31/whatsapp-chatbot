import logging
import httpx
import asyncio
import json
import re
import urllib.request
from typing import Optional, List, Dict, Any
from app.config import settings
from app.models.schemas import IncomingChatMessage

logger = logging.getLogger(__name__)


def format_text_for_telegram(text: str) -> str:
    """Converts standard LLM Markdown syntax into valid Telegram HTML formatting."""
    if not text:
        return ""
    # Replace markdown headers (# Header or ## Header) with <b>HEADER</b>
    text = re.sub(r'^#{1,6}\s*(.+)$', lambda m: f"<b>{m.group(1).strip().upper()}</b>", text, flags=re.MULTILINE)
    # Replace double asterisks **bold** with <b>bold</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    # Replace single asterisk *italic* with <i>italic</i> (only if not adjacent to another asterisk)
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    # Replace double tildes ~~strike~~ with <s>strike</s>
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text)
    return text


def parse_telegram_webhook(payload: Dict[str, Any]) -> List[IncomingChatMessage]:
    """
    Parses incoming messages from Telegram Bot API webhook payload.
    """
    incoming_msgs = []
    try:
        message = payload.get("message") or payload.get("edited_message")
        if not message:
            return incoming_msgs

        msg_id = str(message.get("message_id", ""))
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        
        sender = message.get("from", {})
        first_name = sender.get("first_name", "")
        last_name = sender.get("last_name", "")
        sender_name = f"{first_name} {last_name}".strip() or "Telegram User"

        text_content = message.get("text")
        
        if chat_id and text_content:
            # We prefix chat_id with 'tg_' or use directly as unique identifier for chat history
            incoming_msgs.append(IncomingChatMessage(
                sender_phone=f"tg_{chat_id}",
                sender_name=sender_name,
                message_text=text_content,
                message_id=msg_id
            ))
    except Exception as e:
        logger.error(f"Error parsing Telegram webhook: {e}", exc_info=True)

    return incoming_msgs


def get_clean_token() -> str:
    """Sanitizes TELEGRAM_BOT_TOKEN from environment variables."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return ""
    token = settings.TELEGRAM_BOT_TOKEN.strip().strip('"').strip("'")
    if token.lower().startswith("bot"):
        token = token[3:].strip()
    return token


def send_sync_telegram(url: str, data: dict) -> bool:
    """Synchronous fallback using standard urllib to bypass async IPv6/TLS timeouts."""
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            if resp.status == 200:
                logger.info("Message sent successfully via sync urllib fallback.")
                return True
    except Exception as e:
        logger.error(f"Sync urllib fallback failed: {e}", exc_info=True)
    return False


async def send_telegram_message(chat_id: str, text: str) -> bool:
    """
    Sends a text message reply via Telegram Bot API with HTML formatting, IPv4 forcing, and sync fallback.
    """
    token = get_clean_token()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not configured. Skipping outbound Telegram message.")
        return False

    # Remove 'tg_' prefix if present when sending back to Telegram API
    clean_chat_id = chat_id.replace("tg_", "") if chat_id.startswith("tg_") else chat_id
    formatted_text = format_text_for_telegram(text)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": clean_chat_id,
        "text": formatted_text,
        "parse_mode": "HTML"
    }

    # Attempt 1: httpx with forced IPv4 (local_address="0.0.0.0") and retries

    try:
        transport = httpx.AsyncHTTPTransport(retries=2, local_address="0.0.0.0")
        async with httpx.AsyncClient(transport=transport, timeout=15.0) as client:
            resp = await client.post(url, json=data)
            if resp.status_code == 200:
                logger.info(f"Message sent successfully to Telegram chat {clean_chat_id} via httpx.")
                return True
            else:
                logger.error(f"Telegram API error ({resp.status_code}): {resp.text}")
                return False
    except Exception as e:
        logger.warning(f"httpx outbound request failed ({e}), switching to sync urllib fallback...")

    # Attempt 2: Synchronous urllib fallback in thread pool
    return await asyncio.to_thread(send_sync_telegram, url, data)


async def register_telegram_webhook(webhook_url: str) -> Dict[str, Any]:
    """
    Helper function to register our FastAPI server URL as the Telegram Bot Webhook.
    """
    token = get_clean_token()
    if not token:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN is not configured in environment."}

    url = f"https://api.telegram.org/bot{token}/setWebhook"
    data = {"url": webhook_url}

    try:
        transport = httpx.AsyncHTTPTransport(retries=2, local_address="0.0.0.0")
        async with httpx.AsyncClient(transport=transport, timeout=15.0) as client:
            resp = await client.post(url, json=data)
            return resp.json()
    except Exception as e:
        logger.warning(f"httpx webhook setup failed ({e}), trying sync urllib...")
        try:
            def sync_setup():
                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            return await asyncio.to_thread(sync_setup)
        except Exception as sync_e:
            return {"ok": False, "description": f"Error setting webhook: {str(sync_e)}"}


