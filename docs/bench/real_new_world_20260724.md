# Bench p95 archive

- generated_utc: 2026-07-24T15:04:44.586912+00:00
- profile: real-world-readonly
- budgets_ok: n/a
- loops: 3
- machine_notes: os=Windows 11; python=3.14.4; machine=AMD64; processor=AMD64 Family 25 Model 33 Stepping 0, AuthenticAMD; profile=real-world-readonly

## Index and session

| size | index cold p95 | index warm p95 | shell p95 | cold session p95 | warm session p95 |
|---|---:|---:|---:|---:|---:|
| real | 33.824 | 30.026 | 1.033 | 47.098 | 1.895 |

## Format and rendering

| size | MCA open p95 | MCA read p95 | level NBT p95 | player NBT p95 | tile cold p95 | tile process-warm p95 | tile disk-cache p95 | progressive upgrade p95 | visible upgrade p95 | visible process-warm p95 | backup p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| real | 0.316 | 5854.904 | 1.216 | 0.752 | 106.801 | 2.123 | 0.275 | 1614.677 | 7439.726 | 330.224 | — |

## Real sample metadata

| size | scale hint | files | bytes | regions | read-only verified | preview size | progressive size | visible size | tile path |
|---|---|---:|---:|---:|---|---:|---:|---:|---|
| real | large | 79 | 105143991 | 23 | True | 16 | 32 | 256 | ui_initial_preview_largest_overworld_region |
