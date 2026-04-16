import os
import json
import logging
from pathlib import Path
from backend.core.sqlite_db import AsyncSQLiteDB
from backend.core.config import settings

log = logging.getLogger("qwen2api.migration")

async def run_auto_migration(db: AsyncSQLiteDB):
    """Detects existing JSON files and migrates them to SQLite if the DB is empty."""
    
    # Migration mapping: (JSON file path, SQLite table name, primary key)
    migrations = [
        (settings.ACCOUNTS_FILE, "accounts", "email"),
        (settings.USERS_FILE, "users", "id"),
        (Path(settings.SQLITE_DATA_DIR) / "api_keys.json", "api_keys", "key"),
        (settings.CAPTURES_FILE, "captures", "id")
    ]

    for json_path, table_name, pk in migrations:
        json_path = Path(json_path)
        if not json_path.exists():
            continue

        # Check if table already has data
        existing_count = await db.fetch_one(f"SELECT COUNT(*) as count FROM {table_name}")
        if existing_count and existing_count["count"] > 0:
            log.info(f"Skipping migration for {table_name}: Table already has data.")
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            if not isinstance(data, (list, dict)):
                continue

            # Normalized items for insertion
            items = []
            if isinstance(data, dict) and "keys" in data and table_name == "api_keys":
                items = [{"key": k} for k in data["keys"]]
            elif isinstance(data, list):
                items = data

            if not items:
                continue

            log.info(f"Migrating {len(items)} items from {json_path.name} to {table_name}...")
            
            for item in items:
                # Prepare keys and values for SQL
                # Ensure activation_pending/valid are converted to int for SQLite
                if "activation_pending" in item:
                    item["activation_pending"] = 1 if item["activation_pending"] else 0
                if "valid" in item:
                    item["valid"] = 1 if item["valid"] else 0
                
                # Special handling for captures database 'data' field which is JSON
                if table_name == "captures" and "data" in item:
                    # 'item' might already be the whole capture object
                    pass

                columns = ", ".join(item.keys())
                placeholders = ", ".join(["?" for _ in item])
                sql = f"INSERT OR IGNORE INTO {table_name} ({columns}) VALUES ({placeholders})"
                await db.execute(sql, tuple(item.values()))
            
            await db.commit()
            log.info(f"[SUCCESS] Migration complete for {table_name}.")
            
            # Optional: rename old file to .bak
            bak_path = json_path.with_suffix(".json.bak")
            os.rename(json_path, bak_path)
            log.info(f"Renamed {json_path.name} to {bak_path.name} as backup.")

        except Exception as e:
            log.error(f"Migration failed for {table_name}: {e}")
