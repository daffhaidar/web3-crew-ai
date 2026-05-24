"""Static analysis tool for Solidity smart contract source code.

.. note::

   Most of the implementation has moved to
   :mod:`web3_crew.tools.source_analyzer` as pure functions so the
   regex scan can run **inside** :class:`TokenDataFetcherTool` without
   ever exposing the raw Solidity source to the LLM context. This
   ``BaseTool`` wrapper is kept for back-compat (and direct manual
   invocation) but is no longer wired into the auditor agent's tool
   list — passing a 50 KB source blob through the LLM is exactly what
   the refactor exists to prevent.
"""

import json

from crewai.tools import BaseTool

from web3_crew.tools.source_analyzer import analyze_source_code


class ContractAnalyzerTool(BaseTool):
    name: str = "contract_analyzer"
    description: str = (
        "Legacy. Performs static analysis on Solidity source code to detect "
        "dangerous patterns. DO NOT call from an agent — the source text would "
        "have to pass through the LLM context, which overflows small-context "
        "models. Use TokenDataFetcherTool instead; it runs the same analysis "
        "internally and returns only the findings list. Input: full Solidity "
        "source code as a string."
    )

    def _run(self, source_code: str) -> str:
        return json.dumps(analyze_source_code(source_code), indent=2)
