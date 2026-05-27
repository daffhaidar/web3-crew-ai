from __future__ import annotations

import os
import re
import time
import asyncio
import json
from datetime import datetime, timezone

from crewai.tools import tool
from playwright.async_api import async_playwright
from web3 import Web3
from eth_account import Account

from web3_crew.tools.scheduled_mint import parse_schedule_time

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINT_KEYWORDS = ("mint", "claim", "public mint", "free")

def _load_wallets(count: int = 4) -> list[dict]:
    wallets: list[dict] = []
    for i in range(1, count + 1):
        pk = os.getenv(f"PRIV_KEY_{i}")
        if not pk:
            continue
        acct = Account.from_key(pk)
        wallets.append({
            "index": i,
            "private_key": pk,
            "address": acct.address,
        })
    return wallets

def _seconds_until(target_ts: float) -> float:
    return target_ts - time.time()

# ---------------------------------------------------------------------------
# Core monitoring + minting logic
# ---------------------------------------------------------------------------

async def _monitor_and_mint_async(
    url: str,
    target_time_spec: str = "",
    wallet_count: int = 4,
) -> str:
    wallets = _load_wallets(wallet_count)
    if not wallets:
        return "❌ Gagal boss!! Nggak ada private key yang ketemu di env (PRIV_KEY_1..N)."

    rpc_url = os.getenv("RPC_URL", "https://eth.llamarpc.com")
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    target_ts: float | None = None
    if target_time_spec:
        target_ts = parse_schedule_time(target_time_spec)
        if target_ts is None:
            return "❌ Gagal parse waktu. Gunakan format '+15m', '+2h', atau 'HH:MM UTC'."

    if target_ts is not None:
        while _seconds_until(target_ts) > 0:
            remaining = _seconds_until(target_ts)
            mins, secs = divmod(int(remaining), 60)
            print(f"[FrontendSniper] Belum jamnya boss, standby... sisa {mins}m {secs}s")
            await asyncio.sleep(min(30, remaining))
        print("[FrontendSniper] Waktu tiba! Mulai monitoring aktif…")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"[FrontendSniper] Membuka {url} …")
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        print(f"[FrontendSniper] Menanam DOM Mutation Observer di {url}...")
        await page.evaluate("""(keywords) => {
            return new Promise((resolve) => {
                const checkButtons = () => {
                    const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
                    for (const btn of btns) {
                        const text = (btn.innerText || '').toLowerCase();
                        const match = keywords.some(k => text.includes(k));
                        const isDisabled = btn.disabled || btn.getAttribute('aria-disabled') === 'true' || btn.classList.contains('disabled');
                        if (match && !isDisabled) return true;
                    }
                    return false;
                };
                if (checkButtons()) return resolve(true);
                const observer = new MutationObserver(() => {
                    if (checkButtons()) {
                        observer.disconnect();
                        resolve(true);
                    }
                });
                observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'class', 'aria-disabled'] });
            });
        }""", _MINT_KEYWORDS)
        
        print("[FrontendSniper] BINGO! Mutasi DOM terdeteksi, tombol aktif!")
        valid_buttons = []
        for keyword in _MINT_KEYWORDS:
            loc = page.get_by_role("button", name=re.compile(keyword, re.IGNORECASE))
            count = await loc.count()
            for i in range(count):
                btn = loc.nth(i)
                if not await btn.is_disabled():
                    valid_buttons.append(btn)

        tx_hashes: list[str] = []
        failed_count = 0
        _capture_exposed = False

        async def _click_mint_for_wallet(w: dict) -> str | None:
            nonlocal _capture_exposed
            captured: list[str] = []

            async def _capture_tx(payload: str):
                captured.append(payload)

            if _capture_exposed:
                try:
                    page.remove_listener("captureTx", lambda _: None)
                except Exception:
                    pass
                _capture_exposed = False

            await page.expose_function("captureTx", _capture_tx)
            _capture_exposed = True

            address = w["address"]
            
            js_injection = f"""
                window.ethereum = {{
                    isMetaMask: true,
                    request: async function({{ method, params }}) {{
                        if (method === 'eth_requestAccounts' || method === 'eth_accounts') {{
                            return ['{address}'];
                        }}
                        if (method === 'eth_chainId') {{
                            return '0x1';
                        }}
                        if (method === 'eth_sendTransaction') {{
                            window.captureTx(JSON.stringify(params[0]));
                            return '0x' + '0'.repeat(64);
                        }}
                        return null;
                    }}
                }};
            """
            
            await page.add_init_script(js_injection)
            await page.evaluate(f"(() => {{ {js_injection} }})()")

            tx_data = None
            for idx, btn in enumerate(valid_buttons):
                captured.clear()
                try:
                    btn_text = await btn.inner_text()
                    print(f"[FrontendSniper] Wallet {w['index']} ngeklik tombol '{btn_text.strip()}'...")
                    await btn.click(timeout=5000)
                    await asyncio.sleep(2.5)
                    
                    if captured:
                        tx_data = json.loads(captured[0])
                        print(f"[FrontendSniper] -> Payload tertangkap dari tombol '{btn_text.strip()}'!")
                        break
                    else:
                        print(f"[FrontendSniper] -> Tombol '{btn_text.strip()}' zonk (gak ada payload). Lanjut...")
                except Exception as e:
                    print(f"[FrontendSniper] -> Gagal ngeklik tombol #{idx+1}: {e}")

            if not tx_data:
                print(f"[FrontendSniper] Wallet {w['index']}: Semua tombol diklik, tapi web gak ngirim payload sama sekali.")
                return None

            try:
                nonce = w3.eth.get_transaction_count(address)
                value_hex = tx_data.get("value", "0x0")
                value_int = int(value_hex, 16) if value_hex else 0

                tx = {
                    "from": address,
                    "to": w3.to_checksum_address(tx_data.get("to")),
                    "value": value_int,
                    "data": tx_data.get("data", ""),
                    "nonce": nonce,
                    "chainId": 1,
                }
                
                try:
                    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
                except Exception as e:
                    print(f"[FrontendSniper] Estimate gas gagal, pakai fallback 300k: {e}")
                    tx["gas"] = 300000

                try:
                    tx["maxFeePerGas"] = w3.eth.gas_price * 2
                    tx["maxPriorityFeePerGas"] = w3.to_wei(1, "gwei")
                except Exception:
                    pass 

                signed = w3.eth.account.sign_transaction(tx, w["private_key"])
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                print(f"[FrontendSniper] Wallet {w['index']} sukses on-chain! Hash: {tx_hash.hex()}")
                return tx_hash.hex()
            except Exception as e:
                print(f"[FrontendSniper] Wallet {w['index']} gagal eksekusi on-chain: {e}")
                return None

        print(f"[FrontendSniper] Memulai infiltrasi dari {len(wallets)} wallet berurutan…")
        
        # Eksekusi berurutan agar injeksi JS tiap wallet tidak saling timpa
        for w in wallets:
            result = await _click_mint_for_wallet(w)
            if result is None:
                failed_count += 1
            else:
                tx_hashes.append(str(result))

        await browser.close()

    if failed_count == 0 and tx_hashes:
        return f"✅ Sukses boss!! {len(wallets)} wallet menembus frontend. Hash: [{', '.join(tx_hashes)}]"
    elif tx_hashes:
        return f"❌ Tembus sebagian boss!! Berhasil: [{', '.join(tx_hashes)}]"
    else:
        return "❌ Gagal boss!! Semua wallet gagal nge-trigger transaksi atau revert."

# ---------------------------------------------------------------------------
# CrewAI Tool wrapper
# ---------------------------------------------------------------------------

@tool("Playwright Frontend Sniper")
def playwright_frontend_sniper(url: str, target_time_spec: str = "", wallet_count: int = 4) -> str:
    """
    Monitor a mint page using a headless browser and auto-mint when the button activates.
    Supports standby countdown and multi-wallet parallel execution.
    Args:
        url: The mint page URL.
        target_time_spec: Relative offset like '+10m', '+1h', or UTC time.
        wallet_count: Number of wallets to use.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_monitor_and_mint_async(url, target_time_spec, wallet_count))
    finally:
        loop.close()
