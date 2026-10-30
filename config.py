import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))

# Browser configuration
HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
CHROME_PATH = os.getenv("CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
PROFILE_DIR = os.getenv("PROFILE_DIR", str(BASE_DIR / "chatgpt_profile"))

# Optional CDP connection (e.g. "http://localhost:9222" if user launched Chrome with --remote-debugging-port=9222)
CDP_URL = os.getenv("CDP_URL", None)

# URLs
CHATGPT_URL = "https://chatgpt.com"

# Timeout settings
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 120))  # seconds
STREAM_POLL_INTERVAL = 0.2  # seconds

# Available models advertised in /v1/models
AVAILABLE_MODELS = [
    {
        "id": "gpt-4o",
        "object": "model",
        "created": 1715367049,
        "owned_by": "openai"
    },
    {
        "id": "gpt-4o-mini",
        "object": "model",
        "created": 1715367049,
        "owned_by": "openai"
    },
    {
        "id": "chatgpt-web",
        "object": "model",
        "created": 1715367049,
        "owned_by": "monkey-bridge"
    },
    {
        "id": "o1-preview",
        "object": "model",
        "created": 1725367049,
        "owned_by": "openai"
    }
]
