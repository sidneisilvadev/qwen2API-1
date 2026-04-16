import time
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel
from backend.core.config import settings, MODEL_MAP, resolve_model
from backend.core.sqlite_db import AsyncSQLiteDB
from backend.core.account_pool import AccountPool, Account
from backend.services.qwen_client import QwenClient
from backend.services.auth_resolver import activate_account as activate_logic, register_qwen_account

router = APIRouter()
log = logging.getLogger("qwen2api.admin")

async def verify_admin(request: Request, authorization: str = Header(None)):
    try:
        if not authorization or not authorization.startswith("Bearer "):
            log.warning(f"[Admin] Auth failed: Missing or invalid Bearer header")
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        token = authorization.split("Bearer ", 1)[1].strip()
        admin_key = settings.ADMIN_KEY.strip()

        # Hardening Phase 1: Zero-dependency Master Key (Emergency Fallback)
        if token == admin_key:
            return token

        # Hardening Phase 2: Check System Readiness
        db: AsyncSQLiteDB = getattr(request.app.state, "db", None)
        if not db:
            log.warning("[Admin] Access attempted while system is initializing (db not ready)")
            raise HTTPException(status_code=503, detail="System Initializing: Database not ready")

        # Hardening Phase 3: Dynamic admin keys in SQLite
        try:
            is_dynamic_admin = await db.fetch_one("SELECT key FROM admin_keys WHERE key = ?", (token,))
            if is_dynamic_admin:
                return token
        except Exception as db_err:
            log.error(f"[Admin] Database error during admin verify: {db_err}")
            raise HTTPException(status_code=503, detail="System Busy: Database temporarily unavailable")

        log.warning(f"[Admin] Access denied: Token mismatch.")
        raise HTTPException(status_code=403, detail="Forbidden: Admin Key Mismatch")
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[Admin] Crash in verify_admin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Auth Error")

async def verify_any_key(request: Request, authorization: str = Header(None)):
    """Allows Admin Keys OR Usage Keys (sk-qwen-). Used for non-destructive discovery."""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        token = authorization.split("Bearer ", 1)[1].strip()
        
        # 1. Check Master Admin
        if token == settings.ADMIN_KEY:
            return token
            
        db: AsyncSQLiteDB = request.app.state.db
        
        # 2. Check Dynamic Admin Keys
        is_admin = await db.fetch_one("SELECT key FROM admin_keys WHERE key = ?", (token,))
        if is_admin:
            return token
            
        # 3. Check Usage Keys (sk-qwen-)
        is_usage = await db.fetch_one("SELECT key FROM api_keys WHERE key = ?", (token,))
        if is_usage:
            return token
            
        raise HTTPException(status_code=403, detail="Invalid API Key")
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error in verify_any_key: {e}")
        raise HTTPException(status_code=500, detail="Auth Error")

class UserCreate(BaseModel):
    name: str
    quota: int = 1000000

# --- SYSTEM STATUS ---

@router.get("/status", dependencies=[Depends(verify_admin)])
async def get_system_status(request: Request):
    try:
        # Check pool availability
        pool = getattr(request.app.state, "account_pool", None)
        if not pool:
            log.warning("[Admin] account_pool not initialized yet in app.state")
            return {
                "accounts": {"total": 0, "valid": 0, "invalid": 0, "rate_limited": 0, "pending_activation": 0},
                "models_discovered": 0,
                "engine_mode": getattr(settings, "ENGINE_MODE", "hybrid"),
                "status": "initializing",
                "version": settings.VERSION
            }
            
        # Check engine readiness
        engine = getattr(request.app.state, "gateway_engine", None)
        is_ready = getattr(engine, "_started", False) if engine else False
        
        pool_stats = pool.status()
        return {
            "accounts": pool_stats,
            "models_discovered": len(getattr(pool, "discovered_models", []) or []),
            "engine_mode": settings.ENGINE_MODE,
            "default_thinking": settings.DEFAULT_THINKING,
            "default_search": settings.DEFAULT_SEARCH,
            "status": "ready" if is_ready else "initializing",
            "version": settings.VERSION
        }
    except Exception as e:
        log.error(f"[Admin] Fatal crash in get_system_status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

# --- DYNAMIC MODELS ---

@router.get("/models", dependencies=[Depends(verify_any_key)])
async def list_discovered_models(request: Request):
    """List all models discovered dynamically from Qwen.ai. Accessible by ANY valid key."""
    pool: AccountPool = request.app.state.account_pool
    return {"models": pool.discovered_models}

@router.post("/models/sync", dependencies=[Depends(verify_admin)])
async def sync_models(request: Request):
    """Force a sync of models from all providers."""
    qwen_client = request.app.state.qwen_client
    pool = request.app.state.account_pool
    
    # 1. Sync from Qwen
    qwen_models = await qwen_client.sync_models()
    if qwen_models:
        await pool.update_discovered_models("qwen", qwen_models)
    
    return {
        "ok": True, 
        "counts": { 
            "qwen": len([m for m in pool.discovered_models if m.get("provider") == "qwen"])
        }, 
        "models": pool.discovered_models
    }

# --- USERS ---

@router.get("/users", dependencies=[Depends(verify_admin)])
async def list_users(request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    users = await db.fetch_all("SELECT * FROM users")
    return {"users": users}

@router.post("/users", dependencies=[Depends(verify_admin)])
async def create_user(user: UserCreate, request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    new_user = {
        "id": f"sk-{uuid.uuid4().hex}",
        "name": user.name,
        "quota": user.quota,
        "used_tokens": 0,
    }
    await db.execute(
        "INSERT INTO users (id, name, quota, used_tokens) VALUES (?, ?, ?, ?)",
        (new_user["id"], new_user["name"], new_user["quota"], new_user["used_tokens"])
    )
    await db.commit()
    return new_user

# --- ACCOUNTS ---

@router.get("/accounts", dependencies=[Depends(verify_admin)])
async def list_accounts(request: Request):
    pool: AccountPool = request.app.state.account_pool
    accounts = []
    for a in pool.accounts:
        item = a.to_dict()
        item["valid"] = a.valid
        item["inflight"] = a.inflight
        item["status_code"] = a.get_status_code()
        item["status_text"] = a.get_status_text()
        item["last_error"] = a.last_error
        accounts.append(item)
    return {"accounts": accounts}

@router.post("/accounts", dependencies=[Depends(verify_admin)])
async def add_account(request: Request):
    pool: AccountPool = request.app.state.account_pool
    client: QwenClient = request.app.state.qwen_client
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, detail="Invalid JSON body")

    token = data.get("token", "")
    if not token:
        raise HTTPException(400, detail="token is required")

    acc = Account(
        email=data.get("email", f"manual_{int(time.time())}@qwen"),
        password=data.get("password", ""),
        token=token,
        cookies=data.get("cookies", ""),
        username=data.get("username", ""),
    )

    is_valid = await client.verify_token(token)
    if not is_valid:
        acc.valid = False
        acc.status_code = "auth_error"
        acc.last_error = "Token verification failed"
        return {"ok": False, "error": acc.last_error}

    acc.valid = True
    acc.status_code = "valid"
    await pool.add(acc)
    return {"ok": True, "email": acc.email}

@router.delete("/accounts/{email}", dependencies=[Depends(verify_admin)])
async def delete_account(email: str, request: Request):
    pool: AccountPool = request.app.state.account_pool
    await pool.remove(email)
    return {"ok": True}

@router.delete("/accounts/mass/clear-history", dependencies=[Depends(verify_admin)])
async def clear_all_histories(request: Request):
    """Deep cleanup: deletes all internal chats for all accounts in the pool."""
    pool: AccountPool = request.app.state.account_pool
    client: QwenClient = request.app.state.qwen_client
    
    accounts = [a for a in pool.accounts if a.valid]
    log.info(f"[Cleanup] Starting mass history cleanup for {len(accounts)} accounts.")
    
    total_cleaned = 0
    for acc in accounts:
        try:
            await client.clear_account_history(acc.token)
            total_cleaned += 1
        except Exception as e:
            log.warning(f"[Cleanup] Failed for {acc.email}: {e}")
            
    return {"ok": True, "accounts_processed": total_cleaned}

# --- CAPTURE (COMMAND TOWER) ---

@router.post("/accounts/capture/launch", dependencies=[Depends(verify_admin)])
async def launch_capture_browser(request: Request):
    try:
        data = await request.json()
    except Exception as e:
        log.warning(f"[Admin] Launch capture JSON parse failed: {e}")
        data = {}
        
    provider = data.get("provider", "qwen")
    log.info(f"[Admin] Request to launch capture browser for provider: {provider}")
    
    from backend.services.session_capturer import global_capture_session
    try:
        result = await global_capture_session.launch(provider)
        log.info(f"[Admin] Launch result for {provider}: {result}")
        return result
    except Exception as e:
        log.error(f"[Admin] CRITICAL error launching browser for {provider}: {e}")
        return {"ok": False, "message": f"Erro crítico no servidor: {str(e)}"}

@router.post("/accounts/capture/extract", dependencies=[Depends(verify_admin)])
async def extract_capture_data(request: Request):
    from backend.services.session_capturer import global_capture_session
    pool: AccountPool = request.app.state.account_pool
    return await global_capture_session.extract(pool)

@router.post("/accounts/capture/stop", dependencies=[Depends(verify_admin)])
async def stop_capture_browser(request: Request):
    from backend.services.session_capturer import global_capture_session
    await global_capture_session.stop()
    return {"ok": True}

# --- SETTINGS & KEYS ---

@router.get("/settings", dependencies=[Depends(verify_admin)])
async def get_settings():
    return {
        "version": "2.2.0",
        "max_inflight_per_account": settings.MAX_INFLIGHT,
        "engine_mode": settings.ENGINE_MODE,
        "default_thinking": settings.DEFAULT_THINKING,
        "default_search": settings.DEFAULT_SEARCH,
        "model_aliases": {k: v for k, v in MODEL_MAP.items()},
    }

@router.put("/settings", dependencies=[Depends(verify_admin)])
async def update_settings(data: dict, request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    from backend.core.config import DB_MAPPING
    
    # 1. Update in-memory settings & Persist to DB
    for key, value in data.items():
        # Handle dashboard key names
        effective_key = key
        if key == "max_inflight_per_account": effective_key = "max_inflight"
        
        if effective_key in DB_MAPPING:
            field_name, field_type = DB_MAPPING[effective_key]
            
            # Type cast
            try:
                if field_type == "int": typed_val = int(value)
                elif field_type == "float": typed_val = float(value)
                elif field_type == "bool": typed_val = bool(value)
                else: typed_val = str(value)
                
                # Update memory
                setattr(settings, field_name, typed_val)
                
                # Update pool if specific fields
                if field_name == "MAX_INFLIGHT":
                    request.app.state.account_pool.max_inflight = typed_val
                
                # Persist to DB
                await db.set_setting(effective_key, typed_val, field_type)
                log.info(f"[Admin] Persistent setting updated: {effective_key} = {typed_val}")
                
            except Exception as e:
                log.error(f"[Admin] Failed to update setting {key}: {e}")

    if "model_aliases" in data:
        MODEL_MAP.clear()
        MODEL_MAP.update(data["model_aliases"])
        
    return {"ok": True}

@router.get("/keys", dependencies=[Depends(verify_admin)])
async def get_keys(request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    rows = await db.fetch_all("SELECT key FROM api_keys")
    return {"keys": [r["key"] for r in rows]}

@router.post("/keys", dependencies=[Depends(verify_admin)])
async def generate_key(request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    new_key = f"sk-qwen-{uuid.uuid4().hex[:20]}"
    await db.execute("INSERT INTO api_keys (key) VALUES (?)", (new_key,))
    await db.commit()
    return {"ok": True, "key": new_key}

@router.delete("/keys/{key}", dependencies=[Depends(verify_admin)])
async def delete_key(key: str, request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    await db.execute("DELETE FROM api_keys WHERE key = ?", (key,))
    await db.commit()
    return {"ok": True}

# --- DYNAMIC MASTER ADMIN KEYS ---

@router.get("/master-keys", dependencies=[Depends(verify_admin)])
async def list_admin_keys(request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    rows = await db.fetch_all("SELECT key, name, created_at FROM admin_keys")
    return {"keys": rows}

@router.post("/master-keys", dependencies=[Depends(verify_admin)])
async def create_admin_key(data: dict, request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    name = data.get("name", "New Admin")
    new_key = f"adm-{uuid.uuid4().hex[:16]}"
    await db.execute("INSERT INTO admin_keys (key, name) VALUES (?, ?)", (new_key, name))
    await db.commit()
    return {"ok": True, "key": new_key, "name": name}

@router.delete("/master-keys/{key}", dependencies=[Depends(verify_admin)])
async def delete_admin_key(key: str, request: Request):
    db: AsyncSQLiteDB = request.app.state.db
    await db.execute("DELETE FROM admin_keys WHERE key = ?", (key,))
    await db.commit()
    return {"ok": True}
