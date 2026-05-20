#!/usr/bin/env python3
"""
Compliance Skill Audit — runs SOC 2 and GDPR skills via GitHub Models API
and writes the full audit report into the PR description.
"""

import os
import re
import sys
import subprocess
from pathlib import Path
import requests
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────
GITHUB_MODELS_URL = "https://models.inference.ai.azure.com"
MODEL             = "gpt-4o"
MAX_TOKENS        = 3500          # per skill — keeps PR description under GitHub's 65k limit
AUDIT_OPEN_TAG    = "<!-- compliance-audit-start -->"
AUDIT_CLOSE_TAG   = "<!-- compliance-audit-end -->"

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_changed_files():
    base = os.environ.get("BASE_REF", "main")
    result = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base}", "HEAD"],
        capture_output=True, text=True
    )
    return set(result.stdout.strip().splitlines())


def collect_codebase():
    """Gather all sample-app source files into a single annotated string."""
    changed = get_changed_files()
    extensions = {".js", ".ts", ".sql", ".tf", ".py", ".json", ".yml", ".yaml", ".md"}
    skip_dirs  = {"node_modules", ".git", "dist", "build"}

    sections = []
    for path in sorted(Path("sample-app").rglob("*")):
        if path.is_dir():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix not in extensions and path.name != ".env.example":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        label = f"[CHANGED] {path}" if str(path) in changed else str(path)
        sections.append(f"### {label}\n```\n{text}\n```")

    return "\n\n".join(sections)


def read_skill(name: str) -> str:
    return Path(f"compliance/{name}/SKILL.md").read_text(encoding="utf-8")


def run_skill(skill_content: str, codebase: str, label: str) -> str:
    """Call GitHub Models (GPT-4o) with the skill as system prompt."""
    client = OpenAI(
        base_url=GITHUB_MODELS_URL,
        api_key=os.environ["GH_COPILOT_TOKEN"],
    )

    user_prompt = f"""Run a full compliance audit on the following codebase.

Produce a structured report with:
1. **Executive Summary** — counts of Critical / High / Medium findings and compliant controls
2. **Critical Findings** — file path, line reference, criteria/article, risk, exact remediation
3. **High Findings** — same format
4. **Medium Findings** — same format
5. **Compliant Controls** — what is already correct
6. **Prioritised Remediation Roadmap** — ordered table (Priority | Finding | Effort)

Be specific. Reference actual file names and line content from the codebase below.

---

{codebase}
"""

    print(f"  → Calling GitHub Models ({MODEL}) for {label} audit …")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": skill_content},
            {"role": "user",   "content": user_prompt},
        ],
        max_tokens=MAX_TOKENS,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


# ── PR description update ─────────────────────────────────────────────────────

def get_pr_body(pr_number: str, repo: str, token: str) -> str:
    url     = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return (r.json().get("body") or "").strip()


def update_pr_body(pr_number: str, repo: str, token: str, new_body: str) -> None:
    url     = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    r = requests.patch(url, json={"body": new_body}, headers=headers, timeout=15)
    r.raise_for_status()
    print(f"  → PR description updated (HTTP {r.status_code})")


def build_audit_block(soc2_report: str, gdpr_report: str) -> str:
    return f"""{AUDIT_OPEN_TAG}

---

## 🛡️ Automated Compliance Audit

> **Triggered by**: changes to `sample-app/` · **Skills**: `compliance/soc2-audit` + `compliance/gdpr-audit` · **Model**: GitHub Copilot / GPT-4o

---

<details>
<summary><strong>📋 SOC 2 — Trust Service Criteria Audit</strong> (click to expand)</summary>

{soc2_report}

</details>

---

<details>
<summary><strong>🔐 GDPR — EU Compliance Audit</strong> (click to expand)</summary>

{gdpr_report}

</details>

---

*Auto-generated on every PR · [View skills](../../tree/main/compliance)*

{AUDIT_CLOSE_TAG}"""


def inject_audit_into_body(original: str, audit_block: str) -> str:
    """Replace existing audit block if present; otherwise append."""
    pattern = re.compile(
        re.escape(AUDIT_OPEN_TAG) + r".*?" + re.escape(AUDIT_CLOSE_TAG),
        re.DOTALL,
    )
    if pattern.search(original):
        return pattern.sub(audit_block, original)
    separator = "\n\n" if original else ""
    return original + separator + audit_block


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    pr_number = os.environ["PR_NUMBER"]
    repo      = os.environ["REPO"]
    gh_token  = os.environ["GITHUB_TOKEN"]

    print("Collecting sample-app codebase …")
    codebase = collect_codebase()
    print(f"  → {len(codebase):,} characters across source files")

    print("\nLoading skill definitions …")
    soc2_skill = read_skill("soc2-audit")
    gdpr_skill = read_skill("gdpr-audit")

    print("\nRunning SOC 2 audit …")
    soc2_report = run_skill(soc2_skill, codebase, "SOC 2")

    print("\nRunning GDPR audit …")
    gdpr_report = run_skill(gdpr_skill, codebase, "GDPR")

    print("\nFetching current PR description …")
    original_body = get_pr_body(pr_number, repo, gh_token)

    audit_block = build_audit_block(soc2_report, gdpr_report)
    new_body    = inject_audit_into_body(original_body, audit_block)

    print("Writing audit results to PR description …")
    update_pr_body(pr_number, repo, gh_token, new_body)

    print("\n✅ Done — compliance audit posted to PR description.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n❌ Audit failed: {exc}", file=sys.stderr)
        sys.exit(1)
