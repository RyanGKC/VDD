import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_CACHE_PATH = str(Path(__file__).parent.parent / "cache.db")

class PersistentCache:
    def __init__(self, db_path=DEFAULT_CACHE_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS api_cache (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        timestamp DATETIME
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mock_cache (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        timestamp DATETIME
                    )
                ''')
                conn.commit()
        except sqlite3.OperationalError as e:
            print(f"WARNING: Failed to initialize cache db at {self.db_path}: {e}")

    def get(self, key: str, use_mock: bool = False) -> str | None:
        table = "mock_cache" if use_mock else "api_cache"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT value FROM {table} WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return row[0]
        return None

    def set(self, key: str, value: str, use_mock: bool = False):
        table = "mock_cache" if use_mock else "api_cache"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT OR REPLACE INTO {table} (key, value, timestamp) VALUES (?, ?, ?)",
                (key, value, datetime.now().isoformat())
            )
            conn.commit()

    def get_by_prefix(self, prefix: str, use_mock: bool = False) -> list[tuple[str, str]]:
        table = "mock_cache" if use_mock else "api_cache"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT key, value FROM {table} WHERE key LIKE ?", (f"{prefix}%",))
            return cursor.fetchall()
