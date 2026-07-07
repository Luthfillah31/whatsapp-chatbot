import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, Request, BackgroundTasks, status
from sqlalchemy.orm import Session
from app.models.db_models import get_db, SessionLocal
from app.models.schemas import IncomingChatMessage
from app.services import whatsapp_service, llm_service, telegram_service

logger = logging.getLogger(__name__)

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
    """Background worker to run OpenRouter LLM loop and send WhatsApp reply via Meta API."""
    db = SessionLocal()
    try:
        reply_text = llm_service.process_chat_message(
            db=db,
            phone_number=msg.sender_phone,
            sender_name=msg.sender_name,
            message_text=msg.message_text
        )
        await whatsapp_service.send_meta_whatsapp_message(msg.sender_phone, reply_text)
    except Exception as e:
        logger.error(f"Error processing Meta message in background: {e}", exc_info=True)
    finally:
        db.close()


async def process_and_reply_evolution(msg: IncomingChatMessage):
    """Background worker to run OpenRouter LLM loop and send reply via Evolution API."""
    db = SessionLocal()
    try:
        reply_text = llm_service.process_chat_message(
            db=db,
            phone_number=msg.sender_phone,
            sender_name=msg.sender_name,
            message_text=msg.message_text
        )
        await whatsapp_service.send_evolution_message(msg.sender_phone, reply_text)
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
            logger.info(f"Received Meta WhatsApp message from {msg.sender_phone}: {msg.message_text}")
            background_tasks.add_task(process_and_reply_meta, msg)
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
async def receive_telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming Telegram chat messages from Telegram Bot API webhook.
    Returns 200 OK immediately and processes via OpenRouter in background.
    """
    try:
        payload = await request.json()
        incoming_msgs = telegram_service.parse_telegram_webhook(payload)
        for msg in incoming_msgs:
            logger.info(f"Received Telegram message from {msg.sender_name} ({msg.sender_phone}): {msg.message_text}")
            background_tasks.add_task(process_and_reply_telegram, msg)
    except Exception as e:
        logger.error(f"Error receiving Telegram webhook: {e}", exc_info=True)
        
    return {"status": "ok"}


@router.get("/telegram/setup")
async def setup_telegram_webhook(url: str = Query(..., description="Full webhook URL, e.g. https://my-space.hf.space/webhook/telegram")):
    """
    Helper endpoint to easily register this server as the Telegram Bot Webhook.
    Example: GET /webhook/telegram/setup?url=https://luthfillah-whatsapp-chatbot-api.hf.space/webhook/telegram
    """
    result = await telegram_service.register_telegram_webhook(url)
    return result

