import aiosqlite
import json
import logging
from pathlib import Path
from typing import Any, List, Optional, Dict

log = logging.getLogger("qwen2api.db")

class AsyncSQLiteDB:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            
            # Hardening: Performance and Concurrency
            await self._conn.execute("PRAGMA journal_mode = WAL")
            await self._conn.execute("PRAGMA synchronous = NORMAL")
            await self._conn.execute(f"PRAGMA busy_timeout = 5000") # 5 seconds wait for locks
            
            await self._init_tables()
            log.info(f"Connected to SQLite database at {self.db_path} (WAL Mode enabled)")

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _init_tables(self):
        # 1. Accounts Table (Based on Account class)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                email TEXT PRIMARY KEY,
                password TEXT,
                token TEXT,
                cookies TEXT,
                username TEXT,
                provider TEXT DEFAULT "qwen",
                activation_pending INTEGER DEFAULT 0,
                status_code TEXT,
                last_error TEXT,
                last_request_started REAL DEFAULT 0.0,
                last_request_finished REAL DEFAULT 0.0,
                consecutive_failures INTEGER DEFAULT 0,
                rate_limit_strikes INTEGER DEFAULT 0,
                valid INTEGER DEFAULT 1
            )
        """)

        # 2. Users Table (Downstream users)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT,
                quota INTEGER DEFAULT 0,
                used_tokens INTEGER DEFAULT 0
            )
        """)

        # 3. Usage API Keys (For chat endpoints)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key TEXT PRIMARY KEY,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        # 4. Master Admin Keys (Dynamic admin access)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_keys (
                key TEXT PRIMARY KEY,
                name TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        # 5. Captures Table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS captures (
                id TEXT PRIMARY KEY,
                data TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        # 6. System Settings Table (Dynamic Configuration)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                type TEXT DEFAULT 'string',
                updated_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        # 7. Conversations Mapping & Memory Table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                account_email TEXT,
                qwen_chat_id TEXT,
                parent_convo_id TEXT, -- Para suporte a ECT (Tree)
                branch_topic TEXT,    -- Área técnica do ramo
                needs_fork INTEGER DEFAULT 1, -- Inicia como 1 para forçar o primeiro fork organizado
                tags TEXT,            -- JSON array
                summary TEXT,
                last_used REAL DEFAULT (strftime('%s', 'now')),
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        # 8. Conversation Archives (Knowledge Essence)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_archives (
                id TEXT PRIMARY KEY,
                tags TEXT,
                summary TEXT,
                archived_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        await self._conn.commit()

    async def get_setting(self, key: str, default: Any = None) -> Any:
        row = await self.fetch_one("SELECT value, type FROM system_settings WHERE key = ?", (key,))
        if not row:
            return default
        
        val, vtype = row["value"], row["type"]
        if vtype == "int": return int(val)
        if vtype == "float": return float(val)
        if vtype == "bool": return val.lower() in ("true", "1", "yes", "on")
        if vtype == "json": return json.loads(val)
        return val

    async def set_setting(self, key: str, value: Any, vtype: str = "string"):
        # Convert value to string for storage
        sval = json.dumps(value) if vtype == "json" else str(value)
        await self.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, type, updated_at) VALUES (?, ?, ?, strftime('%s', 'now'))",
            (key, sval, vtype)
        )
        await self.commit()

    async def prune_old_conversations(self, days: int = 30) -> List[Dict[str, str]]:
        """
        Move a essência para o arquivo e retorna os dados para exclusão remota na Qwen.
        Retorna: List[{"email": ..., "chat_id": ...}]
        """
        limit_ts = time.time() - (days * 86400)
        to_delete_remote = []
        try:
            # 1. Identifica os alvos
            rows = await self.fetch_all(
                "SELECT id, account_email, qwen_chat_id, tags, summary FROM conversations WHERE last_used < ?", 
                (limit_ts,)
            )
            
            if rows:
                for row in rows:
                    # 2. Arquiva a essência (se houver resumo)
                    if row["summary"]:
                        await self.execute(
                            "INSERT OR REPLACE INTO conversation_archives (id, tags, summary) VALUES (?, ?, ?)",
                            (row["id"], row["tags"], row["summary"])
                        )
                    
                    if row["account_email"] and row["qwen_chat_id"]:
                        to_delete_remote.append({
                            "email": row["account_email"],
                            "chat_id": row["qwen_chat_id"]
                        })
                
                # 3. Deleta o bruto local
                await self.execute("DELETE FROM conversations WHERE last_used < ?", (limit_ts,))
                await self.commit()
                log.info(f"[Pruning] Archived and deleted {len(rows)} old conversations local records.")
            
            return to_delete_remote
        except Exception as e:
            log.error(f"[Pruning] Error during hybrid cleanup: {e}")
            return []

    # Generic Helpers with Retry Logic (Enterprise Stability)
    async def _execute_with_retry(self, func, *args, **kwargs):
        import sqlite3
        import random
        max_retries = 5
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except (aiosqlite.OperationalError, sqlite3.OperationalError) as e:
                err_msg = str(e).lower()
                if "locked" in err_msg or "busy" in err_msg:
                    wait_time = (0.1 * (2 ** attempt)) + (random.random() * 0.1)
                    log.warning(f"[DB] Database locked, retrying {attempt+1}/{max_retries} in {wait_time:.3f}s...")
                    await asyncio.sleep(wait_time)
                    continue
                raise e
            except Exception as e:
                raise e
        # Final attempt
        return await func(*args, **kwargs)

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        async def _exec():
            return await self._conn.execute(sql, params)
        return await self._execute_with_retry(_exec)

    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        async def _fetch():
            async with self._conn.execute(sql, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
        return await self._execute_with_retry(_fetch)

    async def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        async def _fetch():
            async with self._conn.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        return await self._execute_with_retry(_fetch)

    async def commit(self):
        async def _commit():
            await self._conn.commit()
        await self._execute_with_retry(_commit)
