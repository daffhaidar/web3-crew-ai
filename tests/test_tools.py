"""Unit tests for custom CrewAI tools."""

import json

from web3_crew.tools.contract_analyzer import ContractAnalyzerTool
from web3_crew.tools.rug_pull_detector import RugPullDetectorTool


class TestContractAnalyzer:
    def setup_method(self):
        self.tool = ContractAnalyzerTool()

    def test_empty_source_code(self):
        result = json.loads(self.tool._run(""))
        assert result["analyzed"] is False
        assert result["findings"] == []

    def test_unverified_source(self):
        result = json.loads(self.tool._run("Contract source code not verified"))
        assert result["analyzed"] is False

    def test_detects_hidden_mint(self):
        source = """
        contract Token {
            function mint(address to, uint256 amount) public onlyOwner {
                _mint(to, amount);
            }
        }
        """
        result = json.loads(self.tool._run(source))
        assert result["analyzed"] is True
        assert result["pattern_count"] > 0
        names = [f["name"] for f in result["findings"]]
        assert "hidden_mint" in names

    def test_detects_blacklist(self):
        source = """
        contract Token {
            mapping(address => bool) public isBlacklisted;
            function blacklist(address user) external onlyOwner {
                isBlacklisted[user] = true;
            }
        }
        """
        result = json.loads(self.tool._run(source))
        names = [f["name"] for f in result["findings"]]
        assert "blacklist" in names

    def test_detects_fee_manipulation(self):
        source = """
        contract Token {
            uint256 public _taxFee = 5;
            function setFee(uint256 fee) external onlyOwner {
                _taxFee = fee;
            }
        }
        """
        result = json.loads(self.tool._run(source))
        names = [f["name"] for f in result["findings"]]
        assert "fee_manipulation" in names

    def test_detects_selfdestruct(self):
        source = """
        contract Token {
            function destroy() external onlyOwner {
                selfdestruct(payable(owner()));
            }
        }
        """
        result = json.loads(self.tool._run(source))
        assert result["has_critical"] is True

    def test_clean_contract(self):
        source = """
        contract SafeToken {
            string public name = "SafeToken";
            mapping(address => uint256) public balanceOf;
            function transfer(address to, uint256 amount) public returns (bool) {
                balanceOf[msg.sender] -= amount;
                balanceOf[to] += amount;
                return true;
            }
        }
        """
        result = json.loads(self.tool._run(source))
        assert result["analyzed"] is True
        assert result["has_critical"] is False
        assert result["has_high"] is False


class TestRugPullDetector:
    def setup_method(self):
        self.tool = RugPullDetectorTool()

    def test_safe_contract(self):
        data = json.dumps({
            "findings": [],
            "liquidity_usd": 500_000,
            "is_verified": True,
        })
        result = json.loads(self.tool._run(data))
        assert result["risk_score"] == 0
        assert result["risk_label"] == "safe"
        assert result["can_execute"] is True

    def test_dangerous_contract(self):
        data = json.dumps({
            "findings": [
                {"name": "selfdestruct", "severity": "CRITICAL", "occurrences": 1},
                {"name": "hidden_mint", "severity": "HIGH", "occurrences": 2},
                {"name": "blacklist", "severity": "HIGH", "occurrences": 1},
            ],
            "liquidity_usd": 500,
            "is_verified": False,
        })
        result = json.loads(self.tool._run(data))
        assert result["risk_score"] >= 70
        assert result["risk_label"] == "dangerous"
        assert result["can_execute"] is False

    def test_low_liquidity_penalty(self):
        data = json.dumps({
            "findings": [],
            "liquidity_usd": 100,
            "is_verified": True,
        })
        result = json.loads(self.tool._run(data))
        assert result["risk_score"] == 20

    def test_unverified_penalty(self):
        data = json.dumps({
            "findings": [],
            "liquidity_usd": 1_000_000,
            "is_verified": False,
        })
        result = json.loads(self.tool._run(data))
        assert result["risk_score"] == 25

    def test_suspicious_range(self):
        data = json.dumps({
            "findings": [
                {"name": "fee_manipulation", "severity": "HIGH", "occurrences": 1},
                {"name": "trading_pause", "severity": "MEDIUM", "occurrences": 1},
                {"name": "max_tx_limit", "severity": "LOW", "occurrences": 1},
            ],
            "liquidity_usd": 30_000,
            "is_verified": True,
        })
        result = json.loads(self.tool._run(data))
        assert 30 <= result["risk_score"] <= 60

    def test_score_clamped_at_100(self):
        findings = [
            {"name": f"issue_{i}", "severity": "CRITICAL", "occurrences": 3}
            for i in range(10)
        ]
        data = json.dumps({
            "findings": findings,
            "liquidity_usd": 0,
            "is_verified": False,
        })
        result = json.loads(self.tool._run(data))
        assert result["risk_score"] == 100


class TestSafeTransactionTool:
    def test_rejects_high_risk(self):
        from web3_crew.tools.safe_transaction import SafeTransactionTool

        tool = SafeTransactionTool()
        tx_request = json.dumps({
            "risk_score": 80,
            "contract_address": "0x0000000000000000000000000000000000000001",
            "function_name": "mint",
            "function_args": [],
        })
        result = json.loads(tool._run(tx_request))
        assert result["status"] == "rejected"
        assert "risk score" in result["reason"].lower() or "Risk score" in result["reason"]

    def test_rejects_missing_key(self):
        from web3_crew.tools.safe_transaction import SafeTransactionTool

        tool = SafeTransactionTool()
        tx_request = json.dumps({
            "risk_score": 10,
            "contract_address": "0x0000000000000000000000000000000000000001",
            "function_name": "mint",
            "function_args": [],
        })
        result = json.loads(tool._run(tx_request))
        # Should either reject for missing key or error out
        assert result["status"] in ("error", "rejected")

    def test_description_mentions_eip1559_and_flashbots(self):
        """Description is the contract surface the LLM sees; gas-war traits stay visible."""
        from web3_crew.tools.safe_transaction import SafeTransactionTool

        tool = SafeTransactionTool()
        desc = tool.description.lower()
        assert "eip-1559" in desc
        assert "flashbots" in desc


class TestEip1559FeeCalc:
    """Strategy-driven EIP-1559 fee math. Pure function — no chain access."""

    def setup_method(self):
        from web3 import Web3
        self.Web3 = Web3
        # 30 gwei base fee, 2 gwei suggested priority — a calm-mainnet-ish baseline.
        self.base = Web3.to_wei(30, "gwei")
        self.priority = Web3.to_wei(2, "gwei")

    def test_slow_uses_1x_multiplier(self):
        from web3_crew.tools.safe_transaction import compute_eip1559_fees

        _, priority = compute_eip1559_fees(self.base, self.priority, "slow", 100)
        assert priority == self.priority  # 1.0x

    def test_standard_uses_1_5x_multiplier(self):
        from web3_crew.tools.safe_transaction import compute_eip1559_fees

        _, priority = compute_eip1559_fees(self.base, self.priority, "standard", 100)
        assert priority == int(self.priority * 1.5)

    def test_fast_uses_2x_multiplier(self):
        from web3_crew.tools.safe_transaction import compute_eip1559_fees

        _, priority = compute_eip1559_fees(self.base, self.priority, "fast", 100)
        assert priority == self.priority * 2

    def test_aggressive_uses_3x_multiplier(self):
        from web3_crew.tools.safe_transaction import compute_eip1559_fees

        _, priority = compute_eip1559_fees(self.base, self.priority, "aggressive", 100)
        assert priority == self.priority * 3

    def test_unknown_strategy_falls_back_to_fast(self):
        from web3_crew.tools.safe_transaction import compute_eip1559_fees

        _, priority = compute_eip1559_fees(self.base, self.priority, "ludicrous", 100)
        assert priority == self.priority * 2  # 'fast' is the safe default

    def test_priority_fee_respects_hard_cap(self):
        """If the strategy multiplier blows past the cap, the cap wins."""
        from web3_crew.tools.safe_transaction import compute_eip1559_fees

        # 10 gwei suggested * 3x aggressive = 30 gwei; cap at 5 gwei should clamp it.
        _, priority = compute_eip1559_fees(
            base_fee_wei=self.base,
            suggested_priority_wei=self.Web3.to_wei(10, "gwei"),
            strategy="aggressive",
            max_priority_fee_gwei=5,
        )
        assert priority == self.Web3.to_wei(5, "gwei")

    def test_max_fee_formula(self):
        """maxFeePerGas = 2 * base_fee + priority_fee."""
        from web3_crew.tools.safe_transaction import compute_eip1559_fees

        max_fee, priority = compute_eip1559_fees(self.base, self.priority, "fast", 100)
        assert max_fee == self.base * 2 + priority


class TestPrivateKeyScrubbing:
    """Defensive scrub: if the configured PK ever surfaces in an error, hide it."""

    def test_scrubs_when_pk_present(self, monkeypatch):
        from web3_crew.config import settings
        from web3_crew.tools.safe_transaction import _scrub_private_key

        fake_pk = "0xdeadbeef" + "00" * 30  # 0x + 64 hex chars
        monkeypatch.setattr(settings, "wallet_private_key", fake_pk)
        msg = f"signer blew up at {fake_pk} during build_transaction"
        scrubbed = _scrub_private_key(msg)
        assert fake_pk not in scrubbed
        assert "[REDACTED]" in scrubbed

    def test_noop_when_pk_absent(self, monkeypatch):
        from web3_crew.config import settings
        from web3_crew.tools.safe_transaction import _scrub_private_key

        monkeypatch.setattr(settings, "wallet_private_key", "0x" + "ab" * 32)
        msg = "RPC timeout after 30s"
        assert _scrub_private_key(msg) == msg

    def test_noop_when_pk_empty(self, monkeypatch):
        """Empty PK setting must not turn arbitrary substrings into [REDACTED]."""
        from web3_crew.config import settings
        from web3_crew.tools.safe_transaction import _scrub_private_key

        monkeypatch.setattr(settings, "wallet_private_key", "")
        msg = "estimate_gas reverted: insufficient funds"
        assert _scrub_private_key(msg) == msg


class TestFlashbotsRouting:
    """Submission client selection: primary RPC vs Flashbots Protect."""

    def test_returns_same_client_when_flashbots_unset(self, monkeypatch):
        from web3 import Web3

        from web3_crew.config import settings
        from web3_crew.tools.safe_transaction import _build_submission_client

        monkeypatch.setattr(settings, "flashbots_rpc_url", "")
        default = Web3(Web3.HTTPProvider("https://example.invalid"))
        assert _build_submission_client(default) is default

    def test_returns_new_client_when_flashbots_set(self, monkeypatch):
        from web3 import Web3

        from web3_crew.config import settings
        from web3_crew.tools.safe_transaction import _build_submission_client

        monkeypatch.setattr(settings, "flashbots_rpc_url", "https://rpc.flashbots.net")
        default = Web3(Web3.HTTPProvider("https://example.invalid"))
        submitter = _build_submission_client(default)
        assert submitter is not default
        # Submission client points at Flashbots, not the user's primary RPC.
        assert "flashbots.net" in submitter.provider.endpoint_uri


class TestWorstCaseCost:
    """gas_limit * max_fee_per_gas — the upper bound the wallet might pay."""

    def test_formula(self):
        from web3_crew.tools.safe_transaction import estimate_worst_case_cost_wei

        # 300k gas at 100 gwei = 0.03 ETH worst case
        cost = estimate_worst_case_cost_wei(300_000, 100 * 10**9)
        assert cost == 300_000 * 100 * 10**9


class TestExplorerUrl:
    """Block-explorer link for the configured chain."""

    def test_mainnet(self):
        from web3_crew.tools.safe_transaction import explorer_tx_url

        url = explorer_tx_url("0x" + "ab" * 32, chain_id=1)
        assert url == "https://etherscan.io/tx/0x" + "ab" * 32

    def test_polygon(self):
        from web3_crew.tools.safe_transaction import explorer_tx_url

        url = explorer_tx_url("0x" + "cd" * 32, chain_id=137)
        assert "polygonscan.com" in url

    def test_unknown_chain_falls_back_to_etherscan(self):
        from web3_crew.tools.safe_transaction import explorer_tx_url

        url = explorer_tx_url("0x" + "ef" * 32, chain_id=99999)
        assert "etherscan.io" in url

    def test_prepends_0x_when_missing(self):
        from web3_crew.tools.safe_transaction import explorer_tx_url

        url = explorer_tx_url("ab" * 32, chain_id=1)
        assert "/tx/0x" + "ab" * 32 in url


class TestTerminalResponse:
    """Mined-tx response builder — must distinguish success from reverted."""

    def _build_receipt(self, status: int):
        # Minimal receipt shape — what the helper actually reads.
        return {
            "transactionHash": bytes.fromhex("ab" * 32),
            "blockNumber": 123_456,
            "gasUsed": 90_000,
            "effectiveGasPrice": 50 * 10**9,
            "status": status,
        }

    def test_status_1_returns_success(self):
        from web3_crew.tools.safe_transaction import _terminal_response

        result = json.loads(_terminal_response(
            receipt=self._build_receipt(status=1),
            function_name="mint",
            max_fee=205 * 10**9,
            priority_fee=5 * 10**9,
            attempts_used=1,
            fee_mode="eip1559",
        ))
        assert result["status"] == "success"
        assert result["action"] == "mint"
        assert result["tx_hash"] == "ab" * 32
        assert result["block_number"] == 123_456
        assert result["explorer_url"].endswith("/tx/0x" + "ab" * 32)

    def test_status_0_returns_reverted(self):
        """The exact foot-gun this PR exists to close: don't lie about success."""
        from web3_crew.tools.safe_transaction import _terminal_response

        result = json.loads(_terminal_response(
            receipt=self._build_receipt(status=0),
            function_name="mint",
            max_fee=205 * 10**9,
            priority_fee=5 * 10**9,
            attempts_used=1,
            fee_mode="eip1559",
        ))
        assert result["status"] == "reverted"
        assert result["tx_hash"] == "ab" * 32
        # Gas was spent — the user needs to know that explicitly.
        assert "gas was spent" in result["reason"].lower()
        assert result["explorer_url"].endswith("/tx/0x" + "ab" * 32)

    def test_missing_status_treated_as_success(self):
        """Pre-Byzantium fork receipts lack a status field; treat absent as success."""
        from web3_crew.tools.safe_transaction import _terminal_response

        receipt = self._build_receipt(status=1)
        receipt.pop("status")
        result = json.loads(_terminal_response(
            receipt=receipt,
            function_name="mint",
            max_fee=205 * 10**9,
            priority_fee=5 * 10**9,
            attempts_used=1,
            fee_mode="eip1559",
        ))
        # Absent status -> success path. (We can't tell on these chains; success
        # is the kinder default since they predate the failure-revert era.)
        assert result["status"] == "success"


class TestPendingResponse:
    """Stuck-tx response builder — must surface enough info to recover."""

    def test_with_tx_hash_includes_explorer(self):
        from web3_crew.tools.safe_transaction import _pending_response

        result = json.loads(_pending_response(
            last_tx_hash_hex="0x" + "ab" * 32,
            nonce=42,
            reason="timeout",
            attempts_used=1,
            current_max_fee=205 * 10**9,
            current_priority=5 * 10**9,
        ))
        assert result["status"] == "pending"
        assert result["tx_hash"] == "0x" + "ab" * 32
        assert result["nonce"] == 42
        assert result["explorer_url"].endswith("/tx/0x" + "ab" * 32)
        assert "max_fee_per_gas" in result
        assert "max_priority_fee_per_gas" in result

    def test_without_tx_hash_omits_explorer(self):
        """If we couldn't even submit, there's no hash to link."""
        from web3_crew.tools.safe_transaction import _pending_response

        result = json.loads(_pending_response(
            last_tx_hash_hex=None,
            nonce=42,
            reason="budget exceeded on initial bump",
            attempts_used=0,
            current_max_fee=205 * 10**9,
            current_priority=5 * 10**9,
        ))
        assert result["status"] == "pending"
        assert "tx_hash" not in result
        assert "explorer_url" not in result
        assert result["nonce"] == 42


class TestSafeTransactionToolDescriptionDefensive:
    """The tool description is the contract surface the LLM sees."""

    def test_mentions_new_outcome_types(self):
        from web3_crew.tools.safe_transaction import SafeTransactionTool

        desc = SafeTransactionTool().description.lower()
        assert "reverted" in desc
        assert "pending" in desc
        assert "rejected" in desc
        assert "budget" in desc
