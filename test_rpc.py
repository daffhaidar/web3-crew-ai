from web3 import Web3
w3 = Web3(Web3.HTTPProvider("https://cloudflare-eth.com", request_kwargs={'headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}}))
print("Tersambung ke RPC:", w3.is_connected())
if w3.is_connected():
    addr = Web3.to_checksum_address("0x2bca07cde1613a9955e62c0dac5114e04d2c379c")
    bal = w3.eth.get_balance(addr)
    print("Saldo Mentah (Wei):", bal)
    print("Saldo ETH:", w3.from_wei(bal, 'ether'))
