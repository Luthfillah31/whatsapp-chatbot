import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.models.db_models import init_db
from app.routers import web, api, webhooks

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="🎾 Sistem Reservasi Lapangan Tenis Warga - Komplek Perumahan",
    description="Production-grade AI chatbot powered by OpenRouter for residential complex tennis court reservations via Telegram & WhatsApp.",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
def on_startup():
    logger.info("Initializing database tables...")
    init_db()
    logger.info("Database initialized successfully!")

# Mount static directory for UI assets
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include routers
app.include_router(web.router)
app.include_router(api.router)
app.include_router(webhooks.router)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Tennis Court Chatbot API"}
