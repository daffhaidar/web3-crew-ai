"""
Advanced Headless Scraper Tool for CrewAI

This module provides a custom CrewAI tool that uses Playwright's async API to scrape
JavaScript-heavy Web3 websites and extract EVM smart contract addresses.

Error Handling Strategy:
- All errors are caught and converted to formatted strings (no exception propagation)
- Browser resources are cleaned up in finally blocks
- Input validation occurs before browser launch
- Async/sync bridge handles event loop conflicts
"""

import re
import asyncio
from typing import List

try:
    from crewai.tools import BaseTool
except ImportError:
    raise ImportError(
        "crewai package is required. Install it with: pip install crewai"
    )

try:
    from playwright.async_api import async_playwright
except ImportError:
    raise ImportError(
        "playwright package is required. Install it with: pip install playwright && playwright install"
    )


class AdvancedScrapeTool(BaseTool):
    """
    Custom CrewAI tool for scraping Web3 websites and extracting EVM addresses.
    
    Uses Playwright's headless browser to render JavaScript-heavy pages and extract
    smart contract addresses using regex pattern matching.
    """
    
    name: str = "advanced_scrape"
    description: str = """
    Scrapes EVM smart contract addresses from Web3 websites using headless browser automation.
    
    Purpose: Extract smart contract addresses and page content from JavaScript-rendered Web3 sites
    (DEX interfaces, token listing sites, blockchain explorers, etc.).
    
    Input: A single URL string (must start with http:// or https://).
    
    Output: A formatted string with three sections:
    - Addresses Found: List of unique EVM addresses (0x + 40 hex chars) or "None"
    - Page Content: First 500 characters of scraped content
    - Status: "Success" or "Error - [reason]"
    """
    
    def _extract_evm_addresses(self, text: str) -> List[str]:
        """
        Extract and deduplicate EVM addresses from text content.
        
        Args:
            text: Page content to search for EVM addresses
            
        Returns:
            List of unique EVM addresses (case-insensitive deduplication,
            preserving first occurrence casing)
        """
        # Regex pattern for EVM addresses: 0x followed by 40 hexadecimal characters
        pattern = r'0x[a-fA-F0-9]{40}'
        matches = re.findall(pattern, text)
        
        # Deduplicate using case-insensitive comparison, preserving first occurrence casing
        seen = {}
        unique_addresses = []
        
        for address in matches:
            address_lower = address.lower()
            if address_lower not in seen:
                seen[address_lower] = True
                unique_addresses.append(address)
        
        return unique_addresses
    
    def _format_result(
        self,
        addresses: List[str],
        content: str,
        status: str = "Success"
    ) -> str:
        """
        Format scraping results into structured string output.
        
        Args:
            addresses: List of extracted EVM addresses
            content: Page content (will be truncated to 500 chars)
            status: Status message ("Success" or "Error - [reason]")
            
        Returns:
            Formatted string with three labeled sections separated by double newlines
        """
        # Format addresses section
        if addresses:
            addresses_section = "\n".join(addresses)
        else:
            addresses_section = "None"
        
        # Truncate content to first 500 characters
        content_section = content[:500] if content else ""
        
        # Build formatted output
        result = f"""Addresses Found:
{addresses_section}

Page Content:
{content_section}

Status:
{status}"""
        
        return result
    
    async def _async_scrape(self, url: str) -> str:
        """
        Async implementation of scraping logic using Playwright.
        
        Args:
            url: Target URL to scrape
            
        Returns:
            Formatted result string (never raises exceptions)
        """
        browser = None
        context = None
        
        try:
            # Launch Playwright browser in headless mode
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                
                # Navigate to URL with 30-second timeout, wait for network idle
                try:
                    response = await page.goto(
                        url,
                        timeout=30000,
                        wait_until="networkidle"
                    )
                    
                    # Check for HTTP error status codes
                    if response and response.status >= 400:
                        return self._format_result(
                            [],
                            "",
                            f"Error - HTTP {response.status}"
                        )
                
                except Exception as nav_error:
                    # Handle navigation errors (timeout, DNS, connection refused, etc.)
                    error_str = str(nav_error)
                    if "timeout" in error_str.lower():
                        return self._format_result(
                            [],
                            "",
                            "Error - Page load timeout after 30 seconds"
                        )
                    else:
                        return self._format_result(
                            [],
                            "",
                            f"Error - URL unreachable: {error_str}"
                        )
                
                # Extract fully rendered text content from page body
                try:
                    content = await page.inner_text("body")
                except Exception as extract_error:
                    return self._format_result(
                        [],
                        "",
                        f"Error - Content extraction failed: {str(extract_error)}"
                    )
                
                # Extract EVM addresses from content
                addresses = self._extract_evm_addresses(content)
                
                # Format and return successful result
                return self._format_result(addresses, content, "Success")
        
        except Exception as e:
            # Catch browser launch failures and any other unexpected errors
            error_msg = str(e)
            if "browser" in error_msg.lower() or "launch" in error_msg.lower():
                return self._format_result(
                    [],
                    "",
                    f"Error - Browser launch failed: {error_msg}"
                )
            else:
                return self._format_result(
                    [],
                    "",
                    f"Error - {error_msg}"
                )
        
        finally:
            # Ensure browser resources are cleaned up
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                # Suppress cleanup errors to avoid masking original errors
                pass
    
    def _run(self, url: str) -> str:
        """
        Synchronous entry point for CrewAI tool execution.
        
        Args:
            url: Target URL to scrape (must start with http:// or https://)
            
        Returns:
            Formatted string with three sections:
            - Addresses Found: List of unique EVM addresses (one per line) or "None"
            - Page Content: First 500 characters of scraped content
            - Status: "Success" or "Error - [reason]"
        """
        # Validate URL format
        if not url or not url.strip():
            return self._format_result([], "", "Error - Invalid URL format")
        
        if not url.startswith(("http://", "https://")):
            return self._format_result([], "", "Error - Invalid URL scheme")
        
        # Bridge sync/async execution
        try:
            return asyncio.run(self._async_scrape(url))
        except RuntimeError as e:
            # Handle case where event loop is already running
            if "already running" in str(e).lower():
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(self._async_scrape(url))
            else:
                return self._format_result(
                    [],
                    "",
                    f"Error - Async execution failed: {str(e)}"
                )
