def scan_all_regions(world_path):
    patterns = ["region/*.mca", "DIM*/region/*.mca", "dimensions/**/region/*.mca", "*/region/*.mca"]
    files = []
    for pat in patterns:
        files.extend(world_path.rglob(pat))
    return list(set(files))