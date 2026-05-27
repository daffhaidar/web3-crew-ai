"""Entry point for the Web3 Crew AI system.

Usage:
    python -m web3_crew.main <token_address> [--action mint]
"""

import argparse

from web3_crew.crew import build_crew


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Web3 Crew AI — Autonomous token analysis, audit, and execution",
    )
    parser.add_argument(
        "token_address",
        help="EVM contract address of the token to analyze (e.g., 0x...)",
    )
    parser.add_argument(
        "--action",
        default="mint",
        choices=["mint", "approve", "transfer"],
        help="On-chain action to execute if the audit passes (default: mint)",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("  Web3 Crew AI — Autonomous Multi-Agent System")
    print("=" * 70)
    print(f"  Target Token : {args.token_address}")
    print(f"  Action       : {args.action}")
    print("=" * 70)
    print()

    crew = build_crew(
        token_address=args.token_address,
        action=args.action,
    )

    result = crew.kickoff()

    print()
    print("=" * 70)
    print("  FINAL RESULT")
    print("=" * 70)
    print(result)


if __name__ == "__main__":
    main()
