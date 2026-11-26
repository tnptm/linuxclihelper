from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import ollama


PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "commands": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "description": {"type": "string"},
                    "requires_root": {"type": "boolean"},
                },
                "required": ["command", "description", "requires_root"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["explanation", "commands"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are linuxclihelper, an expert Linux command-line assistant.
The user describes a task. Work out the shell commands that accomplish it and reply with a single JSON object.

Rules:
- "explanation": 2-4 sentences explaining what the solution does and naming the key tools/commands and what they do (for example, what dd does and what its arguments mean).
- "commands": the ordered list of exact shell commands to run. Use as few commands as reasonably possible. Every command must be directly runnable in bash with no placeholders; pick sensible defaults when the user is unspecific.
- Each command item has:
  - "command": the exact shell command (no leading "$"). Pipes and redirections are allowed.
  - "description": one short line describing what that command does.
  - "requires_root": true if the command needs root privileges (writing system paths, package managers, mounting, swap, services, firewall/network config, etc.). Do not add sudo yourself; just set this flag.
- If several commands are needed, include all of them in the correct order.
- Prefer standard Linux tools and safe defaults. 
- If the user is unspecific, make reasonable assumptions.
- If user asks clearly unsafe commands, refuse to provide them and explain why in the "explanation" field.
- If the task is not related to Linux command-line operations, refuse to provide commands and explain why in the "explanation" field.
- Reply with JSON only. Do not wrap it in markdown code fences and do not add prose outside the JSON object."""


@dataclass
class PlannedCommand:
    command: str
    description: str = ""
    requires_root: bool = False


@dataclass
class Plan:
    explanation: str
    commands: list[PlannedCommand] = field(default_factory=list)


@dataclass
class Recommendation:
    command: str
    description: str = ""
    requires_root: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.command, (tuple, list)):
            self.command = self.command[0]
            self.description = self.command[1] if len(self.command) > 1 else ""
            self.requires_root = bool(self.command[2]) if len(self.command) > 2 else False


@dataclass
class ExecutedCommand:
    command: str
    description: str = ""
    requires_root: bool = False
    exit_code: int = 0


@dataclass
class ExecutedCommand:
    command: str
    description: str = ""
    requires_root: bool = False
    exit_code: int = 0


class PlannerError(RuntimeError):
    pass


def _make_client(host: str | None) -> ollama.Client:
    if host:
        return ollama.Client(host=host)
    return ollama.Client()


def _model_name(entry: Any) -> str | None:
    if isinstance(entry, dict):
        return entry.get("model") or entry.get("name")
    return getattr(entry, "model", None) or getattr(entry, "name", None)


def list_models(host: str | None = None) -> list[tuple[str, int]]:
    client = _make_client(host)
    response = client.list()
    entries = (
        response.get("models", [])
        if isinstance(response, dict)
        else getattr(response, "models", [])
    )

    models: list[tuple[str, int]] = []
    for entry in entries:
        name = _model_name(entry)
        if not name:
            continue
        if isinstance(entry, dict):
            size = entry.get("size", 0)
        else:
            size = getattr(entry, "size", 0)
        models.append((name, int(size or 0)))
    return models


def resolve_model(client: ollama.Client, requested: str | None = None) -> str:
    if requested:
        return requested

    env_model = os.environ.get("LINUXCLIHELPER_MODEL")
    if env_model:
        return env_model

    try:
        response = client.list()
        entries = (
            response.get("models", [])
            if isinstance(response, dict)
            else getattr(response, "models", [])
        )
        available = [name for name in (_model_name(e) for e in entries) if name]
    except Exception:  # noqa: BLE001 - model discovery is best effort
        return get_default_model()

    if not available:
        return get_default_model()

    return available[0]


def _message_content(response: Any) -> str:
    if isinstance(response, dict):
        message = response.get("message") or {}
    else:
        message = getattr(response, "message", None)

    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    return content or ""


def _extract_json(text: str) -> str:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise PlannerError("The model did not return a JSON object.")
    return text[start : end + 1]


def _parse_plan(content: str) -> Plan:
    try:
        data = json.loads(_extract_json(content))
    except json.JSONDecodeError as exc:
        raise PlannerError(f"Could not parse the model response: {exc}") from exc

    if not isinstance(data, dict):
        raise PlannerError("The model response has an unexpected shape.")

    explanation = str(data.get("explanation") or "").strip()
    raw_commands = data.get("commands")
    if not isinstance(raw_commands, list):
        raise PlannerError("The model response did not contain a command list.")

    commands: list[PlannedCommand] = []
    for item in raw_commands:
        if isinstance(item, str):
            command = item.strip()
            if command:
                commands.append(PlannedCommand(command=command))
            continue
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        if not command:
            continue
        commands.append(
            PlannedCommand(
                command=command,
                description=str(item.get("description") or "").strip(),
                requires_root=bool(item.get("requires_root", False)),
            )
        )

    if not commands:
        raise PlannerError("The model did not provide any commands.")

    return Plan(explanation=explanation, commands=commands)


def _chat(client: ollama.Client, model: str, task: str, response_format: Any) -> str:
    response = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ],
        format=response_format,
        options={"temperature": 0},
    )
    return _message_content(response)


def resolve_model_name(requested: str | None = None, host: str | None = None) -> str:
    return resolve_model(_make_client(host), requested)


def generate_plan(
    task: str,
    model: str | None = None,
    host: str | None = None,
) -> tuple[Plan, str]:
    client = _make_client(host)
    selected_model = resolve_model(client, model)

    try:
        content = _chat(client, selected_model, task, PLAN_SCHEMA)
        plan = _parse_plan(content)
    except PlannerError:
        content = _chat(client, selected_model, task, None)
        plan = _parse_plan(content)
    except ollama.ResponseError:
        content = _chat(client, selected_model, task, None)
        plan = _parse_plan(content)

    return plan, selected_model

def get_preferred_models() -> list[str]:
    """Generate list of the preferred models from currently available models.
    Ask from ollama for the list of available models.
    Returns a list of preferred models that are available.
    """
    available_models = [name for name, _ in list_models()]
    return available_models

def get_default_model() -> str:
    """Ask from ollama if there is a currently active model in memory and return it.
    If no active model is found, return the first preferred model that is available.
    If no preferred models are available, tell the user that no suitable model could be found.
    """
    client = _make_client(None)
    response = client.list()
    active_model = None
    if isinstance(response, dict):
        active_model = response.get("active_model")
    else:
        active_model = getattr(response, "active_model", None)
    if active_model:
        return active_model
    preferred_models = get_preferred_models()
    if preferred_models:
        return preferred_models[0]
    raise RuntimeError("No suitable model could be found. You need to install one with 'ollama pull' command.")



""" hard coded preferred models for reference (
    "mimo-2.6:latest",
    "qwen3.5:latest",
    "qwen3.5",
    "qwen2.5:14b",
    "qwen2.5:7b",
    "llama3.2:latest",
    "llama3.1:8b",
    "mistral:latest",
    "mistral",
)"""