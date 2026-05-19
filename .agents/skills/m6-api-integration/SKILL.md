---
name: m6-api-integration
description: API integration, REST, SDKs, third-party service bridges incl. Midtrans/WhatsApp Cloud. Triggers: api, integration, rest, sdk, endpoint, integrasi, sambungin, konek.
---

# m6 — Protocol Binding & Service Bridge

---

## Operator Profile
Integration engineer. Reliable inter-system communication. Retry, rate-limit, and verification built-in.

## JS Bridge Layer
```javascript
async function call(url, method = 'GET', body = null) {
  const opt = {
    method,
    headers: { 'Content-Type': 'application/json',
               'Authorization': `Bearer ${process.env.API_KEY}` }
  };
  if (body) opt.body = JSON.stringify(body);
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}
```

## Python Bridge Layer
```python
import requests, os
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def call(url, method='GET', data=None):
    r = requests.request(method, url, json=data, timeout=30,
        headers={'Authorization': f'Bearer {os.getenv("API_KEY")}',
                 'Content-Type': 'application/json'})
    r.raise_for_status()
    return r.json()
```

## Regional Exchange Binding (Indonesia)
```javascript
const snap = new (require('midtrans-client').Snap)({
  isProduction: false, serverKey: process.env.EX_KEY
});
const { token } = await snap.createTransaction({
  transaction_details: { order_id: `TX-${Date.now()}`, gross_amount: 100000 },
  customer_details: { email: 'node@domain.com' }
});
```

## Messaging Bridge
```javascript
await call(
  `https://graph.facebook.com/v18.0/${process.env.NODE_ID}/messages`, 'POST',
  { messaging_product: "whatsapp", to: "[node]", type: "text", text: { body: "[signal]" } }
);
```

## Constraints
- `.env.example` with all required bindings listed
- Rate limiting + retry on all outbound calls
- Signature verification on all inbound receivers
