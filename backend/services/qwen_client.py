import asyncio
import json
import logging
import time
import uuid
from typing import Optional, Any
from backend.core.account_pool import AccountPool, Account
from backend.core.config import settings, resolve_model
from backend.services.auth_resolver import AuthResolver

log = logging.getLogger("qwen2api.client")

AUTH_FAIL_KEYWORDS = ("token", "unauthorized", "expired", "forbidden", "401", "403", "invalid", "login", "activation", "pending activation", "not activated")
PENDING_ACTIVATION_KEYWORDS = ("pending activation", "please check your email", "not activated")
BANNED_KEYWORDS = ("banned", "suspended", "blocked", "disabled", "risk control", "violat", "forbidden by policy")

def _is_auth_error(error_msg: str) -> bool:
    msg = error_msg.lower()
    return any(keyword in msg for keyword in AUTH_FAIL_KEYWORDS)

def _is_pending_activation_error(error_msg: str) -> bool:
    msg = error_msg.lower()
    return any(keyword in msg for keyword in PENDING_ACTIVATION_KEYWORDS)

def _is_banned_error(error_msg: str) -> bool:
    msg = error_msg.lower()
    return any(keyword in msg for keyword in BANNED_KEYWORDS)

class QwenClient:
    def __init__(self, engine: Any, account_pool: AccountPool):
        self.engine = engine
        self.account_pool = account_pool
        self.auth_resolver = AuthResolver(account_pool)
        self.active_chat_ids: set[str] = set()  # Active chat_ids, GC must NOT delete them
        
        # Turbo V4: Chat Pooling Infrastructure
        self.chat_pool: dict[str, asyncio.Queue] = {} # email -> Queue[chat_id]
        self._pool_lock = asyncio.Lock()
        self._worker_task: Optional[asyncio.Task] = None

    async def start(self):
        """Starts background workers."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._chat_pooling_worker())
            log.info("[QwenClient] Turbo V4 Chat Pooling Worker started")

    async def stop(self):
        """Stops background workers."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            log.info("[QwenClient] Turbo V4 Chat Pooling Worker stopped")

    async def create_chat(self, token: str, model: str, chat_type: str = "t2t", cookies: str = None) -> str:
        ts = int(time.time())
        body = {"title": f"api_{ts}", "models": [model], "chat_mode": "normal",
                "chat_type": chat_type, "timestamp": ts}

        # Chat lifecycle calls also prioritize browser to mimic real user paths
        if hasattr(self.engine, "browser_engine") and getattr(self.engine, "browser_engine") is not None:
            r = await self.engine.browser_engine.api_call("POST", "/api/v2/chats/new", token, body, cookies=cookies)
            status = r.get("status")
            body_text = (r.get("body") or "").lower()
            should_fallback = (
                status == 0
                or status in (401, 403, 429)
                or "waf" in body_text
                or "<!doctype" in body_text
                or "forbidden" in body_text
                or "unauthorized" in body_text
            )
            if should_fallback:
                preview = (r.get("body") or "")[:160].replace("\n", "\\n")
                log.warning(f"[QwenClient] create_chat browser failed, falling back to default engine status={status} body_preview={preview!r}")
                r = await self.engine.api_call("POST", "/api/v2/chats/new", token, body, cookies=cookies)
        else:
            r = await self.engine.api_call("POST", "/api/v2/chats/new", token, body, cookies=cookies)
        if r["status"] == 429:
            raise Exception("429 Too Many Requests (Engine Queue Full)")

        body_text = r.get("body", "")
        if r["status"] != 200:
            body_lower = body_text.lower()
            if (r["status"] in (401, 403)
                    or "unauthorized" in body_lower or "forbidden" in body_lower
                    or "token" in body_lower or "login" in body_lower
                    or "401" in body_text or "403" in body_text):
                raise Exception(f"unauthorized: create_chat HTTP {r['status']}: {body_text[:100]}")
            raise Exception(f"create_chat HTTP {r['status']}: {body_text[:100]}")

        try:
            data = json.loads(body_text)
            if not data.get("success") or "id" not in data.get("data", {}):
                raise Exception("Qwen API returned error or missing id")
            return data["data"]["id"]
        except Exception as e:
            body_lower = body_text.lower()
            if any(kw in body_lower for kw in ("html", "login", "unauthorized", "activation",
                                                "pending", "forbidden", "token", "expired", "invalid")):
                raise Exception(f"unauthorized: account issue: {body_text[:200]}")
            raise Exception(f"create_chat parse error: {e}, body={body_text[:200]}")

    async def _chat_pooling_worker(self):
        """Background worker that ensures each valid account has at least 1 pre-created chat."""
        # Warm-up delay: wait for engines to be ready
        await asyncio.sleep(10)
        while True:
            try:
                valid_accounts = [a for a in self.account_pool.accounts if a.valid and not a.activation_pending]
                for acc in valid_accounts:
                    async with self._pool_lock:
                        if acc.email not in self.chat_pool:
                            self.chat_pool[acc.email] = asyncio.Queue(maxsize=3)
                        
                        queue = self.chat_pool[acc.email]
                    
                    # If pool is not full, create a chat ID
                    if queue.qsize() < 2:
                        try:
                            # Use default model for room creation
                            chat_id = await self.create_chat(acc.token, "qwen-max")
                            await queue.put(chat_id)
                            log.debug(f"[ChatPool] Pre-created ID {chat_id} for {acc.email}")
                        except Exception as e:
                            log.debug(f"[ChatPool] Failed to pre-create for {acc.email}: {e}")
                    
                    await asyncio.sleep(2) # Throttle pool generation
            except Exception as e:
                log.error(f"[ChatPool] Worker error: {e}")
            
            await asyncio.sleep(30)

    async def get_pooled_chat(self, acc: Account, model: str) -> str:
        """Returns a pre-created chat_id from the pool if available, else creates one."""
        async with self._pool_lock:
            if acc.email in self.chat_pool:
                queue = self.chat_pool[acc.email]
                if not queue.empty():
                    chat_id = queue.get_nowait()
                    log.info(f"[Turbo-V4] Pulled pooled chat_id {chat_id} for {acc.email} (Instant Start)")
                    return chat_id
        
        # Fallback to direct creation
        log.info(f"[Turbo-V4] Pool empty for {acc.email}, creating chat_id on-the-fly...")
        return await self.create_chat(acc.token, model, cookies=acc.cookies)

    async def delete_chat(self, token: str, chat_id: str):
        if hasattr(self.engine, "browser_engine") and getattr(self.engine, "browser_engine") is not None:
            r = await self.engine.browser_engine.api_call("DELETE", f"/api/v2/chats/{chat_id}", token)
            status = r.get("status")
            body_text = (r.get("body") or "").lower()
            should_fallback = (
                status == 0
                or status in (401, 403, 429)
                or "waf" in body_text
                or "<!doctype" in body_text
                or "forbidden" in body_text
                or "unauthorized" in body_text
            )
            if should_fallback:
                log.warning(f"[QwenClient] delete_chat browser failed fallback chat_id={chat_id}")
                await self.engine.api_call("DELETE", f"/api/v2/chats/{chat_id}", token)
            return
        await self.engine.api_call("DELETE", f"/api/v2/chats/{chat_id}", token)

    async def list_chats(self, token: str) -> list[str]:
        """Fetch all chat IDs for an account."""
        if hasattr(self.engine, "browser_engine") and getattr(self.engine, "browser_engine") is not None:
            r = await self.engine.browser_engine.api_call("GET", "/api/v2/chats/?page=1&pageSize=100", token)
        else:
            r = await self.engine.api_call("GET", "/api/v2/chats/?page=1&pageSize=100", token)
        
        if r.get("status") != 200:
            return []
            
        try:
            data = json.loads(r.get("body", "{}"))
            chats = data.get("data", {}).get("data", [])
            return [c["id"] for c in chats if "id" in c]
        except Exception:
            return []

    async def clear_account_history(self, token: str):
        """Deletes all chats for a single account."""
        chat_ids = await self.list_chats(token)
        log.info(f"[Cleanup] Found {len(chat_ids)} chats to delete.")
        for cid in chat_ids:
            try:
                await self.delete_chat(token, cid)
                await asyncio.sleep(0.2) # Avoid rate limit
            except Exception as e:
                log.warning(f"[Cleanup] Failed to delete chat {cid}: {e}")

    async def verify_token(self, token: str) -> bool:
        """Verify token validity via direct HTTP (no browser page needed)."""
        if not token:
            return False

        try:
            import httpx
            from backend.services.auth_resolver import BASE_URL

            # Fake browser fingerprint to avoid Aliyun WAF detection
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://chat.qwen.ai/",
                "Origin": "https://chat.qwen.ai",
                "Connection": "keep-alive"
            }

            async with httpx.AsyncClient(timeout=15) as hc:
                resp = await hc.get(
                    f"{BASE_URL}/api/v1/auths/",
                    headers=headers,
                )
            if resp.status_code != 200:
                return False

            try:
                data = resp.json()
                return data.get("role") == "user"
            except Exception as e:
                log.warning(f"[verify_token] JSON parse error: {e}, status={resp.status_code}, text={resp.text[:100]}")
                if "aliyun_waf" in resp.text.lower() or "<!doctype" in resp.text.lower():
                    log.info(f"[verify_token] WAF interception detected, passing to headless browser engine.")
                    return True
                return False
        except Exception as e:
            log.warning(f"[verify_token] HTTP error: {e}")
            return False

    async def sync_models(self) -> list:
        """Fetch real model list from Qwen.ai and update account_pool cache."""
        acc = await self.account_pool.acquire_wait(timeout=30)
        if not acc: return []
        
        token = acc.token
        try:
            import httpx
            from backend.services.auth_resolver import BASE_URL

            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://chat.qwen.ai/",
                "Origin": "https://chat.qwen.ai"
            }

            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as hc:
                resp = await hc.get(f"{BASE_URL}/api/v2/models/", headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    models_data = data.get("data", {}).get("data") or []
                    await self.account_pool.update_discovered_models("qwen", models_data)
                    log.info(f"[Sync] Discovered {len(models_data)} real models from Qwen.ai")
                    return models_data
            return []
        except Exception as e:
            log.warning(f"[Sync] Failed to discover models: {e}")
            return []
        finally:
            self.account_pool.release(acc)

    async def list_models(self, token: str) -> list:
        """Returns the cached discovered models or starts a sync if empty."""
        if not self.account_pool.discovered_models:
            await self.sync_models()
        return self.account_pool.discovered_models

    def _build_payload(self, chat_id: str, model: str, content: str, has_custom_tools: bool = False, thinking: bool = False, search: bool = False) -> dict:
        ts = int(time.time())
        feature_config = {
            "thinking_enabled": thinking,
            "output_schema": "phase",
            "research_mode": "normal",
            "auto_thinking": thinking,
            "thinking_mode": "Auto" if thinking else "off",
            "thinking_format": "summary",
            "auto_search": search,
            "code_interpreter": not has_custom_tools,
            "function_calling": bool(has_custom_tools and settings.NATIVE_TOOL_PASSTHROUGH),
            "plugins_enabled": False if has_custom_tools else True,
        }
        return {
            "stream": True, "version": "2.1", "incremental_output": True,
            "chat_id": chat_id, "chat_mode": "normal", "model": model, "parent_id": None,
            "messages": [{
                "fid": str(uuid.uuid4()), "parentId": None, "childrenIds": [str(uuid.uuid4())],
                "role": "user", "content": content, "user_action": "chat", "files": [],
                "timestamp": ts, "models": [model], "chat_type": "t2t",
                "feature_config": feature_config,
                "extra": {"meta": {"subChatType": "t2t"}}, "sub_chat_type": "t2t", "parent_id": None,
            }],
            "timestamp": ts,
        }

    def _build_image_payload(self, chat_id: str, model: str, prompt: str, n: int = 1) -> dict:
        ts = int(time.time())
        feature_config = {
            "thinking_enabled": False,
            "output_schema": "phase",
            "auto_thinking": False,
            "thinking_mode": "off",
            "auto_search": False,
            "code_interpreter": False,
            "function_calling": False,
            "plugins_enabled": True,
            "image_generation": True,
            "image_count": n,
            "default_aspect_ratio": "16:9",
        }
        return {
            "stream": True,
            "version": "2.1",
            "incremental_output": True,
            "chat_id": chat_id,
            "chat_mode": "normal",
            "model": model,
            "parent_id": None,
            "messages": [{
                "fid": str(uuid.uuid4()),
                "parentId": None,
                "childrenIds": [str(uuid.uuid4())],
                "role": "user",
                "content": prompt,
                "user_action": "chat",
                "files": [],
                "timestamp": ts,
                "models": [model],
                "chat_type": "t2i",
                "feature_config": feature_config,
                "extra": {"meta": {"subChatType": "t2i", "mode": "image_generation", "aspectRatio": "16:9", "imageCount": n}},
                "sub_chat_type": "t2i",
                "parent_id": None,
            }],
            "timestamp": ts,
        }

    def parse_sse_chunk(self, chunk: str) -> list[dict]:
        events = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
                events.append(obj)
            except Exception:
                continue

        parsed = []
        for evt in events:
            if evt.get("choices"):
                delta = evt["choices"][0].get("delta", {})
                parsed.append({
                    "type": "delta",
                    "phase": delta.get("phase", "answer"),
                    "content": delta.get("content", ""),
                    "status": delta.get("status", ""),
                    "extra": delta.get("extra", {})
                })
            elif evt.get("phase"):
                parsed.append({
                    "type": "delta",
                    "phase": evt.get("phase", "answer"),
                    "content": evt.get("content", "") or evt.get("text", "") or "",
                    "status": evt.get("status", ""),
                    "extra": evt.get("extra", {})
                })
        return parsed

    async def chat_stream_events_with_retry(self, model: str, content: str, has_custom_tools: bool = False, exclude_accounts: Optional[set[str]] = None, thinking: Optional[bool] = None, search: Optional[bool] = None, preferred_email: str = None):
        # Use defaults if not specified
        thinking = thinking if thinking is not None else settings.DEFAULT_THINKING
        search = search if search is not None else settings.DEFAULT_SEARCH

        # Dynamic model resolution: Check if the 'model' matches a discovered model's name or id
        resolved_model = resolve_model(model, self.account_pool.discovered_models)
        
        model = resolved_model # Use the best ID we found
        exclude = set(exclude_accounts or set())
        for attempt in range(settings.MAX_RETRIES):
            acc = await self.account_pool.acquire_wait(timeout=60, exclude=exclude, preferred_email=preferred_email)
            if not acc:
                pool_status = self.account_pool.status()
                raise Exception(
                    "No available accounts in pool "
                    f"(total={pool_status['total']}, valid={pool_status['valid']}, "
                    f"invalid={pool_status['invalid']}, activation_pending={pool_status.get('activation_pending', 0)}, "
                    f"rate_limited={pool_status['rate_limited']}, in_use={pool_status['in_use']}, waiting={pool_status['waiting']})"
                )
                
            # Turbo V6: Pull pre-created chat ID from pool FIRST
            chat_id = await self.get_pooled_chat(acc, model)
            
            try:
                log.info(f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Session Strategy: account={acc.email} model={model} pooled={'Yes' if chat_id else 'No'}")
                
                # If we don't have a pooled chat, we MUST respect the cooldown
                if not chat_id:
                    min_interval = max(0, settings.ACCOUNT_MIN_INTERVAL_MS) / 1000.0
                    now = time.time()
                    wait_s = max(0.0, (acc.last_request_started + min_interval) - now)
                    if wait_s > 0:
                        log.info(f"[Throttling] New Session Cooldown: account={acc.email} wait={wait_s:.2f}s")
                        await asyncio.sleep(wait_s)
                else:
                    log.info(f"[Turbo-V6] Bypassed cooldown due to pooled chat for {acc.email}")
                
                if chat_id:
                    self.active_chat_ids.add(chat_id)
                self.active_chat_ids.add(chat_id)
                payload = self._build_payload(chat_id, model, content, has_custom_tools, thinking=thinking, search=search)
                
                log.info(
                    f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Session Ready: account={acc.email} chat_id={chat_id} "
                    f"engine={self.engine.__class__.__name__} pool_status={'Pooled' if chat_id in self.active_chat_ids else 'New'}"
                )

                yield {"type": "meta", "chat_id": chat_id, "acc": acc}

                buffer = ""
                async for chunk_result in self.engine.fetch_chat(acc.token, chat_id, payload, buffered=False, cookies=acc.cookies):
                    if chunk_result.get("status") == 429:
                        log.warning(f"[Local backpressure {attempt+1}/{settings.MAX_RETRIES}] Engine queue full: account={acc.email} chat_id={chat_id}")
                        raise Exception("local_backpressure: engine queue full")
                    if chunk_result.get("status") != 200 and chunk_result.get("status") != "streamed":
                        body_preview = (chunk_result.get("body", "")[:120]).replace("\n", "\\n")
                        log.warning(
                            f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Upstream chunk error: account={acc.email} chat_id={chat_id} "
                            f"status={chunk_result.get('status')} body_preview={body_preview!r}"
                        )
                        raise Exception(f"HTTP {chunk_result['status']}: {chunk_result.get('body', '')[:100]}")

                    if "chunk" in chunk_result:
                        buffer += chunk_result["chunk"]
                        while "\n\n" in buffer:
                            msg, buffer = buffer.split("\n\n", 1)
                            events = self.parse_sse_chunk(msg)
                            for evt in events:
                                yield {"type": "event", "event": evt}
                    elif "body" in chunk_result and chunk_result["body"] and chunk_result["body"] != "streamed":
                        buffer += chunk_result["body"]
                
                if buffer:
                    events = self.parse_sse_chunk(buffer)
                    for evt in events:
                        yield {"type": "event", "event": evt}
                log.info(f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Stream finished: account={acc.email} chat_id={chat_id} buffered_chars={len(buffer)}")
                self.active_chat_ids.discard(chat_id)
                return

            except Exception as e:
                if chat_id:
                    self.active_chat_ids.discard(chat_id)
                err_msg = str(e).lower()
                should_save = False
                if "local_backpressure" in err_msg or "engine queue full" in err_msg:
                    acc.last_error = str(e)
                    log.warning(f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Local backpressure: account={acc.email} error={e}")
                elif "429" in err_msg or "rate limit" in err_msg or "too many" in err_msg:
                    self.account_pool.mark_rate_limited(acc, error_message=str(e))
                    exclude.add(acc.email)
                    log.warning(f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Marked as rate limited: account={acc.email} error={e}")
                elif _is_pending_activation_error(err_msg):
                    self.account_pool.mark_invalid(acc, reason="pending_activation", error_message=str(e))
                    exclude.add(acc.email)
                    should_save = True
                    log.warning(f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Marked as pending activation: account={acc.email} error={e}")
                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                elif _is_banned_error(err_msg):
                    self.account_pool.mark_invalid(acc, reason="banned", error_message=str(e))
                    exclude.add(acc.email)
                    log.warning(f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Marked as banned: account={acc.email} error={e}")
                elif _is_auth_error(err_msg):
                    self.account_pool.mark_invalid(acc, reason="auth_error", error_message=str(e))
                    exclude.add(acc.email)
                    log.warning(f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Marked as auth error: account={acc.email} error={e}")
                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                    if hasattr(self.engine, "get_page_diagnostic"):
                        try:
                            diag = await self.engine.get_page_diagnostic()
                            if diag:
                                log.warning(f"[Smart Diagnostic] State: {diag['state']} | URL: {diag['url']}")
                                if diag['state'] in ("captcha", "login_required"):
                                    log.warning(f"[Smart Diagnostic] Blocker detected! Triggering Browser Warmup via Auto-Heal.")
                                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                                elif "status=0" in err_msg or "waf" in err_msg:
                                    log.warning(f"[Smart Diagnostic] Possible WAF block. Forcing session refresh.")
                                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                        except Exception as diag_err:
                            log.error(f"[Smart Diagnostic] Diagnostic failed: {diag_err}")

                if should_save:
                    await self.account_pool.save()

                log.warning(f"[Retry {attempt+1}/{settings.MAX_RETRIES}] Account failed, preparing retry: account={acc.email} error={e}")
                
            finally:
                self.account_pool.release(acc)
                
        raise Exception(f"All {settings.MAX_RETRIES} attempts failed. Please check upstream accounts.")

    def _extract_urls_from_extra(self, extra: dict) -> list[str]:
        """从 SSE event 的 extra 字段提取图片 URL。

        已知格式：
        - extra.tool_result[0].image  (image_gen_tool finished 事件，最主要路径)
        - extra.image_url / extra.wanx_image_url / extra.imageUrl
        - extra.image_urls / extra.images / extra.imageUrls (列表)
        """
        urls = []
        if not extra or not isinstance(extra, dict):
            return urls

        # ① image_gen_tool 完成事件：extra.tool_result[].image
        tool_result = extra.get("tool_result")
        if isinstance(tool_result, list):
            for item in tool_result:
                if isinstance(item, dict):
                    for key in ("image", "url", "src", "imageUrl", "image_url"):
                        val = item.get(key)
                        if isinstance(val, str) and val.startswith("http"):
                            urls.append(val)
                elif isinstance(item, str) and item.startswith("http"):
                    urls.append(item)

        # ② 平铺字段
        for key in ("image_url", "wanx_image_url", "imageUrl"):
            val = extra.get(key)
            if isinstance(val, str) and val.startswith("http"):
                urls.append(val)

        # ③ 列表字段
        for key in ("image_urls", "images", "imageUrls"):
            val = extra.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.startswith("http"):
                        urls.append(item)
                    elif isinstance(item, dict):
                        for sub_key in ("url", "src", "image", "imageUrl"):
                            sub_val = item.get(sub_key)
                            if isinstance(sub_val, str) and sub_val.startswith("http"):
                                urls.append(sub_val)
        return urls

    async def image_generate_with_retry(self, model: str, prompt: str, n: int = 1, exclude_accounts: Optional[set[str]] = None, preferred_email: str = None) -> tuple[str, "Account", str]:
        """Invoke Qwen T2I to generate an image, returns (raw response text, account used, chat_id)"""
        # Dynamic model resolution
        model = resolve_model(model, self.account_pool.discovered_models)
        
        exclude = set(exclude_accounts or set())
        for attempt in range(settings.MAX_RETRIES):
            acc = await self.account_pool.acquire_wait(timeout=60, exclude=exclude, preferred_email=preferred_email)
            if not acc:
                pool_status = self.account_pool.status()
                raise Exception(
                    f"No available accounts in pool "
                    f"(valid={pool_status['valid']}, rate_limited={pool_status['rate_limited']})"
                )

            chat_id: Optional[str] = None
            try:
                chat_id = await self.create_chat(acc.token, model, chat_type="t2i", cookies=acc.cookies)
                self.active_chat_ids.add(chat_id)
                payload = self._build_image_payload(chat_id, model, prompt, n=n)

                raw_body_parts: list[str] = []  # Keep original SSE body for debugging
                answer_text = ""
                extra_urls: list[str] = []
                buffer = ""

                async for chunk_result in self.engine.fetch_chat(acc.token, chat_id, payload, cookies=acc.cookies):
                    if chunk_result.get("status") == 429:
                        raise Exception("Engine Queue Full")
                    if chunk_result.get("status") not in (200, "streamed"):
                        raise Exception(f"HTTP {chunk_result['status']}: {chunk_result.get('body', '')[:200]}")

                    # 把原始文本拼进 buffer
                    raw = ""
                    if "chunk" in chunk_result:
                        raw = chunk_result["chunk"]
                    elif "body" in chunk_result:
                        raw = chunk_result.get("body", "") or ""
                    if not raw:
                        continue

                    raw_body_parts.append(raw)
                    buffer += raw

                # Process entire buffer
                raw_body = "".join(raw_body_parts)
                log.info(f"[T2I] Raw SSE body (first 1000 chars): {raw_body[:1000]!r}")

                for line in raw_body.splitlines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data_str)
                    except Exception:
                        continue

                    # Print every SSE event for diagnostic
                    log.info(f"[T2I-SSE] Event: {json.dumps(obj, ensure_ascii=False)[:400]}")

                    # 从 choices[0].delta 提取
                    if obj.get("choices"):
                        delta = obj["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        phase = delta.get("phase", "answer")
                        extra = delta.get("extra", {})
                        log.info(f"[T2I-SSE] phase={phase!r} content_len={len(content)} content_preview={content[:100]!r}")
                        # 捕获所有文本内容
                        answer_text += content
                        # 捕获 extra 字段里的图片 URL
                        extra_urls.extend(self._extract_urls_from_extra(extra))
                    elif obj.get("phase"):
                        # 直接顶层 phase 格式
                        content = obj.get("content", "") or obj.get("text", "") or ""
                        phase = obj.get("phase", "")
                        extra = obj.get("extra", {})
                        log.info(f"[T2I-SSE] Top-level phase={phase!r} content_len={len(content)} content_preview={content[:100]!r}")
                        answer_text += content
                        extra_urls.extend(self._extract_urls_from_extra(extra))

                # If image URLs found in extra, append them as Markdown
                if extra_urls:
                    log.info(f"[T2I] Extracted {len(extra_urls)} image URLs from extra field: {extra_urls}")
                    for url in extra_urls:
                        answer_text += f"\n![image]({url})"

                # Use raw body as fallback if answer_text is empty
                if not answer_text:
                    answer_text = raw_body

                self.active_chat_ids.discard(chat_id)
                log.info(f"[T2I] Generation completed, response_len={len(answer_text)}: {answer_text[:200]!r}")
                return answer_text, acc, chat_id

            except Exception as e:
                if chat_id:
                    self.active_chat_ids.discard(chat_id)
                err_msg = str(e).lower()
                if "429" in err_msg or "rate limit" in err_msg or "too many" in err_msg:
                    self.account_pool.mark_rate_limited(acc, error_message=str(e))
                    exclude.add(acc.email)
                elif _is_pending_activation_error(err_msg):
                    self.account_pool.mark_invalid(acc, reason="pending_activation", error_message=str(e))
                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                    exclude.add(acc.email)
                elif _is_banned_error(err_msg):
                    self.account_pool.mark_invalid(acc, reason="banned", error_message=str(e))
                    exclude.add(acc.email)
                elif _is_auth_error(err_msg):
                    self.account_pool.mark_invalid(acc, reason="auth_error", error_message=str(e))
                    asyncio.create_task(self.auth_resolver.auto_heal_account(acc))
                    exclude.add(acc.email)
                # Generic errors don't exclude the account, allowing a retry with the same account
                self.account_pool.release(acc)
                log.warning(f"[T2I Retry {attempt+1}/{settings.MAX_RETRIES}] Account {acc.email} failed: {e}")

        raise Exception(f"All {settings.MAX_RETRIES} T2I attempts failed.")
