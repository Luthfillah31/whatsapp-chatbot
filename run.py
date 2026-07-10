import os
import uvicorn

if __name__ == "__main__":
    # Supports Railway dynamic $PORT, Hugging Face Spaces (if PORT=7860), or local default 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
