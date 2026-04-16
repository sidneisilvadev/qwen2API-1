"""
hybrid_engine.py — mix browser stability with httpx speed.
Phase 1 policy:
- api_call: httpx first, browser fallback on failures
- fetch_chat: httpx first (Phantom mode), browser fallback on failures
"""

import logging

log = logging.getLogger("qwen2api.hybrid_engine")


class HybridEngine:
    def __init__(self, browser_engine, httpx_engine):
        self.browser_engine = browser_engine
        self.httpx_engine = httpx_engine
        self._started = False
        self.base_url = getattr(browser_engine, "base_url", getattr(httpx_engine, "base_url", "https://chat.qwen.ai"))
        self.pool_size = getattr(browser_engine, "pool_size", 0)
        self._pages = getattr(browser_engine, "_pages", None)

    async def start(self):
        log.info("[HybridEngine] Starting: Initializing httpx engine first")
        await self.httpx_engine.start()
        log.info("[HybridEngine] Step 1 complete: httpx started, now starting browser engine")
        await self.browser_engine.start()
        self._started = bool(getattr(self.httpx_engine, "_started", False) and getattr(self.browser_engine, "_started", False))
        log.info(f"[HybridEngine] Started: api_call=httpx_first, fetch_chat=httpx_first, started={self._started} browser_started={getattr(self.browser_engine, '_started', False)} httpx_started={getattr(self.httpx_engine, '_started', False)}")

    async def stop(self):
        try:
            await self.httpx_engine.stop()
        finally:
            await self.browser_engine.stop()
        self._started = False
        log.info("[HybridEngine] Stopped")

    async def api_call(self, method: str, path: str, token: str, body: dict = None, cookies: str = None) -> dict:
        log.info(f"[HybridEngine] Routing api_call: prioritizing httpx, method={method} path={path}")
        result = await self.httpx_engine.api_call(method, path, token, body, cookies=cookies)
        status = result.get("status")
        body_text = (result.get("body") or "").lower()
        should_fallback = (
            status == 0
            or status in (401, 403, 429)
            or "waf" in body_text
            or "<!doctype" in body_text
            or "forbidden" in body_text
            or "unauthorized" in body_text
        )
        if should_fallback:
            preview = (result.get("body") or "")[:160].replace("\n", "\\n")
            log.warning(f"[HybridEngine] api_call fallback to browser, method={method} path={path} status={status} body_preview={preview!r}")
            return await self.browser_engine.api_call(method, path, token, body, cookies=cookies)
        log.info(f"[HybridEngine] api_call handled by httpx, method={method} path={path} status={status}")
        return result

    async def fetch_chat(self, token: str, chat_id: str, payload: dict, buffered: bool = False, cookies: str = None):
        log.info(f"[HybridEngine] Routing fetch_chat: prioritizing httpx (Phantom Engine), chat_id={chat_id}")
        saw_success = False
        httpx_error = None
        try:
            async for item in self.httpx_engine.fetch_chat(token, chat_id, payload, buffered=buffered, cookies=cookies):
                status = item.get("status")
                if status in ("streamed", 200):
                    saw_success = True
                    yield item
                    continue
                # Potential WAF/403/Forbidden from HTTPX
                body_text = (item.get("body") or "").lower()
                is_blocked = (
                    status in (401, 403, 429)
                    or "waf" in body_text
                    or "forbidden" in body_text
                )
                if is_blocked and not saw_success:
                    httpx_error = item
                    break
                yield item
            if httpx_error is None:
                return
        except Exception as e:
            if saw_success:
                return
            httpx_error = {"status": 0, "body": str(e)}

        preview = ((httpx_error.get("body") or "")[:160]).replace("\n", "\\n") if isinstance(httpx_error, dict) else str(httpx_error)[:160]
        log.warning(
            f"[HybridEngine] fetch_chat httpx failed, falling back to browser (Visual Warmup): chat_id={chat_id} "
            f"status={httpx_error.get('status') if isinstance(httpx_error, dict) else 'unknown'} "
            f"body_preview={preview!r}"
        )
        async for item in self.browser_engine.fetch_chat(token, chat_id, payload, buffered=buffered, cookies=cookies):
            yield item

    def status(self) -> dict:
        free_pages = 0
        queue = 0
        if self._pages is not None:
            try:
                free_pages = self._pages.qsize()
                queue = max(0, self.pool_size - free_pages)
            except Exception:
                free_pages = 0
                queue = 0
        return {
            "started": self._started,
            "mode": "hybrid",
            "status_v3": "phantom_priority",
            "stream_via": "httpx_first",
            "api_via": "httpx_first",
            "browser_started": getattr(self.browser_engine, "_started", False),
            "httpx_started": getattr(self.httpx_engine, "_started", False),
            "pool_size": self.pool_size,
            "free_pages": free_pages,
            "queue": queue,
        }
