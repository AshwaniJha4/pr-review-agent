"""PR review agent: send a git diff to Claude, get structured findings, post them on the PR.

Usage:
  uv run review.py --base origin/main --head HEAD [--rules rules.md] [--dry-run]
  uv run review.py --diff-file change.diff --dry-run

Posting needs GITHUB_TOKEN, GITHUB_REPOSITORY (owner/name) and PR_NUMBER.
Exit code 1 when any finding is "high", so CI can gate on it.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from typing import Literal

import anthropic
from pydantic import BaseModel

MODEL = os.environ.get("REVIEW_MODEL", "claude-opus-5-5")

SYSTEM = """You review pull request diffs as a senior engineer.
Report only real defects: bugs, wrong logic, wrong units, missing error handling, security issues, broken edge cases.
Skip style, naming and formatting unless it hides a bug.
Each diff line is prefixed with its line number in the new file, or '-' for removed lines.
Cite the new-file line number of the added or changed line the finding is about.
Severity: high = will break behaviour or security; medium = likely bug or edge case; low = minor risk.
If the diff has no real defects, return an empty list."""


class Finding(BaseModel):
    file: str
    line: int
    severity: Literal["high", "medium", "low"]
    message: str


class Review(BaseModel):
    findings: list[Finding]


def annotate_diff(diff: str) -> tuple[str, dict[str, set[int]]]:
    """Prefix each line with its new-file line number; return the text and commentable lines per file."""
    out, lines_by_file = [], {}
    path, new_line = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].removeprefix("b/") if raw[4:] != "/dev/null" else None
            if path:
                lines_by_file.setdefault(path, set())
            out.append(raw)
        elif raw.startswith(("--- ", "diff ", "index ")):
            out.append(raw)
        elif m := re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw):
            new_line = int(m.group(1))
            out.append(raw)
        elif raw.startswith("-"):
            out.append(f"    -  {raw}")
        elif raw.startswith(("+", " ")) and path:
            lines_by_file[path].add(new_line)
            out.append(f"{new_line:5d}  {raw}")
            new_line += 1
        else:
            out.append(raw)
    return "\n".join(out), lines_by_file


def keep_valid(findings: list[Finding], lines_by_file: dict[str, set[int]]) -> list[Finding]:
    """Drop findings that point outside the diff: GitHub rejects review comments on those lines."""
    return [f for f in findings if f.line in lines_by_file.get(f.file, set())]


def review(diff: str, rules: str) -> list[Finding]:
    annotated, lines_by_file = annotate_diff(diff)
    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM + (f"\n\nRepository rules:\n{rules}" if rules else ""),
        messages=[{"role": "user", "content": f"Review this diff:\n\n{annotated}"}],
        output_format=Review,
        output_config={"effort": "high"},
        # Server-side fallback: if the model declines, the API reruns on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        sys.exit("Review declined by the model (stop_reason=refusal).")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        sys.exit(f"No usable review output (stop_reason={response.stop_reason}).")
    found = response.parsed_output.findings
    kept = keep_valid(found, lines_by_file)
    if len(kept) < len(found):
        print(f"Dropped {len(found) - len(kept)} finding(s) outside the diff.", file=sys.stderr)
    return kept


def post_review(findings: list[Finding]) -> None:
    repo, pr, token = os.environ["GITHUB_REPOSITORY"], os.environ["PR_NUMBER"], os.environ["GITHUB_TOKEN"]
    body = {
        "event": "COMMENT",
        "body": f"Automated review: {len(findings)} finding(s).",
        "comments": [
            {"path": f.file, "line": f.line, "side": "RIGHT", "body": f"**{f.severity}**: {f.message}"}
            for f in findings
        ],
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls/{pr}/reviews",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(f"Posted review: HTTP {resp.status}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="origin/main")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--diff-file")
    p.add_argument("--rules", default="rules.md")
    p.add_argument("--dry-run", action="store_true", help="print findings, do not post")
    a = p.parse_args()

    if a.diff_file:
        diff = open(a.diff_file).read()
    else:
        diff = subprocess.run(["git", "diff", f"{a.base}...{a.head}"], capture_output=True, text=True, check=True).stdout
    if not diff.strip():
        print("Empty diff, nothing to review.")
        return
    rules = open(a.rules).read() if os.path.exists(a.rules) else ""

    findings = review(diff, rules)
    print(json.dumps([f.model_dump() for f in findings], indent=2))
    if findings and not a.dry_run:
        post_review(findings)
    if any(f.severity == "high" for f in findings):
        sys.exit(1)


if __name__ == "__main__":
    main()
