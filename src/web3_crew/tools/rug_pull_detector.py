"""Rug-pull risk scoring tool.

Combines static analysis findings with on-chain data to produce
a risk score (0–100) and a risk label.
"""

import json
from typing import Any

from crewai.tools import BaseTool

from web3_crew.config import settings

SEVERITY_WEIGHTS: dict[str, int] = {
    "CRITICAL": 30,
    "HIGH": 15,
    "MEDIUM": 8,
    "LOW": 3,
    "INFO": 0,
}


class RugPullDetectorTool(BaseTool):
    name: str = "rug_pull_detector"
    description: str = (
        "Calculates a rug-pull risk score (0–100) from contract analysis findings "
        "and on-chain data. Input: a JSON string containing 'findings' (list of "
        "analysis findings) and optionally 'liquidity_usd' and 'is_verified'."
    )

    def _run(self, analysis_data: str) -> str:
        data: dict[str, Any] = json.loads(analysis_data)

        findings = data.get("findings", [])
        liquidity_usd = data.get("liquidity_usd", 0)
        is_verified = data.get("is_verified", True)

        # Base score from findings
        risk_score = 0
        for finding in findings:
            severity = finding.get("severity", "INFO")
            weight = SEVERITY_WEIGHTS.get(severity, 0)
            occurrences = min(finding.get("occurrences", 1), 3)  # Cap at 3x
            risk_score += weight * occurrences

        # Penalty: unverified source code
        if not is_verified:
            risk_score += 25

        # Penalty: very low liquidity
        if isinstance(liquidity_usd, (int, float)):
            if liquidity_usd < 1000:
                risk_score += 20
            elif liquidity_usd < 10000:
                risk_score += 10
            elif liquidity_usd < 50000:
                risk_score += 5

        # Clamp 0–100
        risk_score = max(0, min(100, risk_score))

        # Determine label
        if risk_score >= 70:
            risk_label = "dangerous"
        elif risk_score >= settings.max_risk_score:
            risk_label = "suspicious"
        else:
            risk_label = "safe"

        can_execute = risk_score < settings.max_risk_score

        result: dict[str, Any] = {
            "risk_score": risk_score,
            "risk_label": risk_label,
            "can_execute": can_execute,
            "threshold": settings.max_risk_score,
            "findings_summary": [
                {
                    "name": f.get("name", ""),
                    "severity": f.get("severity", ""),
                    "description": f.get("description", ""),
                }
                for f in findings
            ],
            "recommendation": (
                "SAFE_TO_PROCEED" if can_execute
                else "DO_NOT_EXECUTE — risk score exceeds threshold"
            ),
        }

        return json.dumps(result, indent=2)
