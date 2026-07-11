# Phase 4 Checklist

## Writer

- [x] core/mca/writer.py WritableRegion
- [x] set/get/delete chunk + atomic save (.tmp + replace)
- [x] optional .mca.bak
- [x] delete_chunk_entries (location table clear)
- [x] unit tests + example_saves round-trip (1024 chunks)

## Migrated off anvil

- [x] core/worker.py
- [x] core/pure_cleaner.py
- [x] core/converter.py
- [x] app/services/region_editor_service.py
- [x] app/services/save_repair/detector.py
- [x] app/services/save_repair/chunk_repairer.py

## Remaining anvil

- [x] none in production code (scripts/bench_mca.py may still import for optional compare)

## Done when

[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m                                                    [100%][0m
[32m[32m[1m21 passed[0m[32m in 0.36s[0m[0m
