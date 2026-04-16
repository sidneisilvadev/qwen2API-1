from fastapi import APIRouter, Request, HTTPException
import json
import uuid
import logging
from backend.services.token_calc import count_tokens
from backend.core.config import resolve_model, settings
from backend.core.sqlite_db import AsyncSQLiteDB

log = logging.getLogger("qwen2api.embeddings")
router = APIRouter()

@router.post("/embeddings")
@router.post("/v1/embeddings")
async def create_embeddings(request: Request):
    """
    Embeddings 模拟/转发接口。
    通义千问 Web 版没有原生的 Embeddings 接口。
    """
    app = request.app
    db: AsyncSQLiteDB = app.state.db
    
    # 鉴权
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""

    if not token:
        token = request.headers.get("x-api-key", "").strip()
    if not token:
        token = request.query_params.get("key", "").strip() or request.query_params.get("api_key", "").strip()

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
    model = body.get("model", "text-embedding-ada-002")
    input_text = body.get("input", "")
    
    if isinstance(input_text, str):
        input_list = [input_text]
    else:
        input_list = input_text
        
    data = []
    total_tokens = 0
    
    for i, text in enumerate(input_list):
        tokens = count_tokens(text)
        total_tokens += tokens
        
        # 模拟生成 1536 维的特征向量
        import hashlib
        h = hashlib.sha256(text.encode('utf-8')).hexdigest()
        base_val = int(h[:8], 16) / 0xffffffff
        vector = [(base_val * (j % 10) / 10.0) - 0.5 for j in range(1536)]
        
        data.append({
            "object": "embedding",
            "embedding": vector,
            "index": i
        })
        
    usage = {
        "prompt_tokens": total_tokens,
        "total_tokens": total_tokens
    }
    
    # Update SQLite usage
    if user and token != admin_k:
        await db.execute("UPDATE users SET used_tokens = used_tokens + ? WHERE id = ?", 
                       (total_tokens, token))
        await db.commit()
    
    return {
        "object": "list",
        "data": data,
        "model": model,
        "usage": usage
    }
