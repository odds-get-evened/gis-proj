"""Search data collector using SQLite for tracking search interactions and caching query resolution outcomes."""

import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SearchDataCollector:
    """Collects and persists search interactions, training data, and cached query resolutions using SQLite."""

    def __init__(self, db_path: Optional[str] = None, storage_path: Optional[str] = None):
        target_path = db_path or storage_path
        if target_path and target_path.endswith(".jsonl"):
            target_path = target_path.replace(".jsonl", ".db")
        self.db_path = target_path or os.path.join(
            os.path.expanduser("~"), ".gemini", "tmp", "gis-proj", "ai_search_cache.db"
        )
        self._ensure_database()

    def _get_connection(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_database(self) -> None:
        """Creates tables for interactions (training) and query_cache (local query serving)."""
        try:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS interactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        query TEXT NOT NULL,
                        result_type TEXT NOT NULL,
                        selected_suggestion TEXT,
                        gis_metadata TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS query_cache (
                        query_key TEXT PRIMARY KEY,
                        result_json TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            conn.close()
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")

    def log_interaction(
        self,
        query: str,
        result_type: str,
        selected_suggestion: Optional[Dict] = None,
        gis_metadata: Optional[Dict] = None,
    ) -> None:
        """Logs search interaction to SQLite and caches the resolved outcome for local query serving."""
        record = {
            "query": query,
            "result_type": result_type,
            "selected_suggestion": selected_suggestion,
            "gis_metadata": gis_metadata or {},
        }
        try:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO interactions (query, result_type, selected_suggestion, gis_metadata)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        query,
                        result_type,
                        json.dumps(selected_suggestion) if selected_suggestion else None,
                        json.dumps(gis_metadata) if gis_metadata else None,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO query_cache (query_key, result_json, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    """,
                    (query.strip().lower(), json.dumps(record)),
                )
            conn.close()
            logger.info(f"Logged search interaction & cached query: '{query}' -> type: {result_type}")
        except Exception as e:
            logger.error(f"Failed to log interaction to SQLite: {e}")

    def get_cached_result(self, query: str) -> Optional[Dict]:
        """Retrieves cached query resolution from SQLite to bypass external REST APIs."""
        query_key = query.strip().lower()
        try:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT result_json FROM query_cache WHERE query_key = ?",
                (query_key,),
            ).fetchone()
            conn.close()
            if row:
                return json.loads(row["result_json"])
        except Exception as e:
            logger.error(f"Failed to fetch cached result from SQLite: {e}")
        return None

    def load_dataset(self, max_records: int = 1000) -> List[Dict]:
        """Loads logged search interactions from SQLite for iterative training."""
        records = []
        try:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                SELECT query, result_type, selected_suggestion, gis_metadata
                FROM interactions
                ORDER BY id DESC
                LIMIT ?
                """,
                (max_records,),
            )
            for row in cursor:
                records.append({
                    "query": row["query"],
                    "result_type": row["result_type"],
                    "selected_suggestion": json.loads(row["selected_suggestion"]) if row["selected_suggestion"] else None,
                    "gis_metadata": json.loads(row["gis_metadata"]) if row["gis_metadata"] else {},
                })
            conn.close()
            records.reverse()
        except Exception as e:
            logger.error(f"Failed to load training dataset from SQLite: {e}")
        return records
