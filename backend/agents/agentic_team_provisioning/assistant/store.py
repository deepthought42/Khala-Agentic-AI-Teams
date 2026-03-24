"""SQLite-backed persistence for agentic teams and process-design conversations."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from agentic_team_provisioning.models import (
    AgenticTeam,
    ConversationMessage,
    ProcessDefinition,
)

logger = logging.getLogger(__name__)

_DB_DIR = os.getenv("AGENT_CACHE", os.path.join(os.path.expanduser("~"), ".agent_cache"))
_DB_PATH = os.path.join(_DB_DIR, "agentic_team_provisioning.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgenticTeamStore:
    """Thread-safe SQLite store for teams, processes, and conversations."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _DB_PATH
        self._lock = threading.Lock()
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS teams (
                    team_id     TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS processes (
                    process_id  TEXT PRIMARY KEY,
                    team_id     TEXT NOT NULL REFERENCES teams(team_id),
                    data_json   TEXT NOT NULL DEFAULT '{}',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_processes_team ON processes(team_id);

                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    team_id         TEXT NOT NULL REFERENCES teams(team_id),
                    process_id      TEXT,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_team ON conversations(team_id);

                CREATE TABLE IF NOT EXISTS conv_messages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
                    role            TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    timestamp       TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conv_messages_conv ON conv_messages(conversation_id);
                """
            )

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------

    def create_team(self, name: str, description: str = "") -> AgenticTeam:
        team_id = str(uuid.uuid4())
        now = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO teams (team_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (team_id, name, description, now, now),
            )
        return AgenticTeam(
            team_id=team_id, name=name, description=description, created_at=now, updated_at=now
        )

    def get_team(self, team_id: str) -> Optional[AgenticTeam]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM teams WHERE team_id = ?", (team_id,)).fetchone()
            if not row:
                return None
            processes = self._load_processes(conn, team_id)
        return AgenticTeam(
            team_id=row["team_id"],
            name=row["name"],
            description=row["description"],
            processes=processes,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_teams(self) -> list[dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT t.*, (SELECT COUNT(*) FROM processes p WHERE p.team_id = t.team_id) AS process_count
                FROM teams t ORDER BY t.created_at DESC
                """
            ).fetchall()
        return [
            {
                "team_id": r["team_id"],
                "name": r["name"],
                "description": r["description"],
                "process_count": r["process_count"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Processes
    # ------------------------------------------------------------------

    def save_process(self, team_id: str, process: ProcessDefinition) -> None:
        now = _now_iso()
        data = process.model_dump(mode="json")
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM processes WHERE process_id = ?", (process.process_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE processes SET data_json = ?, updated_at = ? WHERE process_id = ?",
                    (json.dumps(data), now, process.process_id),
                )
            else:
                conn.execute(
                    "INSERT INTO processes (process_id, team_id, data_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (process.process_id, team_id, json.dumps(data), now, now),
                )
            conn.execute("UPDATE teams SET updated_at = ? WHERE team_id = ?", (now, team_id))

    def get_process(self, process_id: str) -> Optional[ProcessDefinition]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM processes WHERE process_id = ?", (process_id,)
            ).fetchone()
            if not row:
                return None
        return ProcessDefinition(**json.loads(row["data_json"]))

    def _load_processes(self, conn: sqlite3.Connection, team_id: str) -> list[ProcessDefinition]:
        rows = conn.execute(
            "SELECT data_json FROM processes WHERE team_id = ? ORDER BY created_at", (team_id,)
        ).fetchall()
        return [ProcessDefinition(**json.loads(r["data_json"])) for r in rows]

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def create_conversation(self, team_id: str) -> str:
        conversation_id = str(uuid.uuid4())
        now = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (conversation_id, team_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, team_id, now, now),
            )
        return conversation_id

    def get_conversation_team_id(self, conversation_id: str) -> Optional[str]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT team_id FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
        return row["team_id"] if row else None

    def get_conversation_process_id(self, conversation_id: str) -> Optional[str]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT process_id FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
        return row["process_id"] if row else None

    def set_conversation_process(self, conversation_id: str, process_id: str) -> None:
        now = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET process_id = ?, updated_at = ? WHERE conversation_id = ?",
                (process_id, now, conversation_id),
            )

    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        now = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO conv_messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (now, conversation_id),
            )

    def get_messages(self, conversation_id: str) -> list[ConversationMessage]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, timestamp FROM conv_messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [
            ConversationMessage(role=r["role"], content=r["content"], timestamp=r["timestamp"])
            for r in rows
        ]

    def list_conversations(self, team_id: str) -> list[dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, (SELECT COUNT(*) FROM conv_messages m WHERE m.conversation_id = c.conversation_id) AS message_count
                FROM conversations c WHERE c.team_id = ? ORDER BY c.created_at DESC
                """,
                (team_id,),
            ).fetchall()
        return [
            {
                "conversation_id": r["conversation_id"],
                "team_id": r["team_id"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "message_count": r["message_count"],
            }
            for r in rows
        ]
