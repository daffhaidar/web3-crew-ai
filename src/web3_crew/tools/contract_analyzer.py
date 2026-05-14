"""Static analysis tool for Solidity smart contract source code.

Scans for dangerous patterns commonly found in malicious token contracts.
"""

import json
import re

from crewai.tools import BaseTool

DANGEROUS_PATTERNS: list[dict[str, str]] = [
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


class ContractAnalyzerTool(BaseTool):
    name: str = "contract_analyzer"
    description: str = (
        "Performs static analysis on Solidity source code to detect dangerous patterns "
        "such as hidden mints, blacklists, fee manipulation, proxy patterns, and selfdestruct. "
        "Input: the full Solidity source code as a string."
    )

    def _run(self, source_code: str) -> str:
        if not source_code or source_code == "Contract source code not verified":
            return json.dumps({
                "analyzed": False,
                "reason": "No verified source code available",
                "findings": [],
                "pattern_count": 0,
            })

        findings: list[dict[str, str]] = []
        for pattern_def in DANGEROUS_PATTERNS:
            matches = re.findall(pattern_def["pattern"], source_code)
            if matches:
                findings.append({
                    "name": pattern_def["name"],
                    "severity": pattern_def["severity"],
                    "description": pattern_def["description"],
                    "occurrences": len(matches),
                })

        # Check for onlyOwner modifier usage
        owner_functions = re.findall(r"function\s+(\w+)\s*\([^)]*\)\s*[^{]*onlyOwner", source_code)
        if owner_functions:
            findings.append({
                "name": "owner_restricted_functions",
                "severity": "INFO",
                "description": f"Functions restricted to owner: {', '.join(owner_functions[:10])}",
                "occurrences": len(owner_functions),
            })

        return json.dumps({
            "analyzed": True,
            "findings": findings,
            "pattern_count": len(findings),
            "has_critical": any(f["severity"] == "CRITICAL" for f in findings),
            "has_high": any(f["severity"] == "HIGH" for f in findings),
        }, indent=2)
