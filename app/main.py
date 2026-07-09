import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.models.db_models import init_db
from app.routers import web, api, webhooks, payment_notification

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager

# Initialize database on startup via modern lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database tables...")
    init_db()
    logger.info("Database initialized successfully!")
    yield

# Initialize FastAPI app
app = FastAPI(
    title="🎾 Sistem Reservasi Lapangan Tenis Warga - Komplek Perumahan",
    description="Production-grade AI chatbot powered by OpenRouter for residential complex tennis court reservations via Telegram & WhatsApp.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directory for UI assets
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include routers
app.include_router(web.router)
app.include_router(api.router)
app.include_router(webhooks.router)
app.include_router(payment_notification.router)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Tennis Court Chatbot API"}
