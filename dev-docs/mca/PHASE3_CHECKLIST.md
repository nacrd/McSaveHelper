# Phase 3 检查清单

## Adapter

- [x] ChunkView (data/x/z/version/get_block/get_palette)
- [x] NativeRegion.from_file / get_chunk
- [x] section_range_for_chunk

## Migrated read paths

- [x] nbt_loader.load_chunk_nbt
- [x] entity_block_search base/utils/block_searcher
- [x] world_stats_service
- [x] region_map_service meta scan
- [x] map_export_service

## Deferred to Phase 4 (write/repair)

- [ ] region_editor_service
- [ ] save_repair/*
- [ ] pure_cleaner / worker / converter

## Done when

core\worker.py:import anvil
app\servicesegion_editor_service.py:        import anvil
app\servicesegion_editor_service.py:        import anvil
core\pure_cleaner.py:import anvil
app\services\save_repair\chunk_repairer.py:from anvil import Region
app\services\save_repair\detector.py:from anvil import Region
core\converter.py:                import anvil
[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m                                  [100%][0m
[32m[32m[1m39 passed[0m[32m in 0.94s[0m[0m
