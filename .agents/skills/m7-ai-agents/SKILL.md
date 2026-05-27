---
name: m7-ai-agents
description: AI inference systems, LLM orchestration, prompt design, multi-provider routing (Anthropic, OpenAI, OpenRouter, Groq, DeepSeek, Gemini). Triggers: ai, prompt, agent, llm, claude api, gpt, model, openai, anthropic, gemini, openrouter, groq, deepseek, agen.
---

# m7 — Inference System Design & Model Orchestration

---

## Operator Profile
AI systems architect. Production-grade inference pipelines — not prototypes.

## Provider Registry
```
Provider       | Endpoint                                        | Best For
---------------|-------------------------------------------------|---------------------------
Anthropic      | api.anthropic.com/v1/messages                   | Claude, best reasoning
OpenRouter     | openrouter.ai/api/v1/chat/completions            | Multi-model gateway, cheapest
OpenAI         | api.openai.com/v1/chat/completions               | GPT-4o, GPT-4-turbo
Kimi (Moonshot)| api.moonshot.cn/v1/chat/completions              | Long context (128k+)
Groq           | api.groq.com/openai/v1/chat/completions          | Ultra-fast (Llama, Mixtral)
DeepSeek       | api.deepseek.com/v1/chat/completions             | DeepSeek-V3, coding
Together AI    | api.together.xyz/v1/chat/completions             | Open-source, cheap
Google Gemini  | generativelanguage.googleapis.com/v1beta         | Gemini Pro/Ultra
```

## Anthropic Inference
```javascript
async function infer(spec, input, history = []) {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01"
    },
    body: JSON.stringify({
      model: "claude-sonnet-4-20250514",
      max_tokens: 1000, system: spec,
      messages: [...history, { role: "user", content: input }]
    })
  });
  if (!r.ok) throw new Error(`Inference ${r.status}: ${await r.text()}`);
  return (await r.json()).content[0].text;
}
```

## OpenRouter Inference (Multi-Model Gateway)
```javascript
async function inferOR(model, spec, input, history = []) {
  const r = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${process.env.OPENROUTER_API_KEY}`,
      "X-Title": "SUPERAGENT"
    },
    body: JSON.stringify({
      model,
      messages: [{ role: "system", content: spec }, ...history, { role: "user", content: input }]
    })
  });
  if (!r.ok) throw new Error(`OpenRouter ${r.status}: ${await r.text()}`);
  return (await r.json()).choices[0].message.content;
}
// Models: "anthropic/claude-sonnet-4-20250514", "openai/gpt-4o", "deepseek/deepseek-chat",
//         "meta-llama/llama-3.1-405b", "google/gemini-pro-1.5"
```

## Kimi / Moonshot Inference (Long Context)
```javascript
async function inferKimi(spec, input, history = []) {
  const r = await fetch("https://api.moonshot.cn/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${process.env.KIMI_API_KEY}`
    },
    body: JSON.stringify({
      model: "moonshot-v1-128k",
      messages: [{ role: "system", content: spec }, ...history, { role: "user", content: input }]
    })
  });
  if (!r.ok) throw new Error(`Kimi ${r.status}: ${await r.text()}`);
  return (await r.json()).choices[0].message.content;
}
```

## OpenAI Inference
```javascript
async function inferOAI(spec, input, history = []) {
  const r = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${process.env.OPENAI_API_KEY}`
    },
    body: JSON.stringify({
      model: "gpt-4o",
      messages: [{ role: "system", content: spec }, ...history, { role: "user", content: input }]
    })
  });
  if (!r.ok) throw new Error(`OpenAI ${r.status}: ${await r.text()}`);
  return (await r.json()).choices[0].message.content;
}
```

## Groq Inference (Ultra-Fast)
```javascript
async function inferGroq(spec, input, history = []) {
  const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${process.env.GROQ_API_KEY}`
    },
    body: JSON.stringify({
      model: "llama-3.1-70b-versatile",
      messages: [{ role: "system", content: spec }, ...history, { role: "user", content: input }]
    })
  });
  if (!r.ok) throw new Error(`Groq ${r.status}: ${await r.text()}`);
  return (await r.json()).choices[0].message.content;
}
```

## DeepSeek Inference
```javascript
async function inferDS(spec, input, history = []) {
  const r = await fetch("https://api.deepseek.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${process.env.DEEPSEEK_API_KEY}`
    },
    body: JSON.stringify({
      model: "deepseek-chat",
      messages: [{ role: "system", content: spec }, ...history, { role: "user", content: input }]
    })
  });
  if (!r.ok) throw new Error(`DeepSeek ${r.status}: ${await r.text()}`);
  return (await r.json()).choices[0].message.content;
}
```

## Universal Python Wrapper
```python
import requests, os

def call_llm(message, system="You are a helpful assistant.",
             provider="openrouter", model=None):
    configs = {
        "openrouter": ("https://openrouter.ai/api/v1/chat/completions",
                       os.getenv("OPENROUTER_API_KEY"), model or "anthropic/claude-sonnet-4-20250514"),
        "openai":     ("https://api.openai.com/v1/chat/completions",
                       os.getenv("OPENAI_API_KEY"), model or "gpt-4o"),
        "groq":       ("https://api.groq.com/openai/v1/chat/completions",
                       os.getenv("GROQ_API_KEY"), model or "llama-3.1-70b-versatile"),
        "kimi":       ("https://api.moonshot.cn/v1/chat/completions",
                       os.getenv("KIMI_API_KEY"), model or "moonshot-v1-128k"),
        "deepseek":   ("https://api.deepseek.com/v1/chat/completions",
                       os.getenv("DEEPSEEK_API_KEY"), model or "deepseek-chat"),
    }
    url, key, mdl = configs[provider]
    r = requests.post(url, json={
        "model": mdl,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": message}]
    }, headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
```

## Behavioral Specification Architecture
```
[ROLE]           Operator identity
[CONTEXT]        Operational environment
[CAPABILITIES]   Permitted action space
[CONSTRAINTS]    Hard limits
[OUTPUT_FORMAT]  Response schema
[EXAMPLES]       2–3 input/output pairs
```

## Specification Patterns

**Sequential reasoning:**
```
Before responding, resolve:
1. What is the actual request beneath the surface?
2. What context is required?
3. What output schema serves this?
Then emit response.
```

**Structured emission:**
```
Emit ONLY valid JSON. No preamble. No fences.
Schema: { "output": "...", "confidence": 0.0-1.0, "steps": ["..."] }
```

## Orchestration Loop
```javascript
async function loop(task, callFn, tools = {}, limit = 10) {
  let log = [{ role: "user", content: task }];
  for (let i = 0; i < limit; i++) {
    const out = await callFn(SPEC, "", log);
    log.push({ role: "assistant", content: out });
    if (out.includes("[RESOLVED]")) return { ok: true, out, steps: i + 1 };
    const t = out.match(/\[OP:(\w+)\]/)?.[1];
    if (t && tools[t]) log.push({ role: "user", content: `Result: ${await tools[t](out)}` });
  }
  return { ok: false };
}
```

## Provider Selection Guide
```
Best quality?         → Anthropic (Claude) or OpenAI (GPT-4o)
Cheapest?             → DeepSeek or Groq
Multi-model access?   → OpenRouter (1 key, all models)
Long context (128k+)? → Kimi (Moonshot)
Fastest speed?        → Groq
Coding specialist?    → DeepSeek
Open-source models?   → Together AI or Groq
```

## `.env.example`
```
# Pick provider(s) you use — not all required
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENROUTER_API_KEY=sk-or-your-key-here
OPENAI_API_KEY=sk-your-key-here
KIMI_API_KEY=your-moonshot-key-here
GROQ_API_KEY=gsk_your-key-here
DEEPSEEK_API_KEY=your-deepseek-key-here
```

## Constraints
- Runnable implementation always — no pseudocode
- Token cost estimate for production-scale calls
- Caching strategy for repeated specification patterns
- Version specifications on iteration (v1→v2)
- Always include error handling on API calls
