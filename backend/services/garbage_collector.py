import asyncio
import logging
import json
from backend.services.qwen_client import QwenClient

log = logging.getLogger("qwen2api.gc")

async def garbage_collect_chats(client: QwenClient):
    """
    Background daemon: every 15 minutes, checks all active accounts.
    Calls Qwen API to list and delete orphan chats created by the API (title starts with 'api_').
    Active chat_ids currently being used by requests are skipped.
    """
    while True:
        await asyncio.sleep(900)  # 15分钟
        log.info("[GC] Starting automatic orphan chat cleanup...")
        pool = client.account_pool
        for acc in pool.accounts:
            if not acc.is_available():
                continue
            try:
                # Fetch chat list
                res = await client.engine.api_call("GET", "/api/v2/chats?limit=50", acc.token)
                if isinstance(res, dict) and res.get("status") == 200:
                    data = json.loads(res.get("body", "{}"))
                    if isinstance(data, dict):
                        chats = data.get("data", [])
                        if isinstance(chats, list):
                            for c in chats:
                                if isinstance(c, dict) and c.get("title", "").startswith("api_"):
                                    chat_id = c["id"]
                                    if chat_id in client.active_chat_ids:
                                        log.info(f"[GC] Skipping active chat {chat_id}, currently in use")
                                        continue
                                    # Async delete
                                    asyncio.create_task(client.delete_chat(acc.token, chat_id))
            except Exception as e:
                log.warning(f"[GC] Failed to cleanup account {acc.email}: {e}")
