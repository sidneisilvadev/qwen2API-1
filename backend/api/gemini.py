from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
import json
import logging
import asyncio
from backend.services.qwen_client import QwenClient
from backend.services.token_calc import calculate_usage
from backend.core.config import resolve_model, settings
from backend.core.sqlite_db import AsyncSQLiteDB

log = logging.getLogger("qwen2api.gemini")
router = APIRouter()

@router.post("/v1beta/models/{model}:generateContent")
@router.post("/v1/models/{model}:generateContent")
@router.post("/v1beta/models/{model}:streamGenerateContent")
@router.post("/v1/models/{model}:streamGenerateContent")
@router.post("/models/{model}:generateContent")
@router.post("/models/{model}:streamGenerateContent")
async def gemini_stream(model: str, request: Request):
    """
    Gemini API 协议转换层 -> 转入 OpenAI/Qwen 统一处理内核
    """
    app = request.app
    db: AsyncSQLiteDB = app.state.db
    qwen_client = app.state.qwen_client
    pool = app.state.account_pool
    
    token = request.query_params.get("key", "").strip() or request.query_params.get("api_key", "").strip()
    
    if not token:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        token = request.headers.get("x-api-key", "").strip()

    admin_k = settings.ADMIN_KEY

    # Unified SQLite Auth
    user = None
    if token == admin_k:
        user = {"id": token, "name": "Master Admin", "quota": 999999999, "used_tokens": 0}
    else:
        # Check dynamic admin keys
        is_admin = await db.fetch_one("SELECT key FROM admin_keys WHERE key = ?", (token,))
        if is_admin:
            user = {"id": token, "name": "Dynamic Admin", "quota": 999999999, "used_tokens": 0}
        else:
            # Check API Keys
            is_valid_key = await db.fetch_one("SELECT key FROM api_keys WHERE key = ?", (token,))
            if not is_valid_key:
                raise HTTPException(status_code=401, detail="Invalid API Key")
            user = await db.fetch_one("SELECT * FROM users WHERE id = ?", (token,))

    if user and user.get("quota", 0) <= user.get("used_tokens", 0):
        raise HTTPException(status_code=402, detail="Quota Exceeded")
        
    body = await request.json()
    resolved_model = resolve_model(model, pool.discovered_models)
    contents = body.get("contents", [])

    content = ""
    for m in contents:
        if m.get("role") == "user":
            for part in m.get("parts", []):
                content += part.get("text", "") + "\n"

    # Single Provider (Qwen Only)
    target_client = qwen_client
    log.info(f"[Gemini-Routing] model={resolved_model}, prompt_len={len(content)}")

    try:
        # Note: chat_stream_events_with_retry returns a generator in some contexts, but here it might be different?
        # Re-checking the direct call pattern. In gemini.py it was used as: events, chat_id, acc = await client...
        # But chat_stream_events_with_retry actually is an async generator.
        # Wait, the original gemini.py had a BUG here (await generator). I'll fix it too.
        
        async def generate():
            full_text = ""
            acc = None
            chat_id = None
            try:
                async for evt in target_client.chat_stream_events_with_retry(resolved_model, content):
                    if evt.get("type") == "meta":
                        chat_id = evt.get("chat_id")
                        acc = evt.get("acc")
                        continue
                    if evt.get("type") == "event":
                        inner = evt.get("event", {})
                        if inner.get("type") == "delta":
                            text = inner.get("content", "")
                            full_text += text
                            chunk = {
                                "candidates": [
                                    {"content": {"parts": [{"text": text}], "role": "model"}}
                                ]
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"

                log.info(f"[Gemini] Request complete. Generated {len(full_text)} characters.")
                        
                usage = calculate_usage(content, full_text)
                
                # Update SQLite usage
                if user and token != admin_k:
                    await db.execute("UPDATE users SET used_tokens = used_tokens + ? WHERE id = ?", 
                                   (usage["total_tokens"], token))
                    await db.commit()
                
            finally:
                if acc:
                    target_client.account_pool.release(acc)
                    if chat_id:
                        asyncio.create_task(target_client.delete_chat(acc.token, chat_id))
        
        return StreamingResponse(generate(), media_type="text/event-stream")
        
    except Exception as e:
        log.error(f"Gemini proxy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
