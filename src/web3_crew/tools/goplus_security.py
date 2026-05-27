"""
GoPlus Security Oracle Tool for Token Risk Assessment

This tool integrates with the GoPlus Labs Token Security API to assess
the security risk level of ERC-20 tokens across various blockchain networks.
"""

import requests
from typing import Optional
from crewai.tools import BaseTool


class GoPlusSecurityTool(BaseTool):
    name: str = "goplus_security"
    description: str = """
    Analyzes token security using GoPlus Labs API and returns risk classification.
    
    Input: token_address (required), chain_id (optional, defaults to "1" for Ethereum mainnet)
    
    Output: Risk assessment with classification:
    - [FATAL]: Critical risks detected (honeypot, cannot sell, high tax >50%)
    - [WARNING]: Moderate risks detected (unverified, hidden owner, ownership issues)
    - [SAFE]: No significant risks detected
    
    Supported chain_ids: 1 (Ethereum), 56 (BSC), 137 (Polygon), etc.
    """

    def _run(self, token_address: str, chain_id: str = "1") -> str:
        """
        Execute token security analysis via GoPlus API.
        
        Args:
            token_address: The contract address of the token to analyze
            chain_id: The blockchain network ID (default: "1" for Ethereum)
            
        Returns:
            Formatted risk assessment string with classification and details
        """
        try:
            # Validate input
            if not token_address or not token_address.strip():
                return "[FATAL] Invalid input: token_address cannot be empty"
            
            token_address = token_address.strip().lower()
            
            # Call GoPlus API
            url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
            params = {"contract_addresses": token_address}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Check if API returned valid data
            if "result" not in data or not data["result"]:
                return "[FATAL] API Error: No security data available for this token"
            
            # Extract token data
            token_data = data["result"].get(token_address)
            if not token_data:
                return "[FATAL] API Error: Token not found or invalid address"
            
            # Analyze risks
            fatal_risks = []
            warning_risks = []
            
            # FATAL checks
            is_honeypot = token_data.get("is_honeypot", "0")
            if is_honeypot == "1":
                fatal_risks.append("Honeypot detected - token cannot be sold")
            
            cannot_sell_all = token_data.get("cannot_sell_all", "0")
            if cannot_sell_all == "1":
                fatal_risks.append("Cannot sell all tokens - selling restrictions detected")
            
            sell_tax = token_data.get("sell_tax")
            if sell_tax:
                try:
                    sell_tax_float = float(sell_tax)
                    if sell_tax_float > 0.5:
                        fatal_risks.append(f"Excessive sell tax: {sell_tax_float * 100:.1f}% (>50%)")
                except (ValueError, TypeError):
                    pass
            
            # WARNING checks
            is_open_source = token_data.get("is_open_source", "1")
            if is_open_source == "0":
                warning_risks.append("Contract is not verified/open source")
            
            hidden_owner = token_data.get("hidden_owner", "0")
            if hidden_owner == "1":
                warning_risks.append("Hidden owner detected")
            
            can_take_back_ownership = token_data.get("can_take_back_ownership", "0")
            if can_take_back_ownership == "1":
                warning_risks.append("Owner can take back ownership")
            
            # Format output (Using safe ASCII minus sign instead of bullet points)
            if fatal_risks:
                result = "[FATAL] Critical security risks detected:\n"
                for risk in fatal_risks:
                    result += f"  - {risk}\n"
                if warning_risks:
                    result += "\nAdditional warnings:\n"
                    for risk in warning_risks:
                        result += f"  - {risk}\n"
                return result.strip()
            
            elif warning_risks:
                result = "[WARNING] Security concerns detected:\n"
                for risk in warning_risks:
                    result += f"  - {risk}\n"
                return result.strip()
            
            else:
                return "[SAFE] No significant security risks detected. Token appears safe."
        
        except requests.exceptions.Timeout:
            return "[FATAL] Network Error: API request timed out. Please try again."
        
        except requests.exceptions.ConnectionError:
            return "[FATAL] Network Error: Unable to connect to GoPlus API. Check your internet connection."
        
        except requests.exceptions.HTTPError as e:
            return f"[FATAL] API Error: HTTP {e.response.status_code} - {str(e)}"
        
        except requests.exceptions.RequestException as e:
            return f"[FATAL] Network Error: {str(e)}"
        
        except Exception as e:
            return f"[FATAL] Unexpected Error: {str(e)}"
