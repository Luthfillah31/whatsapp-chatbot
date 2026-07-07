---
title: WhatsApp Tennis Court Chatbot API
emoji: 🎾
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
---

# 🎾 WhatsApp Tennis Court Booking Chatbot

A production-ready, AI-powered WhatsApp chatbot built with **Python (FastAPI)**, **OpenRouter API** (with structured Tool & Function Calling), and **Google Calendar API / SQL Database** for managing bookings across 2 tennis courts.

---

## ✨ Features

- **🤖 AI Receptionist via OpenRouter**: Powered by state-of-the-art LLMs (e.g., Llama 3.3 70B, GPT-4o-mini, Qwen 2.5 Coder) via OpenRouter, capable of understanding natural language inquiries, extracting dates/times, and executing calendar checks without hallucinations.
- **📅 Dual Scheduling Engine**:
  - **Local SQL Database (SQLite / Supabase / PostgreSQL)**: Works out of the box with zero configuration needed.
  - **Google Calendar Sync**: Easily connect Google Calendar API to automatically create and sync live reservations for **Tennis Court 1** and **Tennis Court 2**.
- **💬 Multi-Platform Webhook Gateways**:
  - Native **Meta WhatsApp Cloud API** verification and message processing.
  - Native **Telegram Bot API** support (Free & Instant setup via `@BotFather`).
  - Compatible with open-source WhatsApp wrappers (**Evolution API / Baileys**).
- **🖥️ Built-in Interactive Web Simulator & Schedule Dashboard**:
  - Test the chatbot in real-time directly from your browser without needing a WhatsApp Business account or phone setup!
  - Visual hourly availability grid for both courts that updates dynamically as the AI books or cancels reservations.

---

## 🚀 Quickstart Guide

### 1. Install Dependencies
Make sure you have Python 3.10+ installed.
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` (already created by default):
```bash
cp .env.example .env
```
Open `.env` and paste your OpenRouter API Key:
```env
OPENROUTER_API_KEY="your_actual_openrouter_key_here"
```

### 3. Run the Development Server
Start the FastAPI server with live reload:
```bash
uvicorn app.main:app --reload --port 8000
```

### 4. Test in the Web Simulator
Open your browser and navigate to:
👉 **http://localhost:8000**

You will see the **Tennis Club Reception Simulator**. Try sending these messages:
- *"Hi! What are your opening hours and court rental fees?"*
- *"Do you have any courts open tomorrow afternoon around 4pm?"*
- *"Please book Court 1 for me tomorrow from 16:00 to 17:00. My name is Sarah and my phone is +15550192."*
- *"Can you list all my current bookings for +15550192?"*
- *"Cancel my reservation for Court 1 tomorrow at 16:00."*

---

## 🏗️ Project Architecture

```
d:/project/whatsapp-chatbot/
├── app/
│   ├── main.py              # Application initialization & CORS setup
│   ├── config.py            # Environment management (pydantic-settings)
│   ├── models/
│   │   ├── schemas.py       # Pydantic data models for webhooks & tool calling
│   │   └── db_models.py     # SQLAlchemy models (Bookings, Chat History)
│   ├── services/
│   │   ├── llm_service.py   # OpenRouter AI client & function execution loop
│   │   ├── calendar_service.py # Scheduling logic & conflict prevention
│   │   └── whatsapp_service.py # WhatsApp message parsing & outbound sender
│   ├── routers/
│   │   ├── webhooks.py      # Webhook endpoints (/webhook/whatsapp, etc.)
│   │   ├── api.py           # REST endpoints for schedule queries
│   │   └── web.py           # Static dashboard serving
│   └── static/              # Modern Glassmorphism Web Simulator UI
├── tests/                   # Automated unit & integration tests
├── requirements.txt         # Python package dependencies
└── Dockerfile               # Containerization for deployment
```

---

## 🌐 Connecting to WhatsApp & Google Calendar

### Setting up Meta WhatsApp Cloud API
1. Create an app on the [Meta Developer Portal](https://developers.facebook.com/).
2. Add the **WhatsApp** product and generate a temporary/permanent access token.
3. In your `.env`, set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, and choose a `WHATSAPP_VERIFY_TOKEN`.
4. Point your Meta Webhook URL to your public server domain (or ngrok/cloudflare tunnel):
   `https://your-domain.com/webhook/whatsapp`

### Setting up Google Calendar API (Optional)
1. Go to Google Cloud Console and create a Service Account.
2. Download the JSON key file and save it in your project folder (e.g., `service_account.json`).
3. Share your 2 Google Calendars (Court 1 and Court 2) with the Service Account email address with **Make changes to events** permission.
4. Set the calendar IDs and path in `.env`:
   ```env
   GOOGLE_SERVICE_ACCOUNT_FILE="service_account.json"
   GOOGLE_CALENDAR_ID_COURT_1="calendar_id_1@group.calendar.google.com"
   GOOGLE_CALENDAR_ID_COURT_2="calendar_id_2@group.calendar.google.com"
   ```
