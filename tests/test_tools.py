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
