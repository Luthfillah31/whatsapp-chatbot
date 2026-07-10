import logging
import asyncio
from typing import Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, Request, BackgroundTasks, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.models.db_models import get_db, SessionLocal
from app.models.schemas import IncomingChatMessage
from app.services import whatsapp_service, llm_service, telegram_service

logger = logging.getLogger(__name__)

# In-memory deduplication cache for incoming webhook message IDs
PROCESSED_MESSAGE_IDS: set = set()

router = APIRouter(prefix="/webhook", tags=["Webhooks"])


async def process_and_reply_telegram(msg: IncomingChatMessage):
    """Background worker to run OpenRouter LLM loop and send reply via Telegram Bot API."""
    db = SessionLocal()
    try:
        reply_text = llm_service.process_chat_message(
            db=db,
            phone_number=msg.sender_phone,
            sender_name=msg.sender_name,
            message_text=msg.message_text
        )
        await telegram_service.send_telegram_message(msg.sender_phone, reply_text)
    except Exception as e:
        logger.error(f"Error processing Telegram message in background: {e}", exc_info=True)
    finally:
        db.close()


async def process_and_reply_meta(msg: IncomingChatMessage):
    """Background worker to run OpenRouter LLM loop and send WhatsApp reply via configured API."""
    db = SessionLocal()
    try:
        reply_text = llm_service.process_chat_message(
            db=db,
            phone_number=msg.sender_phone,
            sender_name=msg.sender_name,
            message_text=msg.message_text
        )
        await whatsapp_service.send_whatsapp_message(msg.sender_phone, reply_text)
    except Exception as e:
        logger.error(f"Error processing Meta message in background: {e}", exc_info=True)
    finally:
        db.close()


async def process_and_reply_evolution(msg: IncomingChatMessage):
    """Background worker to run OpenRouter LLM loop and send reply via configured API."""
    db = SessionLocal()
    try:
        reply_text = llm_service.process_chat_message(
            db=db,
            phone_number=msg.sender_phone,
            sender_name=msg.sender_name,
            message_text=msg.message_text
        )
        await whatsapp_service.send_whatsapp_message(msg.sender_phone, reply_text)
    except Exception as e:
        logger.error(f"Error processing Evolution message in background: {e}", exc_info=True)
    finally:
        db.close()


@router.get("/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    """
    Endpoint for Meta WhatsApp Cloud API webhook verification.
    """
    if not hub_mode or not hub_verify_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing parameters")

    challenge = whatsapp_service.verify_meta_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge:
        return int(challenge) if challenge.isdigit() else challenge
    
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")


@router.post("/whatsapp")
async def receive_whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming WhatsApp messages from Meta Cloud API.
    Returns 200 OK immediately and processes via OpenRouter in background.
    """
    try:
        payload = await request.json()
        incoming_msgs = whatsapp_service.parse_meta_webhook(payload)
        for msg in incoming_msgs:
            if msg.message_id and msg.message_id in PROCESSED_MESSAGE_IDS:
                logger.info(f"Duplicate Meta WhatsApp message_id {msg.message_id} ignored.")
                continue
            if msg.message_id:
                if len(PROCESSED_MESSAGE_IDS) >= 2000:
                    PROCESSED_MESSAGE_IDS.clear()
                PROCESSED_MESSAGE_IDS.add(msg.message_id)
            logger.info(f"Received Meta WhatsApp message from {msg.sender_phone}: {msg.message_text}")
            asyncio.create_task(process_and_reply_meta(msg))
    except Exception as e:
        logger.error(f"Error receiving WhatsApp webhook: {e}", exc_info=True)
        
    return {"status": "ok"}


@router.post("/evolution")
async def receive_evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming WhatsApp messages from Evolution API / Baileys wrapper.
    """
    try:
        payload = await request.json()
        incoming_msgs = whatsapp_service.parse_evolution_webhook(payload)
        for msg in incoming_msgs:
            logger.info(f"Received Evolution message from {msg.sender_phone}: {msg.message_text}")
            background_tasks.add_task(process_and_reply_evolution, msg)
    except Exception as e:
        logger.error(f"Error receiving Evolution webhook: {e}", exc_info=True)
        
    return {"status": "ok"}


@router.post("/simulator")
async def receive_simulator_message(msg: IncomingChatMessage, db: Session = Depends(get_db)):
    """
    Synchronous endpoint for the interactive Web Chat Simulator.
    Executes the LLM tool loop and returns the reply instantly.
    
    WARNING: This endpoint allows arbitrary sender_phone values for testing.
    In production, phone identity is enforced by WhatsApp webhook payload.
    """
    logger.info(f"Simulator message from {msg.sender_name} ({msg.sender_phone}): {msg.message_text}")
    logger.debug(
        f"SIMULATOR NOTE: Phone '{msg.sender_phone}' is user-provided (not WhatsApp-verified). "
        f"In production, phone is extracted from webhook payload and cannot be spoofed."
    )
    try:
        reply_text = llm_service.process_chat_message(
            db=db,
            phone_number=msg.sender_phone,
            sender_name=msg.sender_name,
            message_text=msg.message_text
        )
        return {"status": "success", "reply": reply_text}
    except Exception as e:
        logger.error(f"Simulator error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/telegram")
async def receive_telegram_webhook(request: Request):
    """
    Receives incoming Telegram messages and replies using Telegram's 
    'Reply via Webhook Response' feature.
    
    Instead of making a separate outbound HTTP call to api.telegram.org/sendMessage,
    we process the message synchronously and return the reply payload directly
    in the webhook response body. Telegram reads this response and delivers it
    as a sendMessage call automatically.
    
    This completely bypasses any outbound network restrictions on the hosting container.
    Telegram allows up to 60 seconds for webhook responses.
    """
    try:
        payload = await request.json()
        incoming_msgs = telegram_service.parse_telegram_webhook(payload)
        
        if not incoming_msgs:
            # No text message to process (could be a status update, photo, etc.)
            return {"status": "ok"}
        
        # Process the first message synchronously
        msg = incoming_msgs[0]
        logger.info(f"Received Telegram message from {msg.sender_name} ({msg.sender_phone}): {msg.message_text}")
        
        db = SessionLocal()
        try:
            reply_text = llm_service.process_chat_message(
                db=db,
                phone_number=msg.sender_phone,
                sender_name=msg.sender_name,
                message_text=msg.message_text
            )
        finally:
            db.close()
        
        # Extract clean chat_id (remove 'tg_' prefix)
        clean_chat_id = msg.sender_phone.replace("tg_", "") if msg.sender_phone.startswith("tg_") else msg.sender_phone
        formatted_reply = telegram_service.format_text_for_telegram(reply_text)
        
        logger.info(f"Replying to Telegram chat {clean_chat_id} via webhook response (no outbound HTTP needed).")
        
        # Return the reply using Telegram's "Reply via Webhook Response" feature.
        # By including "method": "sendMessage" in the JSON response body,
        # Telegram will automatically deliver this as a sendMessage API call.
        return JSONResponse(content={
            "method": "sendMessage",
            "chat_id": clean_chat_id,
            "text": formatted_reply,
            "parse_mode": "HTML"
        })
        
    except Exception as e:
        logger.error(f"Error processing Telegram webhook: {e}", exc_info=True)
        return {"status": "ok"}


@router.get("/telegram/setup")
async def setup_telegram_webhook(url: str = Query(..., description="Full webhook URL, e.g. https://my-space.hf.space/webhook/telegram")):
    """
    Helper endpoint to easily register this server as the Telegram Bot Webhook.
    Example: GET /webhook/telegram/setup?url=https://luthfillah-whatsapp-chatbot-api.hf.space/webhook/telegram
    """
    result = await telegram_service.register_telegram_webhook(url)
    return result


