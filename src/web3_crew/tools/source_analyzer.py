"""Pure-Python static analyzer for Solidity source code.

The regex patterns and scoring logic live here as **pure functions** with
no CrewAI BaseTool wrapping. They are imported by two callers:

* :class:`web3_crew.tools.token_data_fetcher.TokenDataFetcherTool` — runs
  the analysis **inline** while fetching the source from Etherscan, so
  the raw source text never enters the LLM context.
* :class:`web3_crew.tools.contract_analyzer.ContractAnalyzerTool` — the
  legacy BaseTool wrapper, kept for back-compat. It is no longer wired
  into the auditor agent's tool list because the findings already arrive
  pre-computed from the gatherer.

LLM-context discipline
----------------------
Flattened Solidity source code routinely exceeds the 8K token window
of small-context models (e.g. ``cerebras/gpt-oss-120b``, self-hosted
Qwen2). Returning ``source_code`` to the agent at any point overflows
the context and silently truncates mid-/mint. This module's
:func:`analyze_source_code` is the **only** place the raw source is
read; callers receive a short ``findings`` list (each entry is
< 200 chars) plus a one-line ``summary`` string.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict


class PatternDef(TypedDict):
    name: str
    pattern: str
    severity: str
    description: str


class Finding(TypedDict):
    name: str
    severity: str
    description: str
    occurrences: int


# Severity rank used by ``analyze_source_code`` to compute the summary
# headline and ``has_critical`` / ``has_high`` flags. Higher = more
# dangerous. Matches the weights in :mod:`rug_pull_detector` 1:1 so the
# downstream risk score stays consistent.
SEVERITY_RANK: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
}


# Regex patterns covering the most common rug-pull / honeypot shapes in
# malicious ERC-20 / ERC-721 contracts. The list is intentionally short
# and high-signal: each pattern triggers a finding the auditor LLM can
# reason about, but the LLM never needs to see the source text itself.
DANGEROUS_PATTERNS: list[PatternDef] = [
    {
        "name": "hidden_mint",
        "pattern": r"function\s+\w*[Mm]int\w*\s*\(",
        "severity": "HIGH",
        "description": "Mint function detected — owner could inflate supply",
    },
    {
        "name": "blacklist",
        "pattern": r"(blacklist|isBlacklisted|_blacklist|blocked)\s*[\[\(]",
        "severity": "HIGH",
        "description": "Blacklist mechanism — can prevent holders from selling",
    },
    {
        "name": "trading_pause",
        "pattern": r"(tradingEnabled|tradingActive|canTrade|paused)\s*[=;]",
        "severity": "MEDIUM",
        "description": "Trading toggle — owner can halt all trading",
    },
    {
        "name": "fee_manipulation",
        "pattern": r"(setFee|setTax|_taxFee|_liquidityFee|updateFee)\s*[\(\{]",
        "severity": "HIGH",
        "description": "Dynamic fee setter — owner can set arbitrarily high fees (honeypot)",
    },
    {
        "name": "max_tx_limit",
        "pattern": r"(maxTxAmount|_maxTxAmount|maxTransactionAmount)",
        "severity": "LOW",
        "description": "Max transaction limit — can restrict selling large amounts",
    },
    {
        "name": "proxy_pattern",
        "pattern": r"(delegatecall|upgradeTo|implementation\(\))",
        "severity": "HIGH",
        "description": "Proxy/upgradeable pattern — logic can be swapped without notice",
    },
    {
        "name": "selfdestruct",
        "pattern": r"selfdestruct\s*\(",
        "severity": "CRITICAL",
        "description": "Selfdestruct — contract can be destroyed, locking all funds",
    },
    {
        "name": "hidden_owner",
        "pattern": r"(renounceOwnership|transferOwnership)\s*\(",
        "severity": "INFO",
        "description": "Ownership transfer/renounce function present",
    },
    {
        "name": "approve_manipulation",
        "pattern": r"_approve\s*\(\s*\w+\s*,\s*\w+\s*,\s*type\(uint256\)\.max",
        "severity": "MEDIUM",
        "description": "Unlimited approval — potential for drainer behavior",
    },
    {
        "name": "external_call",
        "pattern": r"\.call\{value:",
        "severity": "MEDIUM",
        "description": "Low-level external call with value — potential reentrancy vector",
    },
]

# Cap on owner-restricted function names included in the description.
# Keeps the finding string bounded even for contracts with dozens of
# onlyOwner methods.
_MAX_OWNER_FUNCTIONS_IN_DESCRIPTION = 10

# Cap on findings echoed into the headline summary. The full list is
# still returned in ``findings``; only the rendered headline is capped.
_MAX_FINDINGS_IN_SUMMARY = 5

UNVERIFIED_PLACEHOLDER = "Contract source code not verified"


def analyze_source_code(source_code: str | None) -> dict[str, Any]:
    """Run regex-based static analysis against Solidity source.

    Returns a dict with:

    * ``analyzed`` — True if a non-empty, verified source was scanned.
    * ``findings`` — list of :class:`Finding` dicts, one per matched
      pattern. Empty when the source is unverified.
    * ``pattern_count`` — length of ``findings`` (convenience).
    * ``has_critical`` / ``has_high`` — booleans for fast triage.
    * ``summary`` — one-line LLM-safe digest like ``"5 patterns
      flagged. Highest: HIGH (hidden_mint, blacklist, ...)"``.

    The raw ``source_code`` is never echoed back. Callers that need
    to display a snippet must read it themselves; that is by design,
    so this function can be called from anywhere in the agent context
    without ABI/source leak risk.
    """
    if not source_code or source_code.strip() == "" or source_code == UNVERIFIED_PLACEHOLDER:
        return {
            "analyzed": False,
            "reason": "No verified source code available",
            "findings": [],
            "pattern_count": 0,
            "has_critical": False,
            "has_high": False,
            "summary": (
                "Source unavailable (contract unverified on Etherscan). "
                "Treat as elevated risk; rug-pull score will reflect a +25 "
                "unverified penalty downstream."
            ),
        }

    findings: list[Finding] = []
    for pattern_def in DANGEROUS_PATTERNS:
        matches = re.findall(pattern_def["pattern"], source_code)
        if matches:
            findings.append(
                {
                    "name": pattern_def["name"],
                    "severity": pattern_def["severity"],
                    "description": pattern_def["description"],
                    "occurrences": len(matches),
                }
            )

    owner_functions = re.findall(
        r"function\s+(\w+)\s*\([^)]*\)\s*[^{]*onlyOwner",
        source_code,
    )
    if owner_functions:
        names_shown = owner_functions[:_MAX_OWNER_FUNCTIONS_IN_DESCRIPTION]
        findings.append(
            {
                "name": "owner_restricted_functions",
                "severity": "INFO",
                "description": f"Functions restricted to owner: {', '.join(names_shown)}",
                "occurrences": len(owner_functions),
            }
        )

    has_critical = any(f["severity"] == "CRITICAL" for f in findings)
    has_high = any(f["severity"] == "HIGH" for f in findings)

    return {
        "analyzed": True,
        "findings": findings,
        "pattern_count": len(findings),
        "has_critical": has_critical,
        "has_high": has_high,
        "summary": summarize_findings(findings),
    }


def summarize_findings(findings: list[Finding]) -> str:
    """Render a one-line LLM-safe digest of the findings list.

    Examples:

    * ``"0 dangerous patterns matched. Source code passes static checks."``
    * ``"5 patterns flagged. Highest: HIGH. Names: hidden_mint, fee_manipulation, proxy_pattern."``
    * ``"1 pattern flagged. Highest: CRITICAL (selfdestruct). Names: selfdestruct."``
    """
    if not findings:
        return "0 dangerous patterns matched. Source code passes static checks."

    highest_rank = max(SEVERITY_RANK.get(f["severity"], 0) for f in findings)
    highest_label = next(
        (label for label, rank in SEVERITY_RANK.items() if rank == highest_rank),
        "INFO",
    )

    names = [f["name"] for f in findings[:_MAX_FINDINGS_IN_SUMMARY]]
    overflow = len(findings) - _MAX_FINDINGS_IN_SUMMARY
    suffix = "" if overflow <= 0 else f" (+{overflow} more)"
    return (
        f"{len(findings)} pattern{'s' if len(findings) != 1 else ''} flagged. "
        f"Highest: {highest_label}. Names: {', '.join(names)}{suffix}."
    )
