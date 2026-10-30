import asyncio
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
        self.page_gemini: Optional[Page] = None
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
            },
            "gemini": {
                "is_logged_in": False,
                "type": "Guest",
                "label": "Guest Mode (Not Logged In)",
                "name": "Anonymous (Google Guest)",
                "email": "None",
                "plan": "Free Web Tier"
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
                "chatgpt": self.page_chatgpt.url if self.page_chatgpt else None,
                "gemini": self.page_gemini.url if self.page_gemini else None
            },
            "logs": self._recent_logs[-30:]
        }

    def resolve_provider(self, model: str = "", explicit_provider: Optional[str] = None) -> str:
        if explicit_provider:
            p = explicit_provider.lower().strip()
            if "gemini" in p or "google" in p:
                return "gemini"
            return "chatgpt"
        m = (model or "").lower().strip()
        if "gemini" in m or m.startswith("google"):
            return "gemini"
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
            self.log("Preloading ChatGPT (chatgpt.com)...")
            await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
            await self._dismiss_chatgpt_dialogs()

            # Pre-initialize Gemini page
            self.page_gemini = await self.context.new_page()
            self.log("Preloading Gemini (gemini.google.com)...")
            await self.page_gemini.goto(config.GEMINI_URL, wait_until="domcontentloaded", timeout=60000)

            self._initialized = True
            await self.update_all_accounts()
            self.log("Both ChatGPT and Google Gemini interfaces ready!")

        except Exception as e:
            self.log(f"Browser startup error: {str(e)}", "ERROR")
            self._initialized = False
            raise

    # ------------------ Account State Detection ------------------

    async def update_all_accounts(self) -> Dict[str, Any]:
        """Scans account states for both ChatGPT and Google Gemini."""
        await asyncio.gather(
            self.update_chatgpt_account(),
            self.update_gemini_account(),
            return_exceptions=True
        )
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

    async def update_gemini_account(self) -> Dict[str, Any]:
        if not self.page_gemini or self.page_gemini.is_closed():
            return self._accounts["gemini"]
        try:
            info = await self.page_gemini.evaluate('''() => {
                // Check for Google Sign-in button
                const signInBtns = Array.from(document.querySelectorAll('a, button')).filter(el => {
                    const txt = el.innerText?.trim();
                    return txt === 'Sign in' || txt === 'Sign In';
                });

                // Google account avatar / profile in top right
                const profileBtn = document.querySelector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i], [aria-label*="Google Account" i]');
                const isLogged = !signInBtns.length || !!profileBtn;

                let name = null;
                let email = null;
                if (profileBtn) {
                    const aria = profileBtn.getAttribute('aria-label') || '';
                    name = aria.replace('Google Account:', '').trim();
                }

                if (!isLogged) {
                    return {
                        is_logged_in: false,
                        type: "Guest",
                        label: "Guest Mode (Not Logged In)",
                        name: "Anonymous (Google Guest)",
                        email: "None",
                        plan: "Free Web Tier"
                    };
                }
                return {
                    is_logged_in: true,
                    type: "Logged In",
                    label: `Google Account (${name || 'Logged In'})`,
                    name: name || "Google Account",
                    email: email || "Active Session",
                    plan: "Gemini Standard / Advanced"
                };
            }''')
            self._accounts["gemini"] = info
            return info
        except Exception:
            return self._accounts["gemini"]

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
        for sel in selectors:
            try:
                el = await self.page_chatgpt.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                pass
        try:
            return await self.page_chatgpt.wait_for_selector(", ".join(selectors), timeout=8000, state="visible")
        except Exception:
            return None

    async def _stream_chatgpt(self, prompt: str, new_chat: bool) -> AsyncGenerator[str, None]:
        if not self.page_chatgpt or self.page_chatgpt.is_closed():
            self.page_chatgpt = await self.context.new_page()
            await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="networkidle")

        if new_chat:
            self.log("ChatGPT: starting new conversation...")
            try:
                new_btn = await self.page_chatgpt.query_selector("a[href='/'], button[aria-label*='New chat']")
                if new_btn and await new_btn.is_visible():
                    await new_btn.click()
                else:
                    await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="domcontentloaded")
                await asyncio.sleep(0.8)
                await self._dismiss_chatgpt_dialogs()
            except Exception:
                pass

        composer = await self._get_chatgpt_composer()
        if not composer:
            await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="networkidle")
            await self._dismiss_chatgpt_dialogs()
            composer = await self._get_chatgpt_composer()
            if not composer:
                raise RuntimeError("Could not find ChatGPT input composer.")

        self.log(f"ChatGPT: sending prompt ({len(prompt)} chars)...")
        await composer.click()
        await composer.fill(prompt)
        await asyncio.sleep(0.3)

        send_btn = await self.page_chatgpt.query_selector("button[aria-label*='Send'], button[data-testid='send-button']")
        if send_btn and await send_btn.is_visible():
            await send_btn.click()
        else:
            await self.page_chatgpt.keyboard.press("Enter")

        self.log("ChatGPT: prompt submitted. Streaming response...")
        previous_text = ""
        start_time = time.time()
        timeout = config.REQUEST_TIMEOUT
        streaming_began = False
        idle_cycles = 0

        while time.time() - start_time < timeout:
            await asyncio.sleep(config.STREAM_POLL_INTERVAL)
            is_streaming = await self.page_chatgpt.evaluate('''() => {
                const stopBtn = document.querySelector('button[aria-label*="Stop"], button[data-testid*="stop"]');
                return !!stopBtn;
            }''')

            current_text = await self.page_chatgpt.evaluate(r'''() => {
                // Find all assistant turns
                const assistantTurns = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
                let targetTurn = assistantTurns.length > 0 ? assistantTurns[assistantTurns.length - 1] : null;

                if (!targetTurn) {
                    const articles = Array.from(document.querySelectorAll('article')).filter(a => {
                        return !a.querySelector('[data-message-author-role="user"]') && !!a.querySelector('.markdown, [class*="markdown"]');
                    });
                    if (articles.length > 0) targetTurn = articles[articles.length - 1];
                }

                if (!targetTurn) return "";

                // Find the markdown body inside the assistant turn
                const md = targetTurn.querySelector('.markdown, [class*="markdown"], .whitespace-pre-wrap');
                if (!md) return "";

                // Clone so we don't mutate DOM and remove utility elements
                const clone = md.cloneNode(true);
                clone.querySelectorAll('.sr-only, button, [class*="action"], [class*="feedback"]').forEach(el => el.remove());

                let text = clone.innerText || "";
                text = text.trim();
                
                // Strip any accidental leading "ChatGPT said:" or "ChatGPT"
                if (text.toLowerCase().startsWith('chatgpt said:')) {
                    text = text.slice(13).trim();
                } else if (text.toLowerCase().startsWith('chatgpt')) {
                    text = text.slice(7).trim();
                }

                // Remove footer boilerplate if captured
                const footers = ['ChatGPT is AI and can make mistakes.', 'ChatGPT can make mistakes.'];
                for (const f of footers) {
                    if (text.includes(f)) text = text.split(f)[0].trim();
                }

                return text;
            }''') or ""

            if is_streaming or len(current_text) > 0:
                streaming_began = True

            if current_text and current_text != previous_text:
                if current_text.startswith(previous_text):
                    delta = current_text[len(previous_text):]
                else:
                    # Prefix changed or initial sync: find common prefix length
                    common_len = 0
                    min_len = min(len(previous_text), len(current_text))
                    while common_len < min_len and previous_text[common_len] == current_text[common_len]:
                        common_len += 1
                    delta = current_text[common_len:]

                if delta:
                    previous_text = current_text
                    idle_cycles = 0
                    yield delta
            else:
                idle_cycles += 1

            if streaming_began and not is_streaming and idle_cycles >= 3:
                await asyncio.sleep(0.3)
                self.log(f"ChatGPT stream complete! ({len(previous_text)} chars)")
                break

            if not streaming_began and idle_cycles > 40:
                self.log("ChatGPT: No activity detected after prompt.", "WARNING")
                break

    # ------------------ Gemini Automation ------------------

    async def _get_gemini_composer(self):
        selectors = [
            "rich-textarea .ql-editor",
            "div[contenteditable='true']",
            "div.ql-editor",
            "rich-textarea textarea",
            "rich-textarea"
        ]
        for sel in selectors:
            try:
                el = await self.page_gemini.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                pass
        try:
            return await self.page_gemini.wait_for_selector(", ".join(selectors), timeout=8000, state="visible")
        except Exception:
            return None

    async def _stream_gemini(self, prompt: str, new_chat: bool) -> AsyncGenerator[str, None]:
        if not self.page_gemini or self.page_gemini.is_closed():
            self.page_gemini = await self.context.new_page()
            await self.page_gemini.goto(config.GEMINI_URL, wait_until="networkidle")

        if new_chat:
            self.log("Gemini: starting new chat...")
            try:
                new_btn = await self.page_gemini.query_selector("a[href='/app'], button[aria-label*='New chat' i], button:has-text('New chat')")
                if new_btn and await new_btn.is_visible():
                    await new_btn.click()
                else:
                    await self.page_gemini.goto(config.GEMINI_URL, wait_until="domcontentloaded")
                await asyncio.sleep(0.8)
            except Exception:
                pass

        composer = await self._get_gemini_composer()
        if not composer:
            await self.page_gemini.goto(config.GEMINI_URL, wait_until="networkidle")
            composer = await self._get_gemini_composer()
            if not composer:
                raise RuntimeError("Could not find Google Gemini input composer.")

        self.log(f"Gemini: sending prompt ({len(prompt)} chars)...")
        await composer.click()

        # Fast injection into Quill editor for Gemini
        await self.page_gemini.evaluate('''(text) => {
            const el = document.querySelector('rich-textarea .ql-editor, div.ql-editor, [contenteditable="true"]');
            if (el) {
                el.focus();
                el.innerText = text;
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }''', prompt)
        await asyncio.sleep(0.3)

        # Click send or press Enter
        send_btn = await self.page_gemini.query_selector("button[aria-label*='Send' i], button[aria-label*='Submit' i], button.send-button")
        if send_btn and await send_btn.is_visible():
            await send_btn.click()
        else:
            await self.page_gemini.keyboard.press("Enter")

        self.log("Gemini: prompt submitted. Streaming response...")
        previous_text = ""
        start_time = time.time()
        timeout = config.REQUEST_TIMEOUT
        streaming_began = False
        idle_cycles = 0

        while time.time() - start_time < timeout:
            await asyncio.sleep(config.STREAM_POLL_INTERVAL)
            is_streaming = await self.page_gemini.evaluate('''() => {
                const stopBtn = document.querySelector('button[aria-label*="Stop" i], button.stop-button');
                return !!stopBtn;
            }''')

            current_text = await self.page_gemini.evaluate('''() => {
                const responses = Array.from(document.querySelectorAll('message-content, .model-response-text, .response-container-content, model-response'));
                if (responses.length > 0) {
                    return responses[responses.length - 1].innerText || '';
                }
                return '';
            }''') or ""

            if is_streaming or len(current_text) > 0:
                streaming_began = True

            if len(current_text) > len(previous_text):
                delta = current_text[len(previous_text):]
                previous_text = current_text
                idle_cycles = 0
                yield delta
            else:
                idle_cycles += 1

            if streaming_began and not is_streaming and idle_cycles >= 3:
                self.log(f"Gemini stream complete! ({len(previous_text)} chars)")
                break

            if not streaming_began and idle_cycles > 40:
                self.log("Gemini: No activity detected after prompt.", "WARNING")
                break

    # ------------------ Unified Dispatcher ------------------

    async def new_chat(self, provider: str = "both"):
        """Resets conversation for specified provider or both."""
        if provider in ("chatgpt", "both") and self.page_chatgpt:
            try:
                await self.page_chatgpt.goto(config.CHATGPT_URL, wait_until="domcontentloaded")
            except Exception:
                pass
        if provider in ("gemini", "both") and self.page_gemini:
            try:
                await self.page_gemini.goto(config.GEMINI_URL, wait_until="domcontentloaded")
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
        """Unified streaming generator routing to ChatGPT or Gemini."""
        async with self._lock:
            self._is_busy = True
            try:
                if not self._initialized or not self.context:
                    await self._start_browser()

                chosen_provider = self.resolve_provider(model, provider)
                self.log(f"Routing request to provider: [{chosen_provider.upper()}] (Model: {model})")

                if chosen_provider == "gemini":
                    async for chunk in self._stream_gemini(prompt, new_chat):
                        yield chunk
                else:
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
                self.page_gemini = None
                self.playwright = None
                self._initialized = False

# Global singleton
bridge = BrowserBridge()
