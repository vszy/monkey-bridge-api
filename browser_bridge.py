import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator, Optional, List, Dict, Any
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ChatGPTBridge")

class BrowserBridge:
    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page_chatgpt: Optional[Page] = None
        self.cdp = None
        self._current_network_queue: Optional[asyncio.Queue] = None
        self._lock = asyncio.Lock()
        self._is_busy = False
        self._initialized = False
        self._recent_logs: List[str] = []
        self._accounts: Dict[str, Any] = {
            "chatgpt": {
                "is_logged_in": False,
                "type": "Guest",
                "label": "Guest Mode (Not Logged In)",
                "name": "Anonymous (Guest)",
                "email": "None",
                "plan": "Free Web Tier (Guest)"
            }
        }

    def log(self, message: str, level: str = "INFO"):
        entry = f"[{time.strftime('%H:%M:%S')}] [{level}] {message}"
        self._recent_logs.append(entry)
        if len(self._recent_logs) > 200:
            self._recent_logs.pop(0)
        getattr(logger, level.lower(), logger.info)(message)

    @property
    def is_busy(self) -> bool:
        return self._is_busy

    @property
    def is_ready(self) -> bool:
        return self._initialized and self.context is not None

    def get_status(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "busy": self._is_busy,
            "accounts": self._accounts,
            "urls": {
                "chatgpt": self.page_chatgpt.url if self.page_chatgpt else None
            },
            "logs": self._recent_logs[-30:]
        }

    def resolve_provider(self, model: str = "", explicit_provider: Optional[str] = None) -> str:
        return "chatgpt"

    async def initialize(self):
        """Initializes browser and launches persistent context."""
        async with self._lock:
            if self._initialized and self.context:
                return
            await self._start_browser()

    async def _start_browser(self):
        self.log("Launching unified browser engine (Chrome)...")
        self.playwright = await async_playwright().start()

        profile_dir = os.path.abspath(config.PROFILE_DIR)
        os.makedirs(profile_dir, exist_ok=True)

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--start-maximized"
        ]

        executable = config.CHROME_PATH if os.path.exists(config.CHROME_PATH) else None
        if executable:
            self.log(f"Using Google Chrome from: {executable}")
        else:
            self.log("Custom Chrome not found. Using bundled Chromium.")

        try:
            if config.CDP_URL:
                self.log(f"Connecting to existing browser via CDP: {config.CDP_URL}")
                browser = await self.playwright.chromium.connect_over_cdp(config.CDP_URL)
                self.context = browser.contexts[0] if browser.contexts else await browser.new_context()
            else:
                self.log(f"Loading persistent profile from: {profile_dir}")
                self.context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    executable_path=executable,
                    headless=config.HEADLESS,
                    viewport={"width": 1440, "height": 900},
                    args=launch_args
                )

            # Pre-initialize ChatGPT page
            self.page_chatgpt = self.context.pages[0] if self.context.pages else await self.context.new_page()

            # Initialize CDP session for real-time network stream capture
            await self._ensure_cdp_fetch()

            self.log("Preloading ChatGPT (chatgpt.com)...")
            await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
            await self._dismiss_chatgpt_dialogs()

            self._initialized = True
            await self.update_all_accounts()
            self.log("ChatGPT interface ready!")

        except Exception as e:
            self.log(f"Browser startup error: {str(e)}", "ERROR")
            self._initialized = False
            raise

    async def _ensure_cdp_fetch(self):
        """Ensures CDP session and Fetch interception are active."""
        try:
            if not self.cdp:
                self.cdp = await self.page_chatgpt.context.new_cdp_session(self.page_chatgpt)
                self.cdp.on("Fetch.requestPaused", lambda evt: asyncio.create_task(self._on_fetch_paused(evt)))

            await self.cdp.send("Fetch.enable", {
                "patterns": [
                    {"urlPattern": "*backend-api/f/conversation*", "requestStage": "Response"}
                ]
            })
        except Exception as e:
            try:
                self.cdp = await self.page_chatgpt.context.new_cdp_session(self.page_chatgpt)
                self.cdp.on("Fetch.requestPaused", lambda evt: asyncio.create_task(self._on_fetch_paused(evt)))
                await self.cdp.send("Fetch.enable", {
                    "patterns": [
                        {"urlPattern": "*backend-api/f/conversation*", "requestStage": "Response"}
                    ]
                })
            except Exception as err:
                self.log(f"CDP Fetch enable notice: {err}", "WARNING")

    async def _on_fetch_paused(self, evt: Dict[str, Any]):
        req_id = evt.get('requestId')
        url = evt.get('request', {}).get('url', '')
        if not url.endswith("/backend-api/f/conversation"):
            try:
                await self.cdp.send("Fetch.continueResponse", {"requestId": req_id})
            except Exception:
                pass
            return

        try:
            stream_info = await self.cdp.send("Fetch.takeResponseBodyAsStream", {"requestId": req_id})
            handle = stream_info.get("stream")
            asyncio.create_task(self._consume_cdp_stream(handle))
        except Exception as err:
            self.log(f"Error taking response body as stream: {err}", "ERROR")
            if self._current_network_queue:
                self._current_network_queue.put_nowait(None)

    async def _consume_cdp_stream(self, handle: str):
        """Streams and parses chunked SSE deltas directly from the CDP stream."""
        buffer = ""
        try:
            while True:
                chunk_res = await self.cdp.send("IO.read", {"handle": handle, "size": 32768})
                data = chunk_res.get("data", "")
                eof = chunk_res.get("eof", False)

                if data:
                    buffer += data
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        raw_data = line[5:].strip()
                        if raw_data == "[DONE]":
                            eof = True
                            break
                        try:
                            obj = json.loads(raw_data)
                            if isinstance(obj, dict):
                                if obj.get("type") == "message_stream_complete":
                                    eof = True
                                    break

                                patches = []
                                if "v" in obj and isinstance(obj["v"], list):
                                    patches.extend(obj["v"])
                                elif obj.get("o") == "patch" and "v" in obj and isinstance(obj["v"], list):
                                    patches.extend(obj["v"])

                                for p in patches:
                                    if isinstance(p, dict) and p.get("p", "").startswith("/message/content/parts") and p.get("o") == "append":
                                        v = p.get("v")
                                        if isinstance(v, str) and v and self._current_network_queue:
                                            self._current_network_queue.put_nowait(v)
                        except Exception:
                            pass

                if eof:
                    break
                await asyncio.sleep(0.01)
        except Exception as e:
            self.log(f"Stream consumer error: {e}", "WARNING")
        finally:
            try:
                await self.cdp.send("IO.close", {"handle": handle})
            except Exception:
                pass
            if self._current_network_queue:
                self._current_network_queue.put_nowait(None)

    # ------------------ Account State Detection ------------------

    async def update_all_accounts(self) -> Dict[str, Any]:
        """Scans account state for ChatGPT."""
        await self.update_chatgpt_account()
        return self._accounts

    async def update_chatgpt_account(self) -> Dict[str, Any]:
        if not self.page_chatgpt or self.page_chatgpt.is_closed():
            return self._accounts["chatgpt"]
        try:
            info = await self.page_chatgpt.evaluate('''() => {
                const allButtons = Array.from(document.querySelectorAll('button, a'));
                const hasLoginButton = allButtons.some(el => {
                    const txt = el.innerText?.trim();
                    return txt === 'Log in' || txt === 'Sign up for free' || txt === 'Sign up';
                });

                const userMenuButton = document.querySelector('button[data-testid="user-menu-button"], button[data-testid="profile-button"], [data-testid="profile-button"]');
                const avatarImg = document.querySelector('img[alt*="avatar" i], img[alt*="profile" i]');

                const isActuallyLoggedIn = !hasLoginButton && (!!userMenuButton || !!avatarImg);
                let userName = null;

                if (userMenuButton) {
                    const txt = userMenuButton.innerText?.trim();
                    if (txt && !txt.includes('Remove') && !txt.includes('Log in')) {
                        userName = txt;
                    }
                }
                if (!userName && avatarImg && avatarImg.alt) {
                    userName = avatarImg.alt;
                }

                if (!isActuallyLoggedIn) {
                    return {
                        is_logged_in: false,
                        type: "Guest",
                        label: "Guest Mode (Not Logged In)",
                        name: "Anonymous (Guest)",
                        email: "None",
                        plan: "Free Web Tier"
                    };
                }
                return {
                    is_logged_in: true,
                    type: "Logged In",
                    label: `Logged In (${userName || 'Account'})`,
                    name: userName || "Authenticated User",
                    email: "Stored in Profile",
                    plan: (userName && userName.includes('Plus')) ? "ChatGPT Plus" : "Standard / Plus"
                };
            }''')
            self._accounts["chatgpt"] = info
            return info
        except Exception:
            return self._accounts["chatgpt"]

    # ------------------ Message Formatting ------------------

    def format_messages(self, messages: List[Any]) -> str:
        """Formats an array of OpenAI messages into a single prompt string."""
        if not messages:
            return ""

        def extract_text(content: Any) -> str:
            if content is None:
                return ""
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        parts.append(item.get("text", item.get("content", str(item))))
                    else:
                        parts.append(str(item))
                return "\n".join(parts)
            if isinstance(content, dict):
                return content.get("text", str(content))
            return str(content)

        if len(messages) == 1:
            return extract_text(messages[0].content)

        formatted_parts = []
        for msg in messages:
            role = getattr(msg, "role", "user").capitalize()
            content = extract_text(getattr(msg, "content", ""))
            if not content.strip():
                continue
            if role.lower() == "system":
                formatted_parts.append(f"[System Instruction]: {content}\n")
            elif role.lower() == "user":
                formatted_parts.append(f"[User]: {content}")
            elif role.lower() == "assistant":
                formatted_parts.append(f"[Assistant]: {content}")
            else:
                formatted_parts.append(f"[{role}]: {content}")

        formatted_parts.append("\n[Assistant]:")
        return "\n\n".join(formatted_parts)

    # ------------------ ChatGPT Automation ------------------

    async def _dismiss_chatgpt_dialogs(self):
        if not self.page_chatgpt:
            return
        selectors = [
            "button:has-text('Stay logged out')",
            "button:has-text('Dismiss')",
            "button:has-text('Continue without logging in')",
            "button[aria-label='Dismiss']",
            "button[aria-label='Close']"
        ]
        for sel in selectors:
            try:
                btn = await self.page_chatgpt.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.3)
            except Exception:
                pass

    async def _get_chatgpt_composer(self):
        selectors = [
            "#prompt-textarea",
            "#mobile-composer-prompt",
            "textarea[placeholder*='ChatGPT']",
            "textarea[placeholder*='Ask']",
            "div[contenteditable='true']",
            "textarea"
        ]
        for _ in range(10):
            for sel in selectors:
                try:
                    el = await self.page_chatgpt.query_selector(sel)
                    if el and await el.is_visible():
                        return el
                except Exception:
                    pass
            await asyncio.sleep(0.3)

        try:
            return await self.page_chatgpt.wait_for_selector(", ".join(selectors), timeout=8000, state="visible")
        except Exception:
            return None

    async def _stream_chatgpt(self, prompt: str, new_chat: bool) -> AsyncGenerator[str, None]:
        if not self.page_chatgpt or self.page_chatgpt.is_closed():
            self.page_chatgpt = await self.context.new_page()
            await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="domcontentloaded")

        if new_chat:
            self.log("ChatGPT: resetting conversation...")
            try:
                new_btn = await self.page_chatgpt.query_selector("a[href='/'], button[aria-label*='New chat']")
                if new_btn and await new_btn.is_visible():
                    await new_btn.click()
                    await asyncio.sleep(0.4)
                else:
                    await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="domcontentloaded")
                    await asyncio.sleep(0.5)
                await self._dismiss_chatgpt_dialogs()
            except Exception:
                pass

        await self._ensure_cdp_fetch()

        composer = await self._get_chatgpt_composer()
        if not composer:
            await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="domcontentloaded")
            await self._dismiss_chatgpt_dialogs()
            composer = await self._get_chatgpt_composer()
            if not composer:
                raise RuntimeError("Could not find ChatGPT input composer.")

        # Initialize fresh network queue for this request
        self._current_network_queue = asyncio.Queue()

        self.log(f"ChatGPT: sending prompt ({len(prompt)} chars)...")
        await composer.click()
        await composer.fill(prompt)
        await asyncio.sleep(0.3)

        send_btn = await self.page_chatgpt.query_selector("button[aria-label*='Send'], button[data-testid='send-button']")
        if send_btn and await send_btn.is_visible():
            await send_btn.click()
        else:
            await self.page_chatgpt.keyboard.press("Enter")

        self.log("ChatGPT: prompt submitted. Streaming purely from network...")
        token_count = 0
        start_time = time.time()
        timeout = config.REQUEST_TIMEOUT

        while True:
            try:
                token = await asyncio.wait_for(self._current_network_queue.get(), timeout=timeout)
                if token is None:  # Sentinel signals end of SSE stream
                    break
                token_count += len(token)
                yield token
            except asyncio.TimeoutError:
                self.log("ChatGPT network stream timed out.", "WARNING")
                break

        elapsed = time.time() - start_time
        self.log(f"ChatGPT network stream complete! ({token_count} chars in {elapsed:.2f}s)")

        # Reset web UI state machine so the composer is immediately ready for next prompt
        try:
            stop_btn = await self.page_chatgpt.query_selector("button[aria-label*='Stop'], button[data-testid*='stop']")
            if stop_btn and await stop_btn.is_visible():
                await stop_btn.click()
                await asyncio.sleep(0.2)
        except Exception:
            pass

    # ------------------ Execution & Dispatcher ------------------

    async def new_chat(self):
        """Resets ChatGPT conversation."""
        if self.page_chatgpt:
            try:
                await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="domcontentloaded")
            except Exception:
                pass

    async def send_chat_completion(
        self,
        prompt: str,
        model: str = "gpt-4o",
        provider: Optional[str] = None,
        new_chat: bool = True
    ) -> str:
        """Non-streaming chat completion."""
        full_text = ""
        async for chunk in self.stream_chat_completion(
            prompt=prompt,
            model=model,
            provider=provider,
            new_chat=new_chat
        ):
            full_text += chunk
        return full_text

    async def stream_chat_completion(
        self,
        prompt: str,
        model: str = "gpt-4o",
        provider: Optional[str] = None,
        new_chat: bool = True
    ) -> AsyncGenerator[str, None]:
        """Streaming generator for ChatGPT."""
        async with self._lock:
            self._is_busy = True
            try:
                if not self._initialized or not self.context:
                    await self._start_browser()

                self.log(f"Processing request with ChatGPT (Model: {model})")
                async for chunk in self._stream_chatgpt(prompt, new_chat):
                    yield chunk

            except Exception as e:
                self.log(f"Exception during completion: {str(e)}", "ERROR")
                raise
            finally:
                self._is_busy = False

    async def close(self):
        """Closes browser context and Playwright instance."""
        async with self._lock:
            try:
                if self.context:
                    await self.context.close()
                if self.playwright:
                    await self.playwright.stop()
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
            finally:
                self.context = None
                self.page_chatgpt = None
                self.playwright = None
                self._initialized = False

# Global singleton
bridge = BrowserBridge()
