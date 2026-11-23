# PR review agent

A GitHub Action that sends each pull request diff to Claude, gets back structured findings (file, line, severity, message), posts them as review comments, and fails the check on high-severity findings. Tests run first; the review runs only when they pass.

## How it works
1. `git diff base...head`, with each line prefixed by its new-file line number so the model cites real lines.
2. Claude (`claude-opus-5-5`, structured output with a Pydantic schema) returns findings. Server-side fallback is on, so a declined request is rerun on a fallback model.
3. Findings pointing outside the diff are dropped, because GitHub rejects comments on those lines.
4. The findings are posted as one PR review. The job exits 1 if any finding is "high".

## Run locally
```bash
uv sync
export ANTHROPIC_API_KEY=...
uv run review.py --diff-file sample.diff --dry-run
uv run --with pytest pytest -q
```

## Set up on GitHub
- Add the `ANTHROPIC_API_KEY` repository secret.
- `GITHUB_TOKEN` is provided by Actions; the workflow grants `pull-requests: write`.

## Results (fill in)
| Version | Catch rate (20 seeded bugs) | False positives (10 clean PRs) | Cost per PR |
|---|---|---|---|
| A: official Claude Code Action | | | |
| B: this script, baseline prompt | | | |
| B: + rules.md and context | | | |

## Next
See `FAILURES.md` for what broke and how it was fixed.
