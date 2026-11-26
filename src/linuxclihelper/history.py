from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Self

DB_ENV_VAR = "LINUXCLIHELPER_DB"
DEFAULT_HISTORY_LIMIT = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    prompt TEXT NOT NULL,
    model TEXT NOT NULL,
    summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    executed_at TEXT NOT NULL,
    command TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    requires_root INTEGER NOT NULL DEFAULT 0,
    exit_code INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commands_id ON commands(id DESC);
"""


def default_db_path() -> Path:
    override = os.environ.get(DB_ENV_VAR)
    if override:
        return Path(override).expanduser()

    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "linuxclihelper" / "history.db"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class ExecutedCommand:
    command: str
    description: str
    requires_root: bool
    exit_code: int


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    executed_at: str
    prompt: str
    model: str
    summary: str
    command: str
    description: str
    requires_root: bool
    exit_code: int


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def create_task(self, prompt: str, model: str, summary: str) -> int:
        cursor = self._connection.execute(
            "INSERT INTO tasks (created_at, prompt, model, summary) VALUES (?, ?, ?, ?)",
            (_now(), prompt, model, summary),
        )
        self._connection.commit()
        task_id = cursor.lastrowid
        if task_id is None:
            raise RuntimeError("could not create a history entry")
        return task_id

    def add_command(self, task_id: int, position: int, command: ExecutedCommand) -> None:
        self._connection.execute(
            """
            INSERT INTO commands
                (task_id, position, executed_at, command, description, requires_root, exit_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                position,
                _now(),
                command.command,
                command.description,
                int(command.requires_root),
                command.exit_code,
            ),
        )
        self._connection.commit()

    def recent_commands(self, limit: int = DEFAULT_HISTORY_LIMIT) -> list[HistoryEntry]:
        rows = self._connection.execute(
            """
            SELECT c.id, c.executed_at, c.command, c.description,
                   c.requires_root, c.exit_code,
                   t.prompt, t.model, t.summary
            FROM commands AS c
            JOIN tasks AS t ON t.id = c.task_id
            ORDER BY c.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [
            HistoryEntry(
                id=int(row["id"]),
                executed_at=str(row["executed_at"]),
                prompt=str(row["prompt"]),
                model=str(row["model"]),
                summary=str(row["summary"]),
                command=str(row["command"]),
                description=str(row["description"]),
                requires_root=bool(row["requires_root"]),
                exit_code=int(row["exit_code"]),
            )
            for row in rows
        ]
