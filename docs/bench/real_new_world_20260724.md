# Bench p95 archive

- generated_utc: 2026-07-24T14:31:36.195117+00:00
- profile: real-world-readonly
- budgets_ok: n/a
- loops: 3
- machine_notes: os=Windows 11; python=3.14.4; machine=AMD64; processor=AMD64 Family 25 Model 33 Stepping 0, AuthenticAMD; profile=real-world-readonly

## Index and session

| size | index cold p95 | index warm p95 | shell p95 | cold session p95 | warm session p95 |
|---|---:|---:|---:|---:|---:|
| real | 32.457 | 36.382 | 1.410 | 54.715 | 3.438 |

## Format and rendering

| size | MCA open p95 | MCA read p95 | level NBT p95 | player NBT p95 | tile cold p95 | tile process-warm p95 | tile disk-cache p95 | backup p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| real | 0.322 | 6602.330 | 1.306 | 0.649 | 125.163 | 2.998 | 0.421 | — |

## Real sample metadata

| size | scale hint | files | bytes | regions | read-only verified | tile size | tile path |
|---|---|---:|---:|---:|---|---:|---|
| real | large | 79 | 105143991 | 23 | True | 16 | ui_initial_preview_largest_overworld_region |
