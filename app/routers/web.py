import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["Web UI"])


@router.get("/")
def serve_dashboard():
    """Serves the main interactive simulator and schedule dashboard."""
    static_file = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    if not os.path.exists(static_file):
        raise HTTPException(status_code=404, detail="Dashboard UI file not found.")
    return FileResponse(static_file)


@router.get("/privacy")
def serve_privacy_policy():
    """Serves the Privacy Policy required for Meta WhatsApp App verification and publishing."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Privacy Policy - Tennis Court Surabaya WhatsApp Bot</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; }
            h1, h2 { color: #1a73e8; }
            .container { background: #fdfdfd; border: 1px solid #eee; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
            footer { margin-top: 40px; font-size: 0.9em; color: #666; border-top: 1px solid #ddd; padding-top: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Privacy Policy</h1>
            <p><strong>Last Updated:</strong> July 7, 2026</p>
            
            <h2>1. Information We Collect</h2>
            <p>When you interact with the Tennis Court Surabaya WhatsApp Chatbot, we collect only the necessary information required to facilitate court reservations and customer support. This includes your phone number, message content, and booking details (such as date, time, and court preferences).</p>
            
            <h2>2. How We Use Your Information</h2>
            <p>Your information is used strictly for:</p>
            <ul>
                <li>Processing and checking tennis court schedule availability.</li>
                <li>Confirming tennis court bookings and sending schedule reminders.</li>
                <li>Answering customer service inquiries via AI-assisted messaging.</li>
            </ul>
            
            <h2>3. Data Sharing and Disclosure</h2>
            <p>We do not sell, rent, or share your personal information with third parties for marketing purposes. Data is processed securely through Meta WhatsApp Cloud API and OpenRouter AI models solely for generating automated chatbot responses.</p>
            
            <h2>4. Data Retention and Deletion</h2>
            <p>Booking records are maintained in our system for operational scheduling. If you wish to request deletion of your chat history or contact details from our database, please contact our administrator.</p>
            
            <h2>5. Contact Us</h2>
            <p>If you have any questions or concerns regarding this Privacy Policy or how your data is handled, please contact us at: <strong>luthfillahakhtarf@gmail.com</strong></p>
            
            <footer>
                &copy; 2026 Tennis Court Surabaya. All rights reserved.
            </footer>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

