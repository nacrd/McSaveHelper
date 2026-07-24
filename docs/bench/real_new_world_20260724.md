# Bench p95 archive

- generated_utc: 2026-07-24T14:56:29.694869+00:00
- profile: real-world-readonly
- budgets_ok: n/a
- loops: 3
- machine_notes: os=Windows 11; python=3.14.4; machine=AMD64; processor=AMD64 Family 25 Model 33 Stepping 0, AuthenticAMD; profile=real-world-readonly

## Index and session

| size | index cold p95 | index warm p95 | shell p95 | cold session p95 | warm session p95 |
|---|---:|---:|---:|---:|---:|
| real | 34.355 | 36.633 | 1.126 | 55.337 | 3.254 |

## Format and rendering

| size | MCA open p95 | MCA read p95 | level NBT p95 | player NBT p95 | tile cold p95 | tile process-warm p95 | tile disk-cache p95 | visible upgrade p95 | visible process-warm p95 | backup p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| real | 0.495 | 6334.253 | 1.372 | 0.659 | 125.674 | 2.153 | 0.278 | 8062.600 | 392.975 | — |

## Real sample metadata

| size | scale hint | files | bytes | regions | read-only verified | preview size | visible size | tile path |
|---|---|---:|---:|---:|---|---:|---:|---|
| real | large | 79 | 105143991 | 23 | True | 16 | 256 | ui_initial_preview_largest_overworld_region |
