# linuxclihelper — how to work on this project

A small Python CLI (`uv`-packaged) that turns a plain-English Linux task into an
explained, permission-gated sequence of shell commands, using a local Ollama
model.

---

## Project layout

```
src/linuxclihelper/
  __init__.py      package init
  __main__.py      entry point (calls cli.main())
  cli.py           argparse setup, banner, task/history/list-models handlers
  backend.py       Ollama client, model resolution, JSON plan extraction/parsing
  executor.py      renders the plan, gates on confirmation, wraps sudo, executes
  history.py       SQLite store for executed commands (tasks + commands tables)
pyproject.toml     uv build backend, deps: ollama>=0.5, rich>=13.9
opencode.json       opencode provider config (ollama, local)
README.md          user documentation
USAGE_EXAMPLE.md    example CLI transcript
```

There is no test suite. Verification is done by running the CLI end-to-end.

## Environment

- Python **3.15+** (`requires-python = ">=3.15"` in pyproject.toml; `.python-version`)
- [uv](https://docs.astral.sh/uv/) for `uv sync` / `uv run`
- Ollama running locally (`ollama serve`) with at least one model pulled
- `rich` for the terminal UI (panels, syntax highlighting, prompts, tables)

## Commands

```bash
uv sync            # install the project
uv run linuxclihelper            # interactive mode
uv run linuxclihelper "task"     # one-shot
uv run linuxclihelper --dry-run "task"   # show commands, never execute
uv run linuxclihelper --model mistral
uv run linuxclihelper --list-models
uv run linuxclihelper --history [N]
```

## How the pieces fit together

1. `cli.py:_handle_task` calls `backend.generate_plan(task, model, host)`.
2. `backend.resolve_model` → `resolve_model_name`. In that order:
   explicit `--model` flag → `$LINUXCLIHELPER_MODEL` env var → the first
   preferred model installed in Ollama → else the first installed model.
   `DEFAULT_MODEL = "qwen3.5:latest"` is the fallback when nothing is available.
   `--list-models` calls `list_models` (same resolution logic, no fallback).
3. `backend.generate_plan` calls `client.chat(..., format=PLAN_SCHEMA,
   options={"temperature": 0})` with the `SYSTEM_PROMPT` and the user task.
   `PLAN_SCHEMA` is a JSON schema requiring `explanation` (string) and
   `commands` (array of objects with `command`, `description`, `requires_root`).
   If the schema-tagged call fails (`PlannerError` or `ollama.ResponseError`),
   it retries **without** the format (plain chat) and parses that instead.
   Model responses may be wrapped in markdown fences; `_extract_json` strips
   them, then takes the first `{` … last `}`.
4. `executor.display_plan` renders the explanation panel and lists each command
   with its description, a `[admin]` badge when `needs_root`, and a
   `[potentially destructive]` badge plus a warning line when
   `danger_warning` matches.
5. `executor.execute_plan` (unless `--dry-run`) asks `y`/`n`/`a`/`q` for each
   command before running it. `a` runs the rest. `q` stops.
6. Commands that contain `sudo`/`doas`/`su` are re-wrapped as
   `sudo bash -c <quoted>` via `_wrap_with_sudo` (unless already privileged or
   the command already mentions a privilege tool itself).
7. Each executed command is persisted to the SQLite history store; cancelled and
   skipped commands are **not** saved.

## Safety invariants

- Nothing executes without user confirmation. Preserve the per-command prompt.
- Commands needing root are flagged (`requires_root` from the model, or the
  `PRIVILEGE_RE` regex detecting `sudo`/`doas`/`su`). Do not let the model's
  `requires_root` flag alone decide wrapping — `needs_root` is the single
  decision point.
- `DANGEROUS_PATTERNS` in `executor.py` covers: `rm -rf /`-style, `mkfs`,
  `dd of=/dev/...` and `> /dev/...`, `chmod -R 777 /`, fork bomb `:( ){:`,
  `shutdown|reboot|poweroff|halt`, `kill -<pid> 1`. Add new patterns to the
  tuple, in the same style, with a clear reason string.
- `--dry-run` must never execute anything.

## Code conventions

- `from __future__ import annotations` at the top of every module.
- Typed signatures; `list[str] | None` style (PEP 604) is fine.
- Rich is the only view layer — `console.print`, `Panel`, `Syntax`, `Table`,
  `Prompt`, `Confirm`, `console.status`.
- Errors from the model/Ollama layer are translated into friendly `console.print`
  messages with exit code 1; CLI usage errors use exit code 2 (`cli.py`
  `_handle_history` already does this). Keep that mapping.
- The `backend.py` `_parse_plan` path tolerates sloppy model output (str items,
  missing `description`, missing `requires_root`, empty `commands`) — keep that
  leniency, since the goal is to survive a non-deterministic model.
- Keep the `SYSTEM_PROMPT` in `backend.py` as the single source of truth for the
  plan contract. If it changes, update the README "Safety" section if it
  mentions model behaviour.

## Adding a feature

1. Add the core logic in the most natural module (`backend.py` for protocol,
   `executor.py` for execution, `history.py` for persistence, `cli.py` for
   surface).
2. If it changes user-facing behaviour, update `README.md` and/or
   `USAGE_EXAMPLE.md` so the docs stay accurate.
3. If it touches safety, re-read the safety invariants above first.
4. Test with `uv run linuxclihelper "task"` — ideally against a real Ollama
   instance, but at minimum verify argument handling, `--dry-run`, `--history`,
   and `--list-models` error paths.

## Known rough edges (do not silently "fix" without care)

- `--history` with `--model`/`--host` still works, but history is per-install
  and not scoped to the model used.
- The `PlannerError` retry path loses the original response (`_chat` is called
  again). That is intentional (schema-tagged retry is a best-effort fallback),
  but do not add a third retry path without a reason.
- `opencode.json` points at `ollama/mimo-v2.6:latest`; `backend.py`'s
  `PREFERRED_MODELS` and `DEFAULT_MODEL` are the runtime list. Keep them in sync
  when models change.