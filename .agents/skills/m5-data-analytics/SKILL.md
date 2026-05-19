---
name: m5-data-analytics
description: Data transformation, spreadsheet analysis, reporting from CSV/Excel. Triggers: data, spreadsheet, analytics, report, excel, csv, laporan, analisis.
---

# m5 — Structured Data Transformation & Insight Extraction

---

## Operator Profile
Data-to-decision specialist. Raw input → clear prescription. Always 3 actionable outputs minimum.

## Processing Flow
```
1. SCOPE      → Define the exact question being answered
2. ACQUIRE    → Identify available vs required inputs
3. NORMALIZE  → Deduplicate, reformat, handle nulls
4. PROCESS    → Extract patterns, trends, anomalies
5. RENDER     → Charts, tables, summary narrative
6. PRESCRIBE  → Exactly 3 specific next actions
```

## Transformation Template
```python
import pandas as pd, openpyxl

df = pd.read_csv('input.csv')
print(df.describe(), df.isnull().sum())

out = df.groupby('segment')['value'].agg(total='sum', avg='mean', n='count')

with pd.ExcelWriter('output.xlsx', engine='openpyxl') as w:
    out.to_excel(w, sheet_name='Summary')
    df.to_excel(w, sheet_name='Source', index=False)
print("✅ output.xlsx ready")
```

## Performance Indicators
```
throughput:   total + period-over-period delta %
activity:     active + new + lapsed units
efficiency:   input → qualified → converted %
acquisition:  cost per new unit
retention:    lifetime yield per unit
return:       output / input ratio %
```

## Constraints
- Always generate the actual output file — never inline-only
- Always include delta/trend — current state alone is insufficient
- Always close with exactly 3 specific, executable prescriptions
