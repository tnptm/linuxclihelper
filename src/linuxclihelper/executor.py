from __future__ import annotations

import os
import re
import shlex
import subprocess

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax

from .backend import Plan, PlannedCommand
from .history import ExecutedCommand, HistoryStore

PRIVILEGE_RE = re.compile(r"(?:^|[|&;]\s*|\s)(?:sudo|doas|su)\b")

DANGEROUS_PATTERNS = (
    (re.compile(r"rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(?:/|/\*)\s*$"), "removes the root filesystem"),
    (re.compile(r"\bmkfs(?:\.\w+)?\b"), "formats a filesystem, destroying existing data"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/(?:sd|nvme|hd|vd|mmcblk)"), "writes raw data directly to a disk device"),
    (re.compile(r">\s*/dev/(?:sd|nvme|hd|vd|mmcblk)"), "writes raw data directly to a disk device"),
    (re.compile(r"\bchmod\s+-R\s+777\s+/\s*$"), "makes the entire filesystem world-writable"),
    (re.compile(r":\s*\(\s*\)\s*\{.*\|\s*:"), "is a fork bomb"),
    (re.compile(r"\b(?:shutdown|reboot|poweroff|halt)\b"), "will shut down or reboot the machine"),
    (re.compile(r"\bkill\s+(?:-\w+\s+)*1\b"), "kills PID 1, which can crash the system"),
)


def is_root() -> bool:
    getuid = getattr(os, "geteuid", None)
    return bool(getuid and getuid() == 0)


def needs_root(command: PlannedCommand) -> bool:
    return command.requires_root or bool(PRIVILEGE_RE.search(command.command))


def danger_warning(command: str) -> str | None:
    for pattern, reason in DANGEROUS_PATTERNS:
        if pattern.search(command):
            return reason
    return None


def _badges(command: PlannedCommand, root: bool) -> str:
    badges: list[str] = []
    if root:
        badges.append("[bold white on red] admin [/]")
    warning = danger_warning(command.command)
    if warning:
        badges.append("[bold white on dark_orange3] potentially destructive [/]")
    return " ".join(badges)


def display_plan(plan: Plan, model: str, console: Console) -> None:
    console.print()
    if plan.explanation:
        console.print(
            Panel(
                plan.explanation,
                title="[bold cyan]What this does[/]",
                border_style="cyan",
                padding=(0, 1),
            )
        )

    total = len(plan.commands)
    console.print(f"[bold]Proposed commands[/] [dim]({total})[/]")
    for index, command in enumerate(plan.commands, start=1):
        root = needs_root(command)
        badges = _badges(command, root)
        heading = f"[bold cyan]{index}.[/]"
        if command.description:
            heading += f" {command.description}"
        if badges:
            heading += f"  {badges}"
        console.print(heading)
        console.print(
            Syntax(
                command.command,
                "bash",
                theme="monokai",
                background_color="default",
                word_wrap=True,
                padding=(0, 2),
            )
        )
        warning = danger_warning(command.command)
        if warning:
            console.print(f"   [dark_orange3]Warning: this command {warning}.[/]")

    root_commands = [c for c in plan.commands if needs_root(c)]
    if root_commands and not is_root():
        console.print(
            Panel(
                f"{len(root_commands)} of {total} command(s) need administrator rights. "
                "They will be run through sudo, so you may be asked for your password.",
                title="[bold red]Administrator rights required[/]",
                border_style="red",
                padding=(0, 1),
            )
        )


def _wrap_with_sudo(command: str) -> str:
    if is_root() or PRIVILEGE_RE.search(command):
        return command
    return f"sudo bash -c {shlex.quote(command)}"


def execute_plan(
    plan: Plan,
    model: str,
    console: Console,
    dry_run: bool = False,
    prompt: str = "",
) -> int:
    display_plan(plan, model, console)

    if dry_run:
        console.print("\n[dim]Dry run: no commands were executed.[/]")
        return 0

    history: HistoryStore | None = None
    task_id: int | None = None
    history_warned = False

    def record(command: PlannedCommand, position: int, exit_code: int) -> None:
        nonlocal history, task_id, history_warned
        try:
            if history is None:
                history = HistoryStore()
            if task_id is None:
                task_id = history.create_task(prompt, model, plan.explanation)
            history.add_command(
                task_id,
                position,
                ExecutedCommand(
                    command=command.command,
                    description=command.description,
                    requires_root=needs_root(command),
                    exit_code=exit_code,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - history must never break execution
            if not history_warned:
                console.print(f"\n[yellow]Could not save command history: {exc}[/]")
                history_warned = True

    total = len(plan.commands)
    run_all = False

    try:
        for index, command in enumerate(plan.commands, start=1):
            actual = _wrap_with_sudo(command.command) if needs_root(command) else command.command

            if not run_all:
                try:
                    choice = Prompt.ask(
                        f"\nRun command {index}/{total}?",
                        choices=["y", "n", "a", "q"],
                        default="n",
                    )
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Cancelled.[/]")
                    return 130

                if choice == "q":
                    console.print("[dim]Stopped.[/]")
                    return 0
                if choice == "n":
                    console.print(f"[dim]Skipped command {index}.[/]")
                    continue
                if choice == "a":
                    run_all = True

            console.print(f"[dim]$ {actual}[/]")
            try:
                result = subprocess.run(actual, check=False, shell=True, executable="/bin/bash")
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted.[/]")
                record(command, index, 130)
                return 130

            record(command, index, result.returncode)

            if result.returncode != 0:
                console.print(f"[bold red]Command {index} failed with exit code {result.returncode}.[/]")
                if index < total:
                    try:
                        if not Confirm.ask("Continue with the remaining commands?", default=False):
                            return result.returncode
                    except (EOFError, KeyboardInterrupt):
                        return 130
                else:
                    return result.returncode
            else:
                console.print(f"[green]Command {index} finished successfully.[/]")

        return 0
    finally:
        if history is not None:
            history.close()

