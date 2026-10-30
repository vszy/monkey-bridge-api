import asyncio
import logging
import os
import time
from typing import AsyncGenerator, Optional, List, Dict, Any
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ChatGPTBridge")

class ChatGPTBrowserBridge:
    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._lock = asyncio.Lock()
        self._is_busy = False
        self._initialized = False
        self._recent_logs: List[str] = []
        self._account_info: Dict[str, Any] = {
            "is_logged_in": False,
            "type": "Guest",
            "label": "Guest Mode (Not Logged In)",
            "name": None,
            "email": None,
            "plan": "Guest (Free)"
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
        return self._initialized and self.page is not None

    def get_status(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "busy": self._is_busy,
            "url": self.page.url if self.page else None,
            "account": self._account_info,
            "logs": self._recent_logs[-30:]
        }

    async def update_account_info(self) -> Dict[str, Any]:
        """Detects whether user is in Guest mode or logged into an account."""
        if not self.page or self.page.is_closed():
            return self._account_info
        try:
            info = await self.page.evaluate('''() => {
                const allButtons = Array.from(document.querySelectorAll('button, a'));
                
                // Check if page has visible Login / Sign Up buttons
                const hasLoginButton = allButtons.some(el => {
                    const txt = el.innerText?.trim();
                    return txt === 'Log in' || txt === 'Sign up for free' || txt === 'Sign up' || txt === 'Log in or create account';
                });

                // User menu element in sidebar or header
                const userMenuButton = document.querySelector('button[data-testid="user-menu-button"], button[data-testid="profile-button"], [data-testid="profile-button"]');
                const avatarImg = document.querySelector('img[alt*="avatar" i], img[alt*="profile" i]');

                // If login buttons are present and no dedicated user menu button, user is in Guest mode
                const isActuallyLoggedIn = !hasLoginButton && (!!userMenuButton || !!avatarImg);
                
                let userName = null;
                let userEmail = null;
                let plan = isActuallyLoggedIn ? "OpenAI Account" : "Free Web Tier (Guest)";

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
                        plan: "Free Web Tier (Guest)"
                    };
                }

                return {
                    is_logged_in: true,
                    type: "Logged In",
                    label: `Logged In (${userName || 'Account'})`,
                    name: userName || "Authenticated User",
                    email: userEmail || "Stored in Profile",
                    plan: plan
                };
            }''')
            self._account_info = info
            return info
        except Exception as e:
            return self._account_info

    async def initialize(self):
        """Initializes the browser and navigates to ChatGPT."""
        async with self._lock:
            if self._initialized and self.page and not self.page.is_closed():
                return
            await self._start_browser()

    async def _start_browser(self):
        self.log("Launching browser engine...")
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

        # Check if Chrome executable exists
        executable = config.CHROME_PATH if os.path.exists(config.CHROME_PATH) else None
        if executable:
            self.log(f"Using Google Chrome from: {executable}")
        else:
            self.log("Custom Chrome not found. Falling back to bundled Chromium.")

        try:
            if config.CDP_URL:
                self.log(f"Connecting to existing browser via CDP: {config.CDP_URL}")
                browser = await self.playwright.chromium.connect_over_cdp(config.CDP_URL)
                self.context = browser.contexts[0] if browser.contexts else await browser.new_context()
                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            else:
                self.log(f"Using persistent user profile at: {profile_dir} (Headless: {config.HEADLESS})")
                self.context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    executable_path=executable,
                    headless=config.HEADLESS,
                    viewport={"width": 1440, "height": 900},
                    args=launch_args
                )
                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

            self.log("Navigating to ChatGPT...")
            await self.page.goto(config.CHATGPT_URL, wait_until="networkidle", timeout=60000)
            await self._dismiss_dialogs()
            self._initialized = True
            await self.update_account_info()
            self.log(f"ChatGPT Web ready! Account: {self._account_info.get('label')}")
        except Exception as e:
            self.log(f"Error during browser initialization: {str(e)}", "ERROR")
            self._initialized = False
            raise

    async def _dismiss_dialogs(self):
        """Dismiss common modals like 'Stay logged out' or cookie notices."""
        if not self.page:
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
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    self.log(f"Dismissed prompt dialog: {sel}")
                    await asyncio.sleep(0.5)
            except Exception:
                pass

    async def _get_composer(self):
        """Locates the composer input element."""
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
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                pass
        # Wait up to 8 seconds for any composer
        try:
            return await self.page.wait_for_selector(
                ", ".join(selectors),
                timeout=8000,
                state="visible"
            )
        except Exception:
            return None

    def format_messages(self, messages: List[Any]) -> str:
        """Formats an array of OpenAI messages into a single prompt for ChatGPT."""
        if not messages:
            return ""
        if len(messages) == 1:
            content = messages[0].content
            return content if isinstance(content, str) else str(content)

        formatted_parts = []
        for msg in messages:
            role = msg.role.capitalize()
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if msg.role.lower() == "system":
                formatted_parts.append(f"[System Instruction]: {content}\n")
            elif msg.role.lower() == "user":
                formatted_parts.append(f"[User]: {content}")
            elif msg.role.lower() == "assistant":
                formatted_parts.append(f"[Assistant]: {content}")
            else:
                formatted_parts.append(f"[{role}]: {content}")

        # Instruction for model to continue the conversation
        formatted_parts.append("\n[Assistant]:")
        return "\n\n".join(formatted_parts)

    async def _extract_current_response(self) -> str:
        """Extracts the assistant response text from ChatGPT Web DOM."""
        if not self.page:
            return ""
        try:
            text = await self.page.evaluate('''() => {
                // Find element containing "ChatGPT said:"
                const allElements = Array.from(document.querySelectorAll('*'));
                const saidNodes = allElements.filter(el => {
                    const text = el.innerText || '';
                    return text.includes('ChatGPT said:') && el.children.length === 0;
                });
                
                let response = "";
                if (saidNodes.length > 0) {
                    const lastSaid = saidNodes[saidNodes.length - 1];
                    const container = lastSaid.closest('article') || 
                                      lastSaid.parentElement?.parentElement || 
                                      lastSaid.parentElement;
                    if (container) {
                        const raw = container.innerText || '';
                        const idx = raw.lastIndexOf('ChatGPT said:');
                        if (idx !== -1) {
                            response = raw.substring(idx + 'ChatGPT said:'.length);
                        }
                    }
                }
                
                // Fallback: look for articles or prose/markdown containers
                if (!response.trim()) {
                    const articles = Array.from(document.querySelectorAll('article, [data-message-author-role="assistant"], div.markdown'));
                    if (articles.length > 0) {
                        response = articles[articles.length - 1].innerText || '';
                    }
                }
                
                // Clean footers
                const footers = [
                    'ChatGPT is AI and can make mistakes.',
                    'Thinking',
                    'Log in to get answers based on saved chats',
                    'Try advanced features for free'
                ];
                for (const f of footers) {
                    if (response.includes(f)) {
                        response = response.split(f)[0];
                    }
                }
                return response.trim();
            }''')
            return text or ""
        except Exception as e:
            logger.debug(f"Extraction error: {e}")
            return ""

    async def _is_streaming_active(self) -> bool:
        """Checks if ChatGPT is currently generating/streaming a response."""
        if not self.page:
            return False
        try:
            return await self.page.evaluate('''() => {
                const stopBtn = document.querySelector('button[aria-label*="Stop"], button[data-testid*="stop"]');
                return !!stopBtn;
            }''')
        except Exception:
            return False

    async def new_chat(self):
        """Navigates to a new chat conversation."""
        if not self.page:
            return
        self.log("Opening new chat conversation...")
        try:
            new_btn = await self.page.query_selector("a[href='/'], button[aria-label*='New chat'], button:has-text('New chat')")
            if new_btn and await new_btn.is_visible():
                await new_btn.click()
            else:
                await self.page.goto(config.CHATGPT_URL, wait_until="domcontentloaded")
            await asyncio.sleep(1)
            await self._dismiss_dialogs()
        except Exception as e:
            self.log(f"Error resetting new chat: {e}", "WARNING")

    async def send_chat_completion(
        self,
        prompt: str,
        new_chat: bool = True
    ) -> str:
        """Non-streaming chat completion."""
        full_text = ""
        async for chunk in self.stream_chat_completion(prompt, new_chat=new_chat):
            full_text += chunk
        return full_text

    async def stream_chat_completion(
        self,
        prompt: str,
        new_chat: bool = True
    ) -> AsyncGenerator[str, None]:
        """Streaming chat completion generator that yields text delta chunks."""
        async with self._lock:
            self._is_busy = True
            try:
                if not self._initialized or not self.page or self.page.is_closed():
                    await self._start_browser()

                if new_chat:
                    await self.new_chat()

                composer = await self._get_composer()
                if not composer:
                    self.log("Composer not found. Refreshing page...", "WARNING")
                    await self.page.goto(config.CHATGPT_URL, wait_until="networkidle")
                    await self._dismiss_dialogs()
                    composer = await self._get_composer()
                    if not composer:
                        raise RuntimeError("Unable to locate ChatGPT prompt composer on page.")

                self.log(f"Sending prompt to ChatGPT ({len(prompt)} chars)...")
                await composer.click()
                await composer.fill(prompt)
                await asyncio.sleep(0.3)

                # Send button
                send_btn = await self.page.query_selector(
                    "button[aria-label*='Send message'], button[aria-label*='Send'], button[data-testid='send-button']"
                )
                if send_btn and await send_btn.is_visible():
                    await send_btn.click()
                else:
                    await self.page.keyboard.press("Enter")

                self.log("Prompt submitted. Streaming response...")
                
                previous_text = ""
                start_time = time.time()
                timeout = config.REQUEST_TIMEOUT
                streaming_began = False
                idle_cycles = 0

                while time.time() - start_time < timeout:
                    await asyncio.sleep(config.STREAM_POLL_INTERVAL)
                    is_streaming = await self._is_streaming_active()
                    current_text = await self._extract_current_response()

                    if is_streaming or len(current_text) > 0:
                        streaming_began = True

                    # Calculate new chunk delta
                    if len(current_text) > len(previous_text):
                        delta = current_text[len(previous_text):]
                        previous_text = current_text
                        idle_cycles = 0
                        yield delta
                    else:
                        idle_cycles += 1

                    # Check if finished
                    if streaming_began and not is_streaming and idle_cycles >= 3:
                        # Extra check to ensure any last characters are captured
                        await asyncio.sleep(0.4)
                        final_text = await self._extract_current_response()
                        if len(final_text) > len(previous_text):
                            yield final_text[len(previous_text):]
                        self.log(f"Stream complete! Total response length: {len(final_text or previous_text)} chars.")
                        break

                    # Guard against infinite stall
                    if not streaming_began and idle_cycles > 40: # 8 seconds with zero activity
                        self.log("Warning: No streaming activity detected after prompt.", "WARNING")
                        break

            except Exception as e:
                self.log(f"Exception during chat execution: {str(e)}", "ERROR")
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
                self.page = None
                self.playwright = None
                self._initialized = False

# Global singleton bridge instance
bridge = ChatGPTBrowserBridge()
