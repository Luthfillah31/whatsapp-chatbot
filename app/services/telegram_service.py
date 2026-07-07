import logging
import httpx
from typing import Optional, List, Dict, Any
from app.config import settings
from app.models.schemas import IncomingChatMessage

logger = logging.getLogger(__name__)


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


async def send_telegram_message(chat_id: str, text: str) -> bool:
    """
    Sends a text message reply via Telegram Bot API.
    """
    token = get_clean_token()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not configured. Skipping outbound Telegram message.")
        return False

    # Remove 'tg_' prefix if present when sending back to Telegram API
    clean_chat_id = chat_id.replace("tg_", "") if chat_id.startswith("tg_") else chat_id

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    data = {
        "chat_id": clean_chat_id,
        "text": text
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=data, timeout=20.0)
            if resp.status_code == 200:
                logger.info(f"Message sent successfully to Telegram chat {clean_chat_id}.")
                return True
            else:
                logger.error(f"Telegram API error ({resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            logger.error(f"HTTP request error sending Telegram message: {e}", exc_info=True)
            return False


async def register_telegram_webhook(webhook_url: str) -> Dict[str, Any]:
    """
    Helper function to register our FastAPI server URL as the Telegram Bot Webhook.
    """
    token = get_clean_token()
    if not token:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN is not configured in environment."}

    url = f"https://api.telegram.org/bot{token}/setWebhook"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json={"url": webhook_url}, timeout=20.0)
            return resp.json()
        except Exception as e:
            logger.error(f"Error setting webhook: {e}", exc_info=True)
            return {"ok": False, "description": f"Error setting webhook: {str(e)}"}

