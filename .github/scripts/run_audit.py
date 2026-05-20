#!/usr/bin/env python3
"""
Compliance Skill Audit — runs SOC 2 and GDPR audits via GitHub Models (GPT-4o)
and writes the full report into the PR description.

GitHub Models has an 8 000-token request cap, so the system prompts are kept
compact while still covering every material control area from the skill files.
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
MAX_TOKENS        = 2000
AUDIT_OPEN_TAG    = "<!-- compliance-audit-start -->"
AUDIT_CLOSE_TAG   = "<!-- compliance-audit-end -->"

# ── Compact audit system prompts ──────────────────────────────────────────────
# These distil the SKILL.md frameworks into AI-ready instructions that stay
# well under GitHub Models' 8 000-token input cap.

SOC2_SYSTEM = """You are a Principal IT Audit Director performing a SOC 2 Trust Service Criteria audit.

Examine the code for compliance issues across these controls:
- CC6 (Logical Access): authentication strength, MFA enforcement, least privilege, service account hygiene, no shared credentials
- CC7 (System Operations): failed-login logging, anomaly detection, incident lifecycle documentation, vulnerability patching SLAs
- CC8 (Change Management): PR review requirements, no self-merge, branch protection, CI gates before deploy
- CC4 (Monitoring): log retention vs audit period, alerting coverage, CloudTrail / audit trail completeness
- C1 (Confidentiality): encryption at rest, encryption in transit (TLS), sensitive data in logs, production data in non-prod
- A1 (Availability): backup retention period, multi-AZ, DR plan existence
- CC6.6 (System Boundaries): no 0.0.0.0/0 on admin ports, database not publicly accessible, VPC segmentation

For every finding state the exact criteria code (e.g. CC6.3), the file and line, the issue, and the exact remediation step.

Respond in this exact markdown structure:

## Executive Summary
| Severity | Count |
|---|---|
| Critical | ? |
| High | ? |
| Medium | ? |
| Compliant Controls | ? |

## Critical Findings
**SOC2-C1** — `CC?.?` — `file:line` — issue — remediation
(repeat for each)

## High Findings
**SOC2-H1** — `CC?.?` — `file:line` — issue — remediation

## Medium Findings
**SOC2-M1** — `CC?.?` — `file:line` — issue — remediation

## Compliant Controls
- bullet list

## Remediation Roadmap
| Priority | Finding | Criteria | Effort |
|---|---|---|---|
| Immediate | SOC2-C1 | CC?.? | Low/Med/High |"""

GDPR_SYSTEM = """You are a Chief Data Protection Officer performing a GDPR compliance audit.

Examine the code for EU GDPR violations across these areas:
- Art.5: lawfulness, data minimization (every field must justify its purpose), storage limitation
- Art.6: documented lawful basis before any personal data processing
- Art.7: consent records must capture who/what/when/how; withdrawal must stop processing and be recorded
- Art.13: privacy notice must match what the code actually does at collection time
- Art.15-22 (Data Subject Rights): access (all tables, not just users), erasure (hard delete cascading, not soft delete), portability (JSON/CSV export), objection, restriction
- Art.17: erasure must cascade to audit_logs, sessions, support_tickets, backups, and third-party services
- Art.32: encryption at rest + in transit; access to personal data must be logged
- Art.33: breach detection capability; 72-hour notification workflow documented
- Art.44: every US/third-country sub-processor needs adequacy decision, SCCs, or DPF certification + DPA
- ePrivacy: non-essential tracking scripts (GA, Hotjar, pixels) must be blocked until explicit consent is given

For every finding state the exact Article, the file and line, the violation, and the exact remediation.

Respond in this exact markdown structure:

## Executive Summary
| Level | Count |
|---|---|
| Critical Risk | ? |
| Non-Compliant | ? |
| Partial | ? |
| Compliant | ? |

## Critical Risk Findings
**GDPR-CR1** — `Art.??` — `file:line` — violation — remediation
(repeat for each)

## Non-Compliant Findings
**GDPR-NC1** — `Art.??` — `file:line` — violation — remediation

## Partial Compliance
**GDPR-P1** — `Art.??` — what works and what is missing

## Compliant Areas
- bullet list

## Remediation Roadmap
| Priority | Finding | Article | Effort |
|---|---|---|---|
| Immediate | GDPR-CR1 | Art.?? | Low/Med/High |"""

# ── Codebase collection ───────────────────────────────────────────────────────

def get_changed_files():
    base = os.environ.get("BASE_REF", "main")
    result = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base}", "HEAD"],
        capture_output=True, text=True,
    )
    return set(result.stdout.strip().splitlines())


def collect_codebase() -> str:
    """Return annotated source file contents for sample-app, changed files first."""
    changed   = get_changed_files()
    skip_dirs = {"node_modules", ".git", "dist", "build", "__pycache__"}
    exts      = {".js", ".ts", ".sql", ".tf", ".py", ".json", ".yml", ".yaml", ".md"}
    sections  = []

    all_paths = sorted(Path("sample-app").rglob("*"))

    # Changed files first so the model sees the PR delta prominently
    ordered = [p for p in all_paths if str(p) in changed] + \
              [p for p in all_paths if str(p) not in changed]

    for path in ordered:
        if path.is_dir():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix not in exts and path.name != ".env.example":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        tag = " ← CHANGED IN THIS PR" if str(path) in changed else ""
        sections.append(f"### {path}{tag}\n```\n{text}\n```")

    return "\n\n".join(sections)


# ── Model call ────────────────────────────────────────────────────────────────

def run_audit(system_prompt: str, codebase: str, label: str) -> str:
    client = OpenAI(
        base_url=GITHUB_MODELS_URL,
        api_key=os.environ["GH_COPILOT_TOKEN"],
    )

    user_msg = (
        "Audit the following codebase. Reference actual file names and line content "
        "from the source below.\n\n"
        + codebase
    )

    print(f"  → Calling {MODEL} for {label} audit …")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ],
        max_tokens=MAX_TOKENS,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


# ── PR update ─────────────────────────────────────────────────────────────────

def get_pr_body(pr_number: str, repo: str, token: str) -> str:
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    r   = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
        timeout=15,
    )
    r.raise_for_status()
    return (r.json().get("body") or "").strip()


def update_pr_body(pr_number: str, repo: str, token: str, body: str) -> None:
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    r   = requests.patch(
        url,
        json={"body": body},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
        timeout=15,
    )
    r.raise_for_status()
    print(f"  → PR description updated (HTTP {r.status_code})")


def build_audit_block(soc2: str, gdpr: str) -> str:
    return f"""{AUDIT_OPEN_TAG}

---

## 🛡️ Automated Compliance Audit

> **Triggered by** changes to `sample-app/` &nbsp;·&nbsp; **Skills**: `compliance/soc2-audit` + `compliance/gdpr-audit` &nbsp;·&nbsp; **Model**: GitHub Copilot / GPT-4o

---

<details>
<summary><strong>📋 SOC 2 — Trust Service Criteria Audit</strong></summary>

{soc2}

</details>

---

<details>
<summary><strong>🔐 GDPR — EU Compliance Audit</strong></summary>

{gdpr}

</details>

---
*Auto-generated on every PR touching `sample-app/` · [View skills](../../tree/main/compliance)*
{AUDIT_CLOSE_TAG}"""


def inject_audit(original: str, block: str) -> str:
    pattern = re.compile(
        re.escape(AUDIT_OPEN_TAG) + r".*?" + re.escape(AUDIT_CLOSE_TAG),
        re.DOTALL,
    )
    if pattern.search(original):
        return pattern.sub(block, original)
    sep = "\n\n" if original else ""
    return original + sep + block


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    pr_number = os.environ["PR_NUMBER"]
    repo      = os.environ["REPO"]
    gh_token  = os.environ["GITHUB_TOKEN"]

    print("Collecting sample-app codebase …")
    codebase = collect_codebase()
    chars    = len(codebase)
    approx_tokens = chars // 4
    print(f"  → {chars:,} chars (~{approx_tokens:,} tokens) across source files")

    print("\nRunning SOC 2 audit …")
    soc2_report = run_audit(SOC2_SYSTEM, codebase, "SOC 2")

    print("\nRunning GDPR audit …")
    gdpr_report = run_audit(GDPR_SYSTEM, codebase, "GDPR")

    print("\nFetching current PR description …")
    original = get_pr_body(pr_number, repo, gh_token)

    new_body = inject_audit(original, build_audit_block(soc2_report, gdpr_report))

    print("Writing audit to PR description …")
    update_pr_body(pr_number, repo, gh_token, new_body)

    print("\n✅ Compliance audit posted to PR description.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n❌ Audit failed: {exc}", file=sys.stderr)
        sys.exit(1)
