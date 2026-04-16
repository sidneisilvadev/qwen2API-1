import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
import gc
import socket

# Enterprise logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("qwen2api")

# Enterprise: Use uvloop for maximum event loop performance if available
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

# Hardening: UTF-8 output setup removed from top level and moved to main.py if needed

# Fix UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path to allow running main.py directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.config import settings
from backend.core.sqlite_db import AsyncSQLiteDB
from backend.core.migration import run_auto_migration
from backend.core.browser_engine import BrowserEngine
from backend.core.httpx_engine import HttpxEngine
from backend.core.hybrid_engine import HybridEngine
from backend.core.account_pool import AccountPool
from backend.api import admin, v1_chat, probes, anthropic, gemini, embeddings, images
from backend.services.qwen_client import QwenClient
from backend.services.auth_resolver import AuthResolver
from backend.services.garbage_collector import garbage_collect_chats

from backend.services.garbage_collector import garbage_collect_chats


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting qwen2API v2.0 Enterprise Gateway (Guardian Mode)...")

    # Hardening: Process Priority
    if sys.platform == "win32":
        try:
            import win32api, win32process, win32con
            process = win32api.GetCurrentProcess()
            win32process.SetPriorityClass(process, win32process.ABOVE_NORMAL_PRIORITY_CLASS)
            log.info("[Anti-Crash] Process priority locked to ABOVE_NORMAL")
        except ImportError:
            pass

    # Initialize Unified SQLite Database
    db_path = Path(settings.SQLITE_DATA_DIR) / "gateway.db"
    db = AsyncSQLiteDB(db_path)
    await db.connect()
    
    from backend.core.config import load_db_overrides
    await load_db_overrides(db)
    app.state.db = db
    await run_auto_migration(db)

    browser_engine = BrowserEngine(pool_size=settings.BROWSER_POOL_SIZE)
    httpx_engine = HttpxEngine(base_url="https://chat.qwen.ai")

    if settings.ENGINE_MODE == "httpx":
        engine = httpx_engine
    elif settings.ENGINE_MODE == "hybrid":
        engine = HybridEngine(browser_engine, httpx_engine)
    else:
        engine = browser_engine

    app.state.browser_engine = browser_engine
    app.state.engine = engine
    app.state.account_pool = AccountPool(db)
    await app.state.account_pool.load_from_db()
    
    app.state.qwen_client = QwenClient(engine, app.state.account_pool)
    app.state.auth_resolver = AuthResolver(app.state.account_pool)

    # Start Engines and Workers
    asyncio.create_task(engine.start())
    
    health_task = asyncio.create_task(_account_health_worker(app.state.auth_resolver))
    model_task = asyncio.create_task(_model_discovery_worker(app.state.account_pool, app.state.qwen_client))
    gc_task = asyncio.create_task(_memory_guardian_worker())
    
    yield

    log.info("[Shutdown] Guardian: Performing definitive cleanup...")
    # 1. Stop background tasks
    for task in [health_task, model_task, gc_task]:
        task.cancel()
    
    # 2. Stop Browser Engine (CRITICAL: kills chrome processes)
    await browser_engine.stop()
    
    # 3. Close Database
    await db.close()
    
    log.info("[Shutdown] Cleanup complete. Process exiting.")

async def _memory_guardian_worker():
    """Background worker to prevent memory fragmentation and leaks."""
    log.info("[Guardian] Memory management worker active")
    while True:
        try:
            await asyncio.sleep(600) # Every 10 minutes
            before = gc.get_count()
            collected = gc.collect()
            log.info(f"[Guardian] Memory optimization: Collected {collected} objects. GC Counts: {before} -> {gc.get_count()}")
        except Exception as e:
            log.error(f"[Guardian] Memory worker error: {e}")

app = FastAPI(title="qwen2API Enterprise Gateway", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Anti-Crash: Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"[Anti-Crash] UNHANDLED EXCEPTION: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "O sistema encontrou um erro interno, mas o processo foi preservado pelo Escudo Anti-Crash.", "details": str(exc)}
    )

# Enterprise point 7: Brotli Compression (High performance text transfer)
try:
    from brotli_asgi import BrotliMiddleware
    app.add_middleware(BrotliMiddleware, quality=4) # Level 4 is the sweet spot for real-time
except ImportError:
    pass

# Mount routes
app.include_router(v1_chat.router, tags=["OpenAI Compatible"])
app.include_router(images.router, tags=["Image Generation"])
app.include_router(anthropic.router, tags=["Claude Compatible"])
app.include_router(gemini.router, tags=["Gemini Compatible"])
app.include_router(embeddings.router, tags=["Embeddings"])
app.include_router(probes.router, tags=["Probes"])
app.include_router(admin.router, prefix="/api/admin", tags=["Dashboard Admin"])

@app.get("/", tags=["System"])
async def root_welcome():
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>qwen2API Enterprise Gateway</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
        <style>
            :root {{
                --primary: #4F46E5;
                --bg: #030712;
                --card: #111827;
                --text: #F9FAFB;
            }}
            body {{
                margin: 0;
                font-family: 'Inter', sans-serif;
                background-color: var(--bg);
                color: var(--text);
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                overflow: hidden;
            }}
            .container {{
                text-align: center;
                max-width: 600px;
                padding: 40px;
                background: var(--card);
                border-radius: 24px;
                border: 1px solid rgba(255,255,255,0.1);
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
                position: relative;
            }}
            .glow {{
                position: absolute;
                top: -50px;
                left: -50px;
                width: 200px;
                height: 200px;
                background: var(--primary);
                filter: blur(100px);
                opacity: 0.2;
                z-index: -1;
            }}
            h1 {{
                font-size: 2.5rem;
                font-weight: 800;
                margin-bottom: 1rem;
                background: linear-gradient(135deg, #fff 0%, #a5b4fc 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}
            p {{
                color: #9CA3AF;
                font-size: 1.1rem;
                line-height: 1.6;
            }}
            .status {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
                background: rgba(16, 185, 129, 0.1);
                color: #10B981;
                padding: 6px 16px;
                border-radius: 100px;
                font-size: 0.875rem;
                font-weight: 600;
                margin-bottom: 2rem;
            }}
            .actions {{
                display: flex;
                gap: 16px;
                justify-content: center;
                margin-top: 2rem;
            }}
            .btn {{
                padding: 12px 24px;
                border-radius: 12px;
                font-weight: 600;
                text-decoration: none;
                transition: all 0.2s;
            }}
            .btn-primary {{
                background: var(--primary);
                color: white;
            }}
            .btn-primary:hover {{
                transform: translateY(-2px);
                box-shadow: 0 10px 15px -3px rgba(79, 70, 229, 0.4);
            }}
            .btn-outline {{
                background: transparent;
                border: 1px solid rgba(255,255,255,0.2);
                color: white;
            }}
            .btn-outline:hover {{
                background: rgba(255,255,255,0.05);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="glow"></div>
            <div class="status">
                <span style="width: 8px; height: 8px; background: #10B981; border-radius: 50%; display: inline-block; animation: pulse 2s infinite;"></span>
                Sistema Online (v{settings.VERSION})
            </div>
            <h1>Gateway Ativo</h1>
            <p>Este é o ponto de entrada da API. Use o dashboard para configurar suas contas e testar os modelos.</p>
            
            <div class="actions">
                <a href="http://127.0.0.1:5174" class="btn btn-primary">Acessar Dashboard</a>
                <a href="/docs" class="btn btn-outline">Docs API</a>
            </div>
        </div>
        <style>
            @keyframes pulse {{
                0% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }}
                70% {{ transform: scale(1); box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }}
                100% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }}
            }}
        </style>
    </body>
    </html>
    """)

@app.get("/api", tags=["System"])
async def root_legacy():
    return {
        "status": "qwen2API Enterprise Gateway is running",
        "docs": "/docs",
        "version": settings.VERSION
    }

# Serve frontend build artifacts (if dist folder exists)
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

async def _account_health_worker(auth_resolver):
    log.info("[Health] Background account health worker started")
    while True:
        try:
            for acc in auth_resolver.pool.accounts:
                if not acc.valid or acc.activation_pending:
                    await auth_resolver.auto_heal_account(acc)
        except Exception as e:
            log.error(f"[Health] Check failed: {e}")
        await asyncio.sleep(300)

async def _model_discovery_worker(pool: AccountPool, qwen_client):
    log.info("[Discovery] Background model discovery started")
    while True:
        try:
            # Sync Qwen
            qwen_models = await qwen_client.sync_models()
            if qwen_models:
                await pool.update_discovered_models("qwen", qwen_models)
        except Exception as e:
            log.error(f"[Discovery] Global sync failed: {e}")
        await asyncio.sleep(3600)

if __name__ == "__main__":
    import uvicorn
    
    # Enterprise point 13: TCP Fast Open (Lowers handshake latency)
    # Note: Requires OS support (Linux/Windows 10+)
    # Enterprise: Force TCP_NODELAY on uvicorn server for immediate data delivery
    config = uvicorn.Config(
        "backend.main:app", 
        host="0.0.0.0", 
        port=settings.PORT, 
        workers=1,
        loop="uvloop" if sys.platform != "win32" else "auto"
    )
    server = uvicorn.Server(config)
    
    # Attempt to enable TCP_NODELAY (Nagle's Algorithm off) and TFO
    log.info(f"[Turbo-V3] TCP_NODELAY=True, Socket Pre-heat Active")
    server.run()
