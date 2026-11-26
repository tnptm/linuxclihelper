from __future__ import annotations

import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rich.console import Console

from linuxclihelper.backend import Plan, PlannedCommand
from linuxclihelper.cli import main
from linuxclihelper.executor import execute_plan
from linuxclihelper.history import ExecutedCommand, HistoryStore


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(
            os.environ, {"LINUXCLIHELPER_DB": str(Path(self.directory.name) / "history.db")}
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        console = Console(file=output, width=200, force_terminal=False)
        with patch("linuxclihelper.cli.Console", return_value=console):
            result = main(list(args))
        return result, output.getvalue()

    def test_history_views_use_recent_executions_and_saved_explanations(self) -> None:
        with HistoryStore() as store:
            first = store.create_task("old prompt", "model", "old explanation")
            store.add_command(first, 1, ExecutedCommand("echo old", "", False, 0))
            second = store.create_task("new [prompt]", "model", "new [explanation]")
            store.add_command(second, 1, ExecutedCommand("echo [new]", "", False, 3))

        result, output = self.run_cli("-H", "1")
        self.assertEqual(result, 0)
        self.assertEqual(output, "echo [new]\n")

        result, output = self.run_cli("-Hl", "1")
        self.assertEqual(result, 0)
        self.assertIn("new [prompt]", output)
        self.assertIn("new [explanation]", output)
        self.assertIn("echo [new]", output)
        self.assertNotIn("echo old", output)
        self.assertIn("3", output)

    def test_execution_and_dry_run_record_the_right_history(self) -> None:
        plan = Plan(
            explanation="Explains the task",
            commands=[PlannedCommand("echo approved"), PlannedCommand("echo skipped")],
        )
        console = Console(file=io.StringIO(), width=120)
        with (
            patch("linuxclihelper.executor.Prompt.ask", side_effect=["y", "n"]),
            patch("linuxclihelper.executor.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run,
        ):
            self.assertEqual(execute_plan(plan, "model", console, prompt="my task"), 0)
            self.assertEqual(run.call_count, 1)

        with patch("linuxclihelper.executor.subprocess.run") as run:
            self.assertEqual(execute_plan(plan, "model", console, dry_run=True, prompt="dry task"), 0)
            run.assert_not_called()

        with HistoryStore() as store:
            entries = store.recent_commands()
            self.assertEqual([entry.command for entry in entries], ["echo approved"])
            self.assertEqual(entries[0].summary, "Explains the task")
            self.assertEqual(len(store.recent_recommendations()), 4)

        result, output = self.run_cli("-R", "1")
        self.assertEqual(result, 0)
        self.assertIn("dry task", output)
        self.assertIn("Explains the task", output)

        result, output = self.run_cli("-Hl")
        self.assertEqual(result, 0)
        self.assertIn("my task", output)
        self.assertIn("Explains the task", output)
        self.assertNotIn("dry task", output)
        self.assertNotIn("echo skipped", output)

    def test_empty_history_and_invalid_limits(self) -> None:
        for flag in ("-H", "-Hl"):
            result, output = self.run_cli(flag)
            self.assertEqual(result, 0)
            self.assertIn("No executed commands", output)
            result, output = self.run_cli(flag, "0")
            self.assertEqual(result, 2)
            self.assertIn("positive", output)

    def test_existing_database_and_history_without_ollama(self) -> None:
        db = Path(self.directory.name) / "history.db"
        with sqlite3.connect(db) as connection:
            connection.executescript(
                """
                CREATE TABLE tasks (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                    prompt TEXT NOT NULL, model TEXT NOT NULL, summary TEXT NOT NULL);
                CREATE TABLE commands (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL,
                    position INTEGER NOT NULL, executed_at TEXT NOT NULL, command TEXT NOT NULL,
                    description TEXT NOT NULL, requires_root INTEGER NOT NULL, exit_code INTEGER NOT NULL);
                INSERT INTO tasks VALUES (1, '2026-01-01', 'old task', 'model', 'old explanation');
                INSERT INTO commands VALUES (1, 1, 1, '2026-01-01', 'true', '', 0, 0);
                """
            )

        result = subprocess.run(
            [sys.executable, "-m", "linuxclihelper", "-Hl"],
            env={**os.environ, "OLLAMA_HOST": "http://127.0.0.1:1"},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("old task", result.stdout)
        self.assertIn("old explanation", result.stdout)

    def test_real_command_exit_is_saved(self) -> None:
        plan = Plan(explanation="A command that fails", commands=[PlannedCommand("false")])
        console = Console(file=io.StringIO(), width=120)
        with patch("linuxclihelper.executor.Prompt.ask", return_value="y"):
            self.assertEqual(execute_plan(plan, "model", console, prompt="failure"), 1)
        with HistoryStore() as store:
            entry = store.recent_commands()[0]
            self.assertEqual((entry.command, entry.exit_code), ("false", 1))


if __name__ == "__main__":
    unittest.main()
