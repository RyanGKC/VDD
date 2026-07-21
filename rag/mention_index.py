import sqlite3
from typing import List


def init_mention_index(db_path: str = "mention_index.db") -> sqlite3.Connection:
    """
    Opens (creating if needed) the SQLite mention index and ensures the
    entity_mentions table exists.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_mentions (
            entity_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            PRIMARY KEY (entity_id, chunk_id)
        )
        """
    )
    conn.commit()
    return conn


def record_mentions(conn: sqlite3.Connection, chunk_id: str, entity_ids: List[str]) -> None:
    """
    Records that the given chunk mentions each of the given resolved
    entity ids. Call this at ingestion time once mentioned_entities has
    been resolved to canonical entity ids.
    """
    if not entity_ids:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO entity_mentions (entity_id, chunk_id) VALUES (?, ?)",
        [(entity_id, chunk_id) for entity_id in entity_ids],
    )
    conn.commit()


def get_chunks_mentioning(conn: sqlite3.Connection, entity_id: str) -> List[str]:
    """
    Returns all chunk ids that mention the given resolved entity id,
    whether as the primary subject or a secondary mention.
    """
    cursor = conn.execute(
        "SELECT chunk_id FROM entity_mentions WHERE entity_id = ?", (entity_id,)
    )
    return [row[0] for row in cursor.fetchall()]
