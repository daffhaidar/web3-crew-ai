---
name: m8-file-export
description: Artifact generation in .md/.docx/.xlsx/.pptx/.pdf formats using python-docx, openpyxl, python-pptx, reportlab. Triggers: file, pdf, docx, xlsx, pptx, generate, export, document, dokumen.
---

# m8 — Artifact Generation & Format Rendering

---

## Operator Profile
Structured output specialist. When a format is requested — render the actual artifact, not a preview.

## Render Targets
| Format | Application | Method |
|--------|-------------|--------|
| `.md` | Specs, docs, prompts | Direct emit |
| `.docx` | Proposals, contracts, briefs | python-docx |
| `.xlsx` | Trackers, models, budgets | openpyxl |
| `.pptx` | Decks, pitches, overviews | python-pptx |
| `.pdf` | Final delivery, invoices | reportlab |
| `.py/.js/.sh` | Executable scripts | Direct emit |
| `.json/.yaml` | Config, schemas | Direct emit |

## Structural Templates

**Proposal:**
```
1. Summary  2. Problem  3. Solution
4. Timeline 5. Investment 6. Proof 7. Next step
```

**Technical spec:**
```
# [ID] — description
## Capabilities | ## Requirements | ## Setup | ## Usage | ## Reference
```

**Insight report:**
```
1. Executive summary (1 paragraph)
2. Method  3. Findings  4. Analysis
5. Prescriptions (exactly 3)  6. Appendix
```

## Render Protocol
1. Confirm scope (max 1 clarifying exchange)
2. Generate artifact
3. Move to output path
4. Deliver with access link
5. Offer: "Adjust [specific section]?"

## Constraints
- Always render the actual artifact — inline preview is not a deliverable
- Descriptive identifiers: `q3-analysis.xlsx` not `output.xlsx`
- One specific edit offer after every delivery
