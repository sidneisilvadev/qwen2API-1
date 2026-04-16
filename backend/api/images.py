"""
Image Generation API - compatible with OpenAI /v1/images/generations specification.
"""
import re
import time
import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from backend.services.qwen_client import QwenClient
from backend.core.config import settings
from backend.core.sqlite_db import AsyncSQLiteDB

log = logging.getLogger("qwen2api.images")
router = APIRouter()

DEFAULT_IMAGE_MODEL = "qwen-max-latest"
IMAGE_MODEL_MAP = {
    "dall-e-3": "qwen-max-latest",
    "dall-e-2": "qwen-max-latest",
    "qwen-image": "qwen-max-latest",
    "qwen-image-plus": "qwen-max-latest",
    "qwen-image-turbo": "qwen-max-latest",
    "qwen-max": "qwen-max-latest",
}

def _extract_image_urls(text: str) -> list[str]:
    import re
    urls = []
    # 1. Padrão Markdown ![alt](url)
    urls.extend(re.findall(r'!\[.*?\]\((https?://.*?)\)', text))
    
    # 2. Padrão URL crua de domínios conhecidos da Qwen (inclusive subdomínios ali-)
    urls.extend(re.findall(r'(https?://(?:cdn|oss|ali-cdn|ali-oss)\.qwenlm\.ai/[^\s\)\"\'>]+)', text))
        
    # 3. Padrão de URL genérica se terminar em extensão de imagem
    urls.extend(re.findall(r'(https?://[^\s\)\"\'>]+\.(?:png|jpg|jpeg|webp|gif|svg|bmp))', text))
        
    # Limpeza e unicidade baseada no path (evita duplicatas com/sem query params)
    by_base = {}
    for url in urls:
        # Remove apenas caracteres que visivelmente pertencem ao markup (Markdown/HTML)
        u = url.strip().rstrip(")>\"'")
        if not u.startswith("http"):
            continue
        
        # Remove query params para identificar o arquivo base
        base = u.split('?')[0]
        # Mantém a versão mais longa (provavelmente a que tem o token de acesso ?key=)
        if base not in by_base or len(u) > len(by_base[base]):
            by_base[base] = u
            
    return list(by_base.values())

def _resolve_image_model(requested: str | None) -> str:
    if not requested:
        return DEFAULT_IMAGE_MODEL
    return IMAGE_MODEL_MAP.get(requested, DEFAULT_IMAGE_MODEL)

def _get_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key", "").strip()

@router.post("/v1/images/generations")
@router.post("/images/generations")
async def create_image(request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    client: QwenClient = request.app.state.qwen_client

    # Unified SQLite Auth
    token = _get_token(request)
    admin_k = settings.ADMIN_KEY
    
    user = None
    if token == admin_k:
        user = {"id": token, "name": "Master Admin", "quota": 999999999, "used_tokens": 0}
    else:
        is_admin = await db.fetch_one("SELECT key FROM admin_keys WHERE key = ?", (token,))
        if is_admin:
            user = {"id": token, "name": "Dynamic Admin", "quota": 999999999, "used_tokens": 0}
        else:
            is_valid_key = await db.fetch_one("SELECT key FROM api_keys WHERE key = ?", (token,))
            if not is_valid_key:
                raise HTTPException(status_code=401, detail="Invalid API Key")
            user = await db.fetch_one("SELECT * FROM users WHERE id = ?", (token,))

    if user and user.get("quota", 0) <= user.get("used_tokens", 0):
        raise HTTPException(status_code=402, detail="Quota Exceeded")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    prompt: str = body.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")

    n: int = min(max(int(body.get("n", 1)), 1), 4)
    # [FIX] Use qwen-max as default, it's more stable for T2I rooms
    model = body.get("model") or "qwen-max"
    
    # Resolve against discovered models if possible
    model = resolve_model(model, getattr(client.account_pool, "discovered_models", []))

    log.info(f"[T2I] model={model}, n={n}, prompt={prompt[:80]!r}")

    all_image_urls = []
    last_answer_parts = []

    try:
        max_attempts = n + 1
        attempts = 0
        
        while len(all_image_urls) < n and attempts < max_attempts:
            attempts += 1
            remaining = n - len(all_image_urls)
            try:
                answer_text, acc, chat_id = await client.image_generate_with_retry(model, prompt, n=remaining)
                
                urls = _extract_image_urls(answer_text)
                for u in urls:
                    if u not in all_image_urls:
                        all_image_urls.append(u)
                
                last_answer_parts.append(answer_text)
                asyncio.create_task(client.delete_chat(acc.token, chat_id))
                client.account_pool.release(acc)
            except Exception as e:
                log.warning(f"[T2I] Attempt {attempts} failed: {e}")
                if attempts >= max_attempts:
                    raise

        if not all_image_urls:
            raw_combined = "\n".join(last_answer_parts)
            log.warning(f"[T2I] Failed to extract any image URLs. Raw response: {raw_combined[:300]!r}")
            # If no URLs but we have answer text, maybe it's a safety block or error message from Qwen
            raise HTTPException(status_code=500, detail=f"No image URLs found. Response: {raw_combined[:100]}")

        # Usage update
        if user and token != admin_k:
            await db.execute("UPDATE users SET used_tokens = used_tokens + ? WHERE id = ?", 
                           (len("\n".join(last_answer_parts)) + len(prompt), token))
            await db.commit()

        data = [{"url": url, "revised_prompt": prompt} for url in all_image_urls[:n]]
        return JSONResponse({"created": int(time.time()), "data": data})

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[T2I] Fatal Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
