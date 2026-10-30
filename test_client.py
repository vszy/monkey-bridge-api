import json
import httpx
import time
import sys

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://localhost:8000/v1"

def test_models():
    print("\n--- Testing GET /v1/models ---")
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{BASE_URL}/models")
        print(f"Status: {resp.status_code}")
        print("Models available:", json.dumps(resp.json(), indent=2))

def test_non_streaming():
    print("\n--- Testing POST /v1/chat/completions (Non-Streaming) ---")
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "What is the capital of France? Reply in one sentence."}
        ],
        "stream": False
    }
    t0 = time.time()
    with httpx.Client(timeout=120) as client:
        resp = client.post(f"{BASE_URL}/chat/completions", json=payload)
        print(f"Status: {resp.status_code} ({time.time() - t0:.2f}s)")
        data = resp.json()
        print("Response JSON:")
        print(json.dumps(data, indent=2))
        print("\nExtracted content:", data["choices"][0]["message"]["content"])

def test_streaming():
    print("\n--- Testing POST /v1/chat/completions (Streaming SSE) ---")
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Count from 1 to 5 with emojis."}
        ],
        "stream": True
    }
    t0 = time.time()
    with httpx.Client(timeout=120) as client:
        with client.stream("POST", f"{BASE_URL}/chat/completions", json=payload) as resp:
            print(f"Streaming connected ({time.time() - t0:.2f}s)...")
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    print("\n[STREAM DONE]")
                    break
                try:
                    chunk = json.loads(data_str)
                    content = chunk["choices"][0]["delta"].get("content", "")
                    if content:
                        print(content, end="", flush=True)
                except Exception as e:
                    print("Error parsing chunk:", e)
    print()

if __name__ == "__main__":
    test_models()
    test_non_streaming()
    test_streaming()
