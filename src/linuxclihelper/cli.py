from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version

import ollama
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from .backend import PlannerError, generate_plan
from .executor import execute_plan, is_root

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
        "-n",
        "--dry-run",
        action="store_true",
        help="show the proposed commands without executing them",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_app_version()}")
    return parser


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


def _handle_task(task: str, args: argparse.Namespace, console: Console) -> int:
    console.print(f"\n[bold cyan]Task:[/] {task}")
    try:
        with console.status("[cyan]Thinking about the commands...[/]", spinner="dots"):
            plan, model = generate_plan(task, model=args.model, host=args.host)
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

    return execute_plan(plan, model, console, dry_run=args.dry_run)


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
