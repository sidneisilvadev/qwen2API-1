import asyncio
import logging
import os
import random
import time
import gc
from contextlib import asynccontextmanager
from backend.core.config import settings

log = logging.getLogger("qwen2api.browser")


def _request_jitter_seconds() -> float:
    # Enterprise Mode: Minimal jitter to keep it snappy. For max speed, we use a very low ceiling.
    low = max(0, settings.REQUEST_JITTER_MIN_MS)
    # We cap the high jitter at 50ms for enterprise mode to keep it fast
    high = min(50, settings.REQUEST_JITTER_MAX_MS) if settings.REQUEST_JITTER_MAX_MS > 0 else 0
    return random.uniform(low, high) / 1000.0

JS_FETCH = (
    "async (args) => {"
    "const opts={method:args.method,headers:{'Content-Type':'application/json','Authorization':'Bearer '+args.token}};"
    "if(args.body && args.method!=='GET' && args.method!=='HEAD')opts.body=JSON.stringify(args.body);"
    "const res=await fetch(args.url,opts);"
    "const text=await res.text();"
    "return{status:res.status,body:text};"
    "}"
)

# Full streaming function, single-line string to avoid Camoufox page.evaluate multi-line JS errors.
# Does not depend on window.__qwen_stream_fetch, self-contained.
JS_STREAM_CHUNKED = (
    "async (args) => {"
    "const ctrl=new AbortController();"
    "const tmr=setTimeout(()=>ctrl.abort(),180000);"
    "console.log('[JS] Starting Turbo V2 fetch to '+args.url);"
    "try{"
    "const res=await fetch(args.url,{method:'POST',"
    "headers:{'Content-Type':'application/json','Authorization':'Bearer '+args.token},"
    "body:JSON.stringify(args.payload),signal:ctrl.signal});"
    "console.log('[JS] Fetch response status: '+res.status);"
    "if(!res.ok){"
    "const t=await res.text();clearTimeout(tmr);"
    "console.error('[JS] Fetch failed: (' + res.status + ') ' + t.substring(0,500));"
    "return{status:res.status,body:t.substring(0,2000)};}"
    "const rdr=res.body.getReader();"
    "const dec=new TextDecoder();"
    "let buf='';"
    "let chunks=0;"
    "while(true){"
    "const{done,value}=await rdr.read();"
    "if(done){"
    "if(window.send_chunk && buf)await window.send_chunk(args.chat_id,buf);"
    "break;"
    "}"
    "chunks++;"
    "const decoded=dec.decode(value,{stream:true});"
    "if(window.send_chunk){await window.send_chunk(args.chat_id,decoded);}else{buf+=decoded;}"
    "}"
    "clearTimeout(tmr);"
    "return{status:200,body:'__DONE__'};"
    "}catch(e){"
    "clearTimeout(tmr);"
    "console.error('[JS] Runtime exception: '+e.message + '\\nStack: ' + e.stack);"
    "return{status:0,body:'JS error: '+e.message};"
    "}}"
)

JS_STREAM_FULL = (
    "async (args) => {"
    "const ctrl=new AbortController();"
    "const tmr=setTimeout(()=>ctrl.abort(),1800000);"
    "try{"
    "const res=await fetch(args.url,{method:'POST',"
    "headers:{'Content-Type':'application/json','Authorization':'Bearer '+args.token},"
    "body:JSON.stringify(args.payload),signal:ctrl.signal});"
    "if(!res.ok){"
    "const t=await res.text();clearTimeout(tmr);"
    "return{status:res.status,body:t.substring(0,2000)};}"
    "const rdr=res.body.getReader();"
    "const dec=new TextDecoder();"
    "let body='';"
    "while(true){"
    "const{done,value}=await rdr.read();"
    "if(done)break;"
    "body+=dec.decode(value,{stream:true});}"
    "clearTimeout(tmr);"
    "return{status:res.status,body:body};"
    "}catch(e){"
    "clearTimeout(tmr);"
    "return{status:0,body:'JS error: '+e.message};"
    "}}"
)

# Organization: Chromium profiles inside the project
PROFILES_DIR = os.path.join(os.getcwd(), "data", "browser_profiles")
os.makedirs(PROFILES_DIR, exist_ok=True)

class BrowserEngine:
    def __init__(self, pool_size: int = 3, base_url: str = "https://chat.qwen.ai"):
        self.pool_size = pool_size
        self.base_url = base_url
        self._browser = None
        self._playwright = None
        self._context = None
        self._pages: asyncio.Queue = asyncio.Queue()
        self._streaming_queues: dict[str, asyncio.Queue] = {}
        self._started = False
        self._ready = asyncio.Event()

    async def start(self):
        if self._started:
            return
        try:
            async with asyncio.timeout(90):
                await self._start_chromium()
        except asyncio.TimeoutError:
            log.error("[Browser] Chromium startup TIMEOUT. System continues without BG browser.")
        except Exception as e:
            log.error(f"[Browser] Chromium failed: {e}")
        finally:
            self._ready.set()

    async def _start_chromium(self):
        from playwright.async_api import async_playwright
        log.info("Starting Lite browser engine (Chromium)...")
        self._playwright = await async_playwright().start()
        
        args = [
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-software-rasterizer",
            "--disable-extensions",
        ]
        
        self._browser = await self._playwright.chromium.launch(headless=True, args=args)
        
        # Shared context with stealth
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        )
        
        # Simplified stealth script
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        # Turbo-Load: Resource Blocking (Enterprise point 1)
        async def block_resources(route):
            try:
                # We stop blocking stylesheets as they might be required for the app's JS logic
                if route.request.resource_type in ["image", "media", "font"]:
                    await route.abort()
                else:
                    await route.continue_()
            except Exception:
                # Connection might be closed while reading from driver, or page closed.
                pass
        
        # Apply blocking to all future pages in this context
        await self._context.route("**/*", block_resources)
        
        await self._init_pages()
        self._started = True
        log.info("Lite Browser engine started (Chromium)")
        
        # Enterprise point 3, 9, 14: Background Warmer & Pre-fetcher
        asyncio.create_task(self._background_warmer_worker())

    async def _background_warmer_worker(self):
        """Maintains sockets warm, JIT primed and self-heals crashed pages."""
        while self._started:
            try:
                # 1. Health Watchdog (Definitive Stability)
                is_browser_alive = False
                try:
                    if self._browser and self._browser.is_connected():
                        is_browser_alive = True
                except Exception:
                    is_browser_alive = False

                if not is_browser_alive and self._started:
                    log.warning("[Guardian] Browser process detected DEAD. Restarting engine...")
                    await self._restart_engine()
                    await asyncio.sleep(5)
                    continue

                # 2. Page Health & Rotation
                # We'll check the health of one page per cycle to avoid overhead
                try:
                    page = await asyncio.wait_for(self._pages.get(), timeout=1)
                    try:
                        # Test page with a simple JS call
                        await page.evaluate("1+1")
                        # Perform warming if healthy
                        await self._warmup_page(page)
                        # Optional: Periodic refresh to prevent memory leaks (every 30 cycles)
                        if random.random() < 0.05:
                            await self._refresh_page(page)
                        self._pages.put_nowait(page)
                    except Exception as e:
                        log.error(f"[Guardian] Page health check failed: {e}. Recreating tab...")
                        try: await page.close()
                        except: pass
                        
                        try:
                            new_page = await self._context.new_page()
                            await self._setup_single_page(new_page, 99) # 99 = dynamic id
                            self._pages.put_nowait(new_page)
                        except Exception as e2:
                            log.error(f"[Guardian] Recreating tab failed: {e2}")
                            # If we can't even recreate, we lose a slot for now.
                            # System will attempt to restart engine if many fail.
                except asyncio.TimeoutError:
                    pass

            except Exception as e:
                log.error(f"[Guardian] Watchdog encountered error: {e}")
            
            await asyncio.sleep(30) # Check every 30 seconds

    async def _restart_engine(self):
        """Force a clean restart of the browser process."""
        try:
            await self.stop()
            self._started = False
            self._ready.clear()
            await self.start()
        except Exception as e:
            log.error(f"[Guardian] Engine restart failed: {e}")

    async def _setup_single_page(self, page, index: int):
        # Capture browser console logs
        page.on("console", lambda msg: log.debug(f"  [Browser Console] {msg.text}"))
        page.on("pageerror", lambda exc: log.debug(f"  [Browser PageError] {exc}"))
        try:
            async def bridge(chat_id: str, chunk: str):
                if chat_id in self._streaming_queues:
                    await self._streaming_queues[chat_id].put(chunk)
            await page.expose_function("send_chunk", bridge)
            # Increase timeout and use networkidle if possible, or at least wait a bit more
            await page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)
            # Extra wait to allow Qwen's heavy JS to initialize and avoid "messages not ready" error
            await asyncio.sleep(5)
            log.info(f"  [Browser] Page {index+1} initialized")
        except Exception as e:
            log.warning(f"  [Browser] Page {index+1} setup warning: {e}")

    async def _warmup_page(self, page):
        """Minimal JS call to keep socket and JIT primed."""
        try:
            # Minimal network activity to keep the persistent connection alive
            await page.evaluate("fetch('/api/v2/models/', {method: 'GET', priority: 'low'}).catch(() => {})")
        except Exception:
            pass

    async def _init_pages(self):
        log.info(f"[Browser] Initializing {self.pool_size} concurrent Chromium rendering engines...")
        for i in range(self.pool_size):
            try:
                page = await self._context.new_page()
                await self._setup_single_page(page, i)
                await asyncio.sleep(0.5)
                self._pages.put_nowait(page)
            except Exception as e:
                log.error(f"[Browser] Failed to initialize rendering engine {i+1}: {e}")

    async def inject_cookies(self, page, cookies_str: str):
        """Chromium: Sync backend cookies to browser context."""
        if not cookies_str:
            return
        try:
            domain = "chat.qwen.ai"
            playwright_cookies = []
            for item in cookies_str.split(";"):
                if "=" in item:
                    parts = item.strip().split("=", 1)
                    if len(parts) == 2:
                        name, value = parts
                        playwright_cookies.append({
                            "name": name,
                            "value": value,
                            "domain": domain,
                            "path": "/",
                        })
            if playwright_cookies:
                await page.context.add_cookies(playwright_cookies)
        except Exception as e:
            log.warning(f"  [Browser] Cookie injection failed: {e}")

    async def stop(self):
        log.info("[Browser] Stopping browser engine gracefully...")
        self._started = False
        if self._context:
            try: await self._context.close()
            except Exception: pass
        if self._browser:
            try: await self._browser.close()
            except Exception: pass
        if self._playwright:
            try: await self._playwright.stop()
            except Exception: pass
        self._browser = None
        self._context = None
        self._playwright = None

    async def api_call(self, method: str, path: str, token: str, body: dict = None, cookies: str = None) -> dict:
        await asyncio.wait_for(self._ready.wait(), timeout=300)
        if not self._started:
            # Emergency attempt to start if not running
            asyncio.create_task(self.start())
            return {"status": 0, "body": "Browser engine is starting..."}
        
        try:
            page = await asyncio.wait_for(self._pages.get(), timeout=60)
        except asyncio.TimeoutError:
            return {"status": 429, "body": "Too Many Requests (Queue full)"}

        needs_refresh = False
        try:
            if cookies:
                await self.inject_cookies(page, cookies)
            
            await asyncio.sleep(_request_jitter_seconds())
            result = await page.evaluate(JS_FETCH, {
                "method": method, "url": path, "token": token, "body": body or {},
            })
            if result.get("status") == 0 and result.get("body", "").startswith("JS error:"):
                needs_refresh = True
            return result
        except Exception as e:
            log.error(f"api_call error: {e}")
            needs_refresh = True
            return {"status": 0, "body": str(e)}
        finally:
            if needs_refresh:
                asyncio.create_task(self._refresh_page_and_return(page))
            else:
                self._pages.put_nowait(page)

    async def fetch_chat(self, token: str, chat_id: str, payload: dict, buffered: bool = False, cookies: str = None):
        """Turbo V3: Definitively stable streaming loop."""
        await asyncio.wait_for(self._ready.wait(), timeout=300)
        if not self._started:
            yield {"status": 0, "body": "Browser engine is starting..."}
            return

        try:
            page = await asyncio.wait_for(self._pages.get(), timeout=60)
        except asyncio.TimeoutError:
            yield {"status": 429, "body": "Too Many Requests (Queue full)"}
            return

        chunk_queue: asyncio.Queue = asyncio.Queue()
        self._streaming_queues[chat_id] = chunk_queue
        
        needs_refresh = False
        url = f'/api/v2/chat/completions?chat_id={chat_id}'
        content_received = 0
        
        try:
            if cookies:
                await self.inject_cookies(page, cookies)

            # Warm up non-blocking
            asyncio.create_task(self._warmup_page(page))
            
            js_task = asyncio.create_task(page.evaluate(JS_STREAM_CHUNKED, {
                "url": url, "token": token, "chat_id": chat_id, "payload": payload
            }))
            
            last_chunk_at = time.time()
            while True:
                wait_chunk = asyncio.create_task(chunk_queue.get())
                done, pending = await asyncio.wait(
                    [wait_chunk, js_task], 
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=5 # Short check intervals for responsiveness
                )
                
                now = time.time()
                if not done: # Timeout of 5s
                    if now - last_chunk_at > settings.CHAT_TIMEOUT:
                        log.warning(f"[Browser] Streaming idle timeout: chat_id={chat_id}")
                        needs_refresh = True
                        wait_chunk.cancel()
                        break
                    continue

                if wait_chunk in done:
                    chunk = wait_chunk.result()
                    content_received += len(chunk)
                    last_chunk_at = now
                    yield {"status": "streamed", "chunk": chunk}
                else:
                    wait_chunk.cancel()
                
                if js_task in done:
                    res = js_task.result()
                    if isinstance(res, dict) and res.get("status") != 200:
                        yield res
                        needs_refresh = True
                    break

            if content_received == 0 and not needs_refresh:
                log.warning(f"[Browser] Empty response for chat_id={chat_id}")
                needs_refresh = True

        except Exception as e:
            log.error(f"[Browser] Streaming error: {e}")
            needs_refresh = True
            yield {"status": 0, "body": str(e)}
        finally:
            self._streaming_queues.pop(chat_id, None)
            if needs_refresh:
                asyncio.create_task(self._refresh_page_and_return(page))
            else:
                self._pages.put_nowait(page)

    async def _refresh_page(self, page):
        try:
            await asyncio.wait_for(
                page.goto(self.base_url, wait_until="domcontentloaded"),
                timeout=20000,
            )
        except Exception:
            pass

    async def _refresh_page_and_return(self, page):
        await self._refresh_page(page)
        self._pages.put_nowait(page)

    async def get_page_diagnostic(self) -> dict:
        try:
            page = await asyncio.wait_for(self._pages.get(), timeout=2)
            try:
                content = await page.content()
                content_lower = content.lower()
                state = "ok"
                if "captcha" in content_lower or "verify you are human" in content_lower:
                    state = "captcha"
                elif "login" in content_lower and "chat.qwen.ai" in page.url:
                    state = "login_required"
                
                return {
                    "state": state,
                    "url": page.url,
                    "title": await page.title(),
                }
            finally:
                self._pages.put_nowait(page)
        except Exception:
            return {"state": "unknown", "url": "", "title": ""}
