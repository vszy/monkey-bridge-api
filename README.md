# ChatGPT Web OpenAI-Compatible API Bridge

An OpenAI-compatible REST API server that bridges incoming `/v1/chat/completions` requests to **ChatGPT Web (chatgpt.com)** and returns streaming or non-streaming responses formatted identically to OpenAI's API.

---

## Features

- **OpenAI API Standard Endpoints**:
  - `POST /v1/chat/completions` (JSON & Server-Sent Events SSE streaming)
  - `GET /v1/models` (Advertised models: `gpt-4o`, `gpt-4o-mini`, `chatgpt-web`, `o1-preview`)
  - `GET /health` (Status & real-time browser diagnostics)
- **Browser Automation via Playwright**:
  - Connects to Google Chrome or bundled Chromium with real anti-detection flags (`--disable-blink-features=AutomationControlled`).
  - Persistent profile storage (`./chatgpt_profile`): Log in once to your ChatGPT account (free or Plus) and your session persists across restarts.
  - Guest mode support: Works out-of-the-box even without logging in.
- **Pure Network-Level SSE Stream Interception**:
  - Intercepts ChatGPT's internal Server-Sent Events (`/backend-api/f/conversation`) directly via Chrome DevTools Protocol (CDP `Fetch.takeResponseBodyAsStream`).
  - Completely eliminates fragile DOM scraping, polling delays, and text stripping.
- **Automatic Images & Citation Sources Extraction**:
  - Automatically identifies web search images, citations, and reference links in the SSE metadata.
  - Formats images into a responsive `<div class="image-gallery">` card layout and appends clickable deduplicated source links (`### 🔗 Sources & References`).
- **Real-Time Streaming**:
  - High-performance SSE (`stream: true`) token streaming with live delta calculation.
- **Concurrent Request Guard**:
  - Async queue lock serializes requests safely so browser tabs never collide.
- **Interactive Web Dashboard & Playground**:
  - Live test UI at `http://localhost:8000/` with markdown rendering, image card gallery, latency counter, system prompt, and real-time server activity terminal.
- **Drop-in Compatibility**:
  - Works with Cursor, LibreChat, Open WebUI, NextChat, LangChain, or the official OpenAI Python/Node SDKs.

---

## Quick Start

### 1. Run the Server

On Windows, simply double-click `run.bat` or run:

```bash
.\venv\Scripts\python.exe app.py
```

The server will start on:
- **Web Dashboard & Chat Playground**: [http://localhost:8000](http://localhost:8000)
- **OpenAI API Base**: [http://localhost:8000/v1](http://localhost:8000/v1)

### 2. Log in (Optional but Recommended)

When the browser window opens:
1. Log in to your ChatGPT account if you want access to your Plus subscription, GPT-4o, custom GPTs, and chat history.
2. The browser context will remember your session in `chatgpt_profile/`.

---

## Client Integration Examples

### Official Python OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="dummy-key-not-needed"
)

# Streaming
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "You are an expert programmer."},
        {"role": "user", "content": "Write a python function to compute primes."}
    ],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

### cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "Tell me 3 interesting space facts."}
    ],
    "stream": false
  }'
```

### Third-Party Apps (LibreChat, Open WebUI, Cursor)

Set your application settings:
- **API Base URL**: `http://localhost:8000/v1`
- **API Key**: `sk-any-key`
- **Model**: `gpt-4o` or `chatgpt-web`

---

## Configuration (`config.py` or Environment Variables)

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Host to bind the API server |
| `PORT` | `8000` | Port for the API server |
| `HEADLESS` | `false` | Run browser in headless mode (`true` or `false`) |
| `CHROME_PATH` | `C:\Program Files\Google\Chrome\Application\chrome.exe` | Path to Google Chrome binary |
| `PROFILE_DIR` | `./chatgpt_profile` | Directory for persistent cookies and session |
| `REQUEST_TIMEOUT` | `120` | Maximum seconds to wait for generation |
