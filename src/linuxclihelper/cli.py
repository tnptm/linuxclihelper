from __future__ import annotations

import argparse
import sys
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version

import ollama
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from .backend import PlannerError, generate_plan, list_models, resolve_model_name
from .executor import execute_plan, is_root
from .history import DEFAULT_HISTORY_LIMIT, HistoryStore

QUIT_WORDS = {"q", "quit", "exit", ":q", ":quit"}


def _app_version() -> str:
    try:
        return version("linuxclihelper")
    except PackageNotFoundError:
        return "0.1.0"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linuxclihelper",
        description="Describe a Linux task in plain English and get ready-to-run shell commands.",
    )
    parser.add_argument(
        "task",
        nargs="*",
        help="the task to perform; if omitted, an interactive prompt is shown",
    )
    parser.add_argument(
        "-m",
        "--model",
        help="Ollama model to use (default: autodetect, or $LINUXCLIHELPER_MODEL)",
    )
    parser.add_argument(
        "--host",
        help="Ollama server URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "-l",
        "--list-models",
        action="store_true",
        help="list available Ollama models and their sizes",
    )
    parser.add_argument(
        "-H",
        "--history",
        nargs="?",
        const=DEFAULT_HISTORY_LIMIT,
        type=int,
        metavar="N",
        help="list the last N executed commands (default 10)",
    )
    parser.add_argument(
        "-R",
        "--recommendations",
        nargs="?",
        const=DEFAULT_HISTORY_LIMIT,
        type=int,
        metavar="N",
        help="list the last N AI answers (default 10)",
    )
    parser.add_argument(
        "-Hl",
        "--history-long",
        nargs="?",
        const=DEFAULT_HISTORY_LIMIT,
        type=int,
        metavar="N",
        help="list the last N executed commands with their explanations (default 10)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="show the proposed commands without executing them",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_app_version()}")
    return parser


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1000
    return f"{int(size)} B"


def _format_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _handle_list_models(args: argparse.Namespace, console: Console) -> int:
    try:
        models = list_models(host=args.host)
    except ollama.ResponseError as exc:
        console.print(f"[bold red]Ollama error:[/] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - surface a friendly backend error
        console.print(f"[bold red]Could not talk to Ollama:[/] {exc}")
        console.print(
            "[dim]Make sure the Ollama server is running (`ollama serve`) and reachable"
            + (f" at {args.host}" if args.host else " at http://localhost:11434")
            + ".[/]"
        )
        return 1

    if not models:
        console.print("[yellow]No models installed. Pull one with `ollama pull <model>`.[/]")
        return 1

    table = Table(
        title="Available Ollama models",
        box=box.SIMPLE,
        header_style="bold cyan",
    )
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Size", justify="right")
    for name, size in models:
        table.add_row(name, _human_size(size))
    console.print(table)
    return 0


def _print_banner(console: Console, args: argparse.Namespace) -> None:
    mode = "root" if is_root() else "user"
    model = args.model or "auto"
    console.print(
        Panel(
            "Describe what you want to do in plain English. I will explain it, "
            "show you the exact commands, and run them only after you say yes.\n\n"
            f"[dim]model: {model}   mode: {mode}   type 'exit' to quit[/]",
            title="[bold cyan]linuxclihelper[/]",
            border_style="cyan",
            padding=(0, 1),
        )
    )


def _handle_history(limit: int, console: Console, *, long: bool = False) -> int:
    if limit <= 0:
        console.print("[bold red]The history limit must be a positive number.[/]")
        return 2

    try:
        with HistoryStore() as store:
            entries = store.recent_commands(limit)
    except Exception as exc:  # noqa: BLE001 - surface a friendly history error
        console.print(f"[bold red]Could not read the history database: {exc}[/]")
        return 1

    if not entries:
        console.print("[yellow]No executed commands in history yet.[/]")
        return 0

    if not long:
        for entry in entries:
            console.print(entry.command, markup=False, highlight=False, soft_wrap=True)
        return 0

    table = Table(title=f"Last {len(entries)} executed command(s)", box=box.SIMPLE)
    table.add_column("When", no_wrap=True)
    table.add_column("Prompt", overflow="fold")
    table.add_column("Command", overflow="fold")
    table.add_column("Explanation", overflow="fold")
    table.add_column("Exit", justify="right")
    for entry in entries:
        table.add_row(
            _format_timestamp(entry.executed_at),
            Text(entry.prompt),
            Text(entry.command),
            Text(entry.summary),
            str(entry.exit_code),
        )
    console.print(table)
    return 0


def _handle_recommendations(args: argparse.Namespace, console: Console) -> int:
    limit = args.recommendations
    if limit is None:
        limit = DEFAULT_HISTORY_LIMIT
    if limit <= 0:
        console.print("[bold red]The history limit must be a positive number.[/]")
        return 2

    try:
        with HistoryStore() as store:
            recommendations = store.recent_recommendations(limit)
    except Exception as exc:  # noqa: BLE001 - surface a friendly history error
        console.print(f"[bold red]Could not read the history database: {exc}[/]")
        return 1

    if not recommendations:
        console.print("[yellow]No recommendations in history yet.[/]")
        return 0

    table = Table(
        title=f"Last {len(recommendations)} AI answer(s) - 'What it does?'",
        box=box.SIMPLE,
        header_style="bold cyan",
    )
    table.add_column("When", no_wrap=True)
    table.add_column("Prompt", overflow="fold", max_width=34)
    table.add_column("Model", overflow="fold")
    table.add_column("Recommendation", style="green", overflow="fold")
    for entry in recommendations:
        table.add_row(
            _format_timestamp(entry.created_at),
            Text(entry.prompt),
            Text(entry.model),
            Text(entry.explanation),
        )
    console.print(table)
    return 0


def _handle_task(task: str, args: argparse.Namespace, console: Console) -> int:
    console.print(f"\n[bold cyan]Task:[/] {task}")
    try:
        selected_model = resolve_model_name(args.model, args.host)
        with console.status(
            f"[cyan]Model {selected_model} is thinking about the commands...[/]",
            spinner="dots",
        ):
            plan, model = generate_plan(task, model=selected_model, host=args.host)
    except PlannerError as exc:
        console.print(f"[bold red]The model returned an unusable answer:[/] {exc}")
        return 1
    except ollama.ResponseError as exc:
        console.print(f"[bold red]Ollama error:[/] {exc}")
        if "not found" in str(exc).lower():
            console.print("[dim]Tip: pull a model first, e.g. `ollama pull qwen3.5`.[/]")
        return 1
    except Exception as exc:  # noqa: BLE001 - surface a friendly message for any backend failure
        console.print(f"[bold red]Could not talk to Ollama:[/] {exc}")
        console.print(
            "[dim]Make sure the Ollama server is running (`ollama serve`) and reachable"
            + (f" at {args.host}" if args.host else " at http://localhost:11434")
            + ".[/]"
        )
        return 1

    return execute_plan(
        plan,
        model,
        console,
        dry_run=args.dry_run,
        prompt=task,
    )


def _interactive(args: argparse.Namespace, console: Console) -> int:
    _print_banner(console, args)
    while True:
        try:
            task = Prompt.ask("\n[bold cyan]What would you like to do?[/]")
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0

        task = task.strip()
        if not task:
            continue
        if task.lower() in QUIT_WORDS:
            return 0

        _handle_task(task, args, console)
        console.print()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    console = Console()

    if args.list_models:
        return _handle_list_models(args, console)

    if args.history is not None:
        return _handle_history(args.history, console)

    if args.recommendations is not None:
        return _handle_recommendations(args, console)

    if args.history_long is not None:
        return _handle_history(args.history_long, console, long=True)

    task = " ".join(args.task).strip()
    if task:
        return _handle_task(task, args, console)

    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            return _handle_task(piped, args, console)
        console.print("[bold red]No task provided.[/]")
        return 1

    return _interactive(args, console)
