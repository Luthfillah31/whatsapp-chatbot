import sys
import json
import httpx
import argparse
from typing import Dict, Any

def build_mock_meta_payload(phone: str, name: str, message: str) -> Dict[str, Any]:
    """Constructs a standard Meta WhatsApp Cloud API webhook JSON payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550100",
                                "phone_number_id": "100000001"
                            },
                            "contacts": [
                                {
                                    "profile": {"name": name},
                                    "wa_id": phone
                                }
                            ],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": "wamid.HBgLMTU1NTAxOTIVAgARGBI1QTZFRjAwQjQ1Q0EwMDAwAA==",
                                    "timestamp": "1720000000",
                                    "type": "text",
                                    "text": {"body": message}
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

def main():
    parser = argparse.ArgumentParser(description="Simulate incoming Meta WhatsApp Cloud API webhook message to local FastAPI server.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhook/whatsapp", help="Target webhook endpoint URL")
    parser.add_argument("--phone", default="0812345678", help="Sender WhatsApp phone number")
    parser.add_argument("--name", default="Luthfi Akhtar", help="Sender profile display name")
    parser.add_argument("--msg", default="Halo! Apakah ada lapangan tenis kosong hari ini jam 16:00?", help="Message body text")
    
    args = parser.parse_args()
    
    payload = build_mock_meta_payload(args.phone, args.name, args.msg)
    
    print(f"📡 Sending mock Meta WhatsApp Webhook to {args.url}...")
    print(f"👤 Sender: {args.name} ({args.phone})")
    print(f"💬 Message: '{args.msg}'\n")
    
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(args.url, json=payload)
            print(f"✅ Response Status: {resp.status_code}")
            print(f"📦 Response Body: {resp.text}")
            print("\n💡 NOTE: Check your local FastAPI server logs to see the background LLM processing and simulated WhatsApp reply!")
    except Exception as e:
        print(f"❌ Error sending webhook request: {e}")
        print("Please ensure that the local FastAPI server is running (e.g. via 'pixi run dev' or 'pixi run start').")
        sys.exit(1)

if __name__ == "__main__":
    main()
