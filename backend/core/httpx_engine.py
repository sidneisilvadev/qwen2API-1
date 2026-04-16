"""
httpx_engine.py — Direct connection to Qwen API via curl_cffi (Chrome TLS Fingerprint)
Advantages: TLS fingerprint matches real Chrome, no encoding issues, supports early stream abortion.
"""

import asyncio
import json
import logging

log = logging.getLogger("qwen2api.httpx_engine")

BASE_URL = "https://chat.qwen.ai"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://chat.qwen.ai/",
    "Origin": "https://chat.qwen.ai",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"10.0.0"',
    "sec-ch-ua-model": '""',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}

_IMPERSONATE = "chrome124"


class HttpxEngine:
    """Direct curl_cffi engine — Chrome TLS fingerprint, same interface as BrowserEngine."""

    def __init__(self, pool_size: int = 3, base_url: str = BASE_URL):
        self.base_url = base_url
        self._started = False
        self._ready = asyncio.Event()
        self._session = None # Enterprise point: Persistent Session

    async def start(self):
        # We'll use curl_cffi AsyncSession with a dedicated connection pool
        from curl_cffi.requests import AsyncSession
        self._session = AsyncSession(impersonate=_IMPERSONATE, timeout=1800, max_clients=10)
        self._started = True
        self._ready.set()
        log.info("[HttpxEngine] Started (Persistent Hot Sockets Active)")

    async def stop(self):
        self._started = False
        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass
        log.info("[HttpxEngine] Stopped")

    def _auth_headers(self, token: str) -> dict:
        return {**_HEADERS, "Authorization": f"Bearer {token}"}

    async def api_call(self, method: str, path: str, token: str, body: dict = None, cookies: str = None) -> dict:
        # Safety: Wait for hot session initialization
        await asyncio.wait_for(self._ready.wait(), timeout=60)
        if not self._session:
            return {"status": 0, "body": "Httpx engine is not ready."}
        
        from curl_cffi.requests import AsyncSession
        url = self.base_url + path
        headers = {**self._auth_headers(token), "Content-Type": "application/json"}
        if cookies:
            headers["Cookie"] = cookies
        data = json.dumps(body, ensure_ascii=False).encode() if body else None
        try:
            # Reusing the persistent session
            resp = await self._session.request(method, url, headers=headers, data=data)
            return {"status": resp.status_code, "body": resp.text}
        except Exception as e:
            log.error(f"[HttpxEngine] api_call error: {e}")
            return {"status": 0, "body": str(e)}

    async def fetch_chat(self, token: str, chat_id: str, payload: dict, buffered: bool = False, cookies: str = None):
        """Stream Qwen SSE via curl_cffi with Chrome TLS fingerprint."""
        # Safety: Wait for hot session initialization
        await asyncio.wait_for(self._ready.wait(), timeout=60)
        if not self._session:
            yield {"status": 0, "body": "Httpx engine session not initialized"}
            return
            
        from curl_cffi.requests import AsyncSession
        url = self.base_url + f"/api/v2/chat/completions?chat_id={chat_id}"
        headers = {
            **self._auth_headers(token),
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if cookies:
            headers["Cookie"] = cookies
        body_bytes = json.dumps(payload, ensure_ascii=False).encode()

        try:
            # Reusing the persistent session for streaming (Multiplexing)
            async with self._session.stream("POST", url, headers=headers, data=body_bytes) as resp:
                if resp.status_code != 200:
                    body_chunks = []
                    async for chunk in resp.aiter_content(chunk_size=4096):
                        body_chunks.append(chunk)
                    body_text = b"".join(body_chunks).decode(errors="replace")[:2000]
                    yield {"status": resp.status_code, "body": body_text}
                    return

                # Zero-Latency Chunking: Yield immediately (chunk_size=1)
                async for chunk in resp.aiter_content(chunk_size=1):
                    if chunk:
                        decoded = chunk.decode("utf-8", errors="replace")
                        yield {"status": "streamed", "chunk": decoded}

        except Exception as e:
            log.error(f"[HttpxEngine] fetch_chat error: {e}")
            yield {"status": 0, "body": str(e)}
