import base64
import hashlib
import logging
from typing import Dict, Any
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def create_midtrans_transaction(
    booking_id: int,
    amount: int,
    customer_name: str,
    customer_phone: str
) -> Dict[str, Any]:
    """
    Creates a new transaction session via Midtrans Snap Sandbox.
    If server keys are not configured, falls back to local mock payment simulation.
    """
    order_id = f"booking-{booking_id}"
    
    # Check if Midtrans keys are set
    server_key = settings.MIDTRANS_SERVER_KEY.strip()
    if not server_key or server_key.lower().startswith("your_") or server_key == "test_key":
        logger.info(f"Midtrans Server Key not configured. Using local mock payment gateway for {order_id}.")
        # Use local mock payment URL (the port/host will be resolved relative to base url in the frontend)
        mock_url = f"/payments/mock?order_id={order_id}&gross_amount={amount}&name={customer_name}"
        return {
            "token": f"mock-token-{booking_id}",
            "redirect_url": mock_url
        }

    # Call Midtrans Sandbox Snap API
    url = "https://app.sandbox.midtrans.com/snap/v1/transactions"
    
    # Basic Authentication Header
    auth_str = f"{server_key}:"
    auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    payload = {
        "transaction_details": {
            "order_id": order_id,
            "gross_amount": amount
        },
        "customer_details": {
            "first_name": customer_name,
            "phone": customer_phone
        },
        "credit_card": {
            "secure": True
        }
    }

    try:
        logger.info(f"Requesting Midtrans transaction: {order_id} with amount {amount}")
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        
        if response.status_code == 201:
            data = response.json()
            return {
                "token": data["token"],
                "redirect_url": data["redirect_url"]
            }
        else:
            logger.error(f"Midtrans returned error code {response.status_code}: {response.text}")
            # Fallback to mock on error to maintain system availability
            mock_url = f"/payments/mock?order_id={order_id}&gross_amount={amount}&name={customer_name}"
            return {
                "token": f"mock-token-fallback-{booking_id}",
                "redirect_url": mock_url
            }
    except Exception as e:
        logger.error(f"Failed to connect to Midtrans Sandbox: {e}")
        mock_url = f"/payments/mock?order_id={order_id}&gross_amount={amount}&name={customer_name}"
        return {
            "token": f"mock-token-fallback-{booking_id}",
            "redirect_url": mock_url
        }


def verify_midtrans_signature(
    order_id: str,
    status_code: str,
    gross_amount: str,
    signature_key: str
) -> bool:
    """
    Verifies that the notification webhook originates from Midtrans by checking the signature key.
    Formula: SHA512(order_id + status_code + gross_amount + ServerKey)
    """
    server_key = settings.MIDTRANS_SERVER_KEY.strip()
    
    # Handle mock signature verification
    if not server_key or server_key.lower().startswith("your_") or server_key == "test_key":
        # In mock mode, check if signature is generated locally or matches simple verification
        mock_payload = f"{order_id}{status_code}{gross_amount}mock_key"
        calculated_mock = hashlib.sha512(mock_payload.encode("utf-8")).hexdigest()
        return signature_key == calculated_mock or signature_key == "mock-signature"

    # Midtrans official verification
    try:
        # Standardize gross_amount by stripping trailing .00 if needed, or keeping it as is
        # Midtrans signature calculation matches the raw gross_amount string sent in their JSON.
        payload = f"{order_id}{status_code}{gross_amount}{server_key}"
        calculated = hashlib.sha512(payload.encode("utf-8")).hexdigest()
        
        is_valid = calculated == signature_key
        if not is_valid:
            logger.warning(f"Signature mismatch. Calculated: {calculated}, Got: {signature_key}")
        return is_valid
    except Exception as e:
        logger.error(f"Error computing Midtrans signature: {e}")
        return False
