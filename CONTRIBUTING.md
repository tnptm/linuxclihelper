# Contributing

Everything is reviewed in pull requests. There are no issue comments, no
"review me" commits, and no direct pushes to the default branch. If you have
not opened a PR for your change, it will not be merged.

## How to contribute

1. Fork the repository.
2. Create a branch for the change (e.g. `git checkout -b fix/short-description`).
3. Make the change, then open a pull request.
4. Wait for review. The maintainer is the only reviewer; there is no
   merge-to-head and no self-review requirement.

## What a PR has to contain

A pull request is accepted only if it is self-contained and complete. The
reviewer will reject a PR that needs a second look, so include everything
below before sending it.

- **One behaviour change per PR.** If it fixes a bug and adds a feature, that
  is two PRs.
- **No commit messages like `WIP`, `review`, `please look`, `random` — the
  commit body is shown in the review thread.**
- **The PR description states what changed and why**, in a few sentences.
  The reviewer does not need to open the diff to understand the intent.
- **No secrets.** Never commit `.venv` contents, credentials, or a copied
  `uv.lock` from somewhere else. `.venv` is already ignored; do not `git
  add` it.

## Required verification

Run these and report the result in the PR description:

```bash
uv sync
uv run ruff check src
uv run ruff format --check src
```

Ruff is the only style tool in this project. If you add behaviour that is not
covered by the commands above, add a short line in the PR description saying
what you tested it with (e.g. `uv run linuxclihelper --dry-run "task"`).

## What the reviewer will reject

- **No `git commit --amend` after the PR is opened.** Once a PR exists, the
  history is frozen; fixes go in a follow-up PR.
- **No changes to `README.md`, `USAGE_EXAMPLE.md`, or `AGENTS.md` that are
  not part of the same PR.** If your change alters user-facing behaviour or
  documented behaviour, update the docs in the same PR.
- **No changes to `opencode.json` without a matching `backend.py` change.**
  That file is the local provider config; `backend.py`'s `PREFERRED_MODELS`
  and `DEFAULT_MODEL` are the runtime list. Keep them in sync.
- **No changes to safety behaviour without re-reading the safety invariants in
  `AGENTS.md`** (confirmation gating, `needs_root` as the single wrapping
  decision point, `DANGEROUS_PATTERNS`, `--dry-run` never executing).
- **No changes to `SYSTEM_PROMPT` without a matching `README.md` "Safety"
  section update** if the README mentions model behaviour.
- **No speculative fixes.** If you are unsure whether a rough edge is worth
  fixing, open a PR describing the rough edge and its proposed fix. The
  reviewer decides.

## What the reviewer will accept

- **Small, scoped changes**: a one-line `DANGEROUS_PATTERNS` addition, a
  small `history.py` tweak, a new CLI flag with docs.
- **Backwards-compatible changes**: new flags and options must not break
  existing behaviour silently.
- **Documentation-only PRs** when the code already does the right thing.
- **Refusals documented**: if the reviewer rejects a PR, the PR description
  will say why and what to change. Do not re-push the same PR.

## Merging

The maintainer merges the PR after review. There is no merge queue, no
`Squash and merge` requirement, and no requirement to update the
`AGENTS.md` after merging.

## Rules of conduct

Be concise and specific in review. Comment on the code, not the person.