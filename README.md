# linuxclihelper - AI for Linux Commands

Ask for a Linux task in plain English and get an explanation plus ready-to-run
shell commands. Commands are only executed after you approve them, and commands
that need administrator rights are clearly marked and run through `sudo`.

Uses [uv](https://docs.astral.sh/uv/) for packaging and
[Ollama](https://ollama.com/) as the local AI backend.

## Requirements

- Linux
- Python 3.15+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Ollama](https://ollama.com/download) running locally, with at least one model:

```bash
ollama serve
ollama pull qwen3.5
```

## Install

```bash
uv sync
```

Run it without installing globally:

```bash
uv run linuxclihelper
```

Or install the command into your PATH:

```bash
uv tool install .
```

## Usage

### Interactive mode

```bash
uv run linuxclihelper
```

```
What would you like to do? Create swapfile with dd 2GB
```

The app explains what the commands do, lists every command, warns when root
rights or destructive actions are involved, and then asks before running each
command (`y` = yes, `n` = no, `a` = yes to all remaining, `q` = quit).

### One-shot mode

```bash
uv run linuxclihelper "Create swapfile with dd 2GB"
```

### Show commands without running them

```bash
uv run linuxclihelper --dry-run "Create swapfile with dd 2GB"
```

### Choose a model or server

```bash
uv run linuxclihelper --model mistral
uv run linuxclihelper --host http://localhost:11434
```

The model can also be set with the `LINUXCLIHELPER_MODEL` environment variable.
If no model is given, a model is picked automatically from those installed in
Ollama.

### List available models

```bash
uv run linuxclihelper --list-models
```

This prints every model installed in Ollama together with its size on disk.

### History

Executed commands are saved to a SQLite database. Cancelled and skipped
commands are not saved. `--history` lists the last commands that were actually
run, along with the prompt, solution summary, and exit code:

```bash
uv run linuxclihelper --history [N]
```

The database lives in `$XDG_DATA_HOME/linuxclihelper/history.db` (or
`$LINUXCLIHELPER_DB` if set).

## Options

```
-m, --model MODEL   Ollama model to use
    --host HOST     Ollama server URL (default: http://localhost:11434)
-l, --list-models   List available Ollama models and their sizes
-H, --history [N]   List the last N executed commands (default 10)
-n, --dry-run       Show commands without executing them
    --version       Show the version
```

You can also pipe a task in:

```bash
echo "list the 10 largest files in /var" | uv run linuxclihelper
```

## Safety

The model can propose dangerous commands. Every command is displayed before it
runs and nothing is executed without your confirmation. Commands that require
root are highlighted, and potentially destructive commands (for example `mkfs`,
raw `dd` to a device, or `rm -rf /`) get an extra warning. Review commands
before approving them.
