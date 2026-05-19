---
name: x3-debug-error
description: Fault diagnosis, debugging, error/stack trace resolution. Triggers: error, bug, not working, failed, debug, stack trace, gagal, gak jalan, rusak.
---

# x3 — Fault Diagnosis & Resolution
# Load ONLY when: error, bug, not working, failed, debug, stack trace

---

## Protocol

### Step 1 — Gather (all at once)
```
- Exact exception text (full, not paraphrased)
- Last action taken before fault
- Environment: OS, runtime version, stack
- Last known working state (if applicable)
```

### Step 2 — Classify
```
syntax      → malformed instruction
runtime     → valid syntax, execution failure
logic       → runs clean, wrong output
environment → missing var, wrong version, permission
network     → timeout, DNS, port, firewall
dependency  → missing module, version conflict
```

### Step 3 — Diagnose
```
Root cause: [specific line or config]
Mechanism:  [one sentence why]
```

### Step 4 — Resolve
```bash
# Exact corrective command(s)
```

### Step 5 — Verify
```bash
# Confirmation command
```

### Step 6 — Harden
```
# Config delta to prevent recurrence
```

## Output Format
```
[ROOT CAUSE] → [specific]
[FIX]        → [exact commands]
[VERIFY]     → [verification]
[HARDEN]     → [prevention]
```

Diagnose before prescribing. Never "try this and see."
If more data needed — ask for everything in one message.
