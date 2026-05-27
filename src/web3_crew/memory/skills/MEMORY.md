# MEMORY.md — Long-Term Context (v3)
# Auto-injected every session. Compact format — token-budget aware.
# Private/main sessions only. Never inject in shared/group contexts.

---

## OWNER

Name:    [name]
Niche:   [primary domain]
Audience: [who they serve]
Model:   [how they make money]

---

## STACK BIASES

Server:  [preferred OS]
Runtime: [preferred language]
DB:      [preferred storage]
Deploy:  [pm2 / systemd / etc.]

---

## ACTIVE PROJECTS

```
[name] | [status] | [stack] | [current blocker or next milestone]
[name] | [status] | [stack] | [current blocker or next milestone]
```

---

## LOCKED DECISIONS

```
[date] | [decision] | [reason — 1 line]
[date] | [decision] | [reason]
```

---

## OPERATOR PREFERENCES (revealed over sessions)

```
- [pref 1]
- [pref 2]
```

---

## RECENT CONTEXT (rolling — last 30 days)

<!-- SUPERAGENT appends compact summaries here. Auto-prune entries > 30 days. -->

<!-- Format: [YYYY-MM-DD] [topic] | [outcome/decision] | [open?] -->

---

## COMPACTION RULES

- Total file ≤ 2000 tokens. Compact when approaching limit.
- Each entry ≤ 1 line.
- Prune entries > 30 days unless flagged "permanent".
- On session end with significant new context → append, don't rewrite.
