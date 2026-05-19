---
name: x1-audit-system
description: Internal system audit, capability review, agent self-improvement. Triggers: audit, improve system, review agent, upgrade.
---

# x1 — Internal Capability Refinement
# Load ONLY when: audit, improve system, review agent, upgrade

---

## Audit Protocol

### Layer 1 — Output Quality
```
Were last outputs immediately executable?
Did any cause unnecessary follow-up?
Did the reflection loop catch all issues?
```

### Layer 2 — Module Coverage
```
Did correct modules activate per task?
Any gaps (task needed module that doesn't exist)?
Any redundancy between modules?
```

### Layer 3 — Routing Precision
```
Any false positives in trigger matching?
Any missed activations?
Registry keywords still accurate?
```

### Layer 4 — Token Efficiency
```
Any always-on content that could be conditional?
Which modules load more than needed?
What can be compressed without losing function?
```

## Output Format
```
[FINDINGS]
- [issue] → [fix]

[PRIORITY]
1. [highest impact]
2. [second]
3. [third]

[PROPOSED EDITS]
→ exact changes to specific files
```

After audit, always ask:
> "Apply now or review first?"
Never auto-apply system changes.
