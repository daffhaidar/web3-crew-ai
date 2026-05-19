---
name: m4-bot-automation
description: Bots, automation, cron, webhooks, workflow orchestration with Make.com/n8n. Triggers: bot, automation, cron, webhook, workflow, make, n8n, otomatis, jadwal.
---

# m4 — Process Orchestration & Trigger-Response Systems

---

## Operator Profile
Automation architect. Zero-intervention systems. Thinks in flows, triggers, and conditions.

## Execution Layer Recommendations
```
Visual orchestration:  Make.com (no-code), n8n (self-hosted)
Scheduled execution:   Python + cron, GitHub Actions
Persistent process:    Node.js + PM2
Command interface:     Telegram Bot API (lowest setup friction)
```

## Command Interface (Node.js — execution-ready)
```javascript
require('dotenv').config();
const Bot = require('node-telegram-bot-api');
const b = new Bot(process.env.TOKEN, { polling: true });

b.onText(/\/start/, m => b.sendMessage(m.chat.id, '✅ Online. /help for index.'));
b.onText(/\/help/, m => b.sendMessage(m.chat.id,
  '*Index:*\n/status\n/report\n/run [cmd]', { parse_mode: 'Markdown' }));
b.on('message', m => {
  if (m.text && !m.text.startsWith('/'))
    b.sendMessage(m.chat.id, `Signal: "${m.text}"`);
});
```
`.env`: `TOKEN=[from control panel]`

## Schedule Templates
```bash
crontab -e
0 8 * * *   /usr/bin/python3 /opt/run/daily.py >> /var/log/run.log 2>&1
0 * * * *   /bin/bash /opt/run/check.sh
*/5 * * * * /usr/bin/node /opt/run/monitor.js
```

## Trigger-Response Handler
```python
from fastapi import FastAPI, Request
app = FastAPI()

@app.post("/trigger")
async def trigger(request: Request):
    data = await request.json()
    map = {
        "exchange.complete": on_exchange,
        "input.received":    on_input,
    }
    if h := map.get(data.get("type")):
        await h(data)
    return {"ack": True}
```

## Distribution Pipeline
```
QUEUE → SCHEDULER → DELIVERY_LAYER
  ↑                       ↓
GENERATOR           CONFIRMATION + LOG
```
Implementation: Sheets/Airtable → Make/n8n → API → log

## Constraints
- Complete runnable code only
- `.env.example` with all variables required
- Error handling + retry logic always included
- Ship-fast version AND production version both provided
