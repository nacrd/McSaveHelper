# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCSaveHelper is a Minecraft save file management tool built with Python and Flet (GUI framework). It handles cross-version migration, UUID mapping, NBT editing, save analysis, and repair operations.

## Development Commands

### Running the Application
```bash
python main.py
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_uuid_utils.py

# Run with verbose output
pytest -v tests/
```

### Linting and Type Checking
```bash
# Flake8 (configured in .flake8)
flake8 app core tests

# Mypy (configured in pyproject.toml)
mypy app core tests

# Pyright (configured in pyrightconfig.json)
pyright
```

### Building Executables
```bash
# Single-file executable
pyinstaller build-onefile.spec

# Portable multi-file version
pyinstaller build-portable.spec
```

Output: `dist/` directory

### Debug Packaged Executable
```bash
MCSaveHelper.exe --console
```

## Architecture

### Layer Structure
```
UI Layer (app/ui/)
    ↓ calls
Service Layer (app/services/)
    ↓ uses
Core Layer (core/)
```

- **UI Layer**: Flet-based views and components. Views inherit from `ft.Column`, receive `Application` instance, and implement `on_save_selected(path: str)` method.
- **Service Layer**: Business logic for save operations, NBT parsing, region analysis, entity/block search, etc. Services typically return dataclass results and accept log/progress callbacks.
- **Core Layer**: Low-level utilities for UUID conversion, NBT operations, region file handling, logging, and i18n.

### Key Design Patterns

**View + Service + Test Pattern**: When adding new features, create:
1. `app/services/xxx_service.py` - Business logic
2. `app/ui/views/xxx.py` - Flet UI view
3. `tests/test_xxx.py` - pytest tests

**Page Registration**: New views must be registered in `app/application.py`:
- `_tab_defs`: Add sidebar tab
- `_create_view()`: Import and instantiate view class
- `_get_top_actions()`: Add top-bar action buttons (optional)

**Current Save Context**: Views receive the selected save path via `on_save_selected(path: str)`. A valid save requires `level.dat` in the directory (validated by `app/models/save_context.py`).

**Internationalization**: Add translation keys to `translations/zh_CN.json` and `translations/en_US.json` for any user-facing text.

### Reference Implementations

When implementing similar features, refer to:
- **Statistics/Analysis**: `app/ui/views/explorer/explorer_view.py` (stats tab), `app/services/world_stats_service.py`
- **Export Operations**: `app/ui/views/map_export.py`, `app/services/map_export_service.py`
- **Search Features**: `app/ui/views/entity_block_search.py`, `app/services/entity_block_search_service.py`

## Critical Technical Details

### Flet API Compatibility

**IMPORTANT**: This project includes extensive Flet 0.85+ API compatibility patches in `main.py` (`_patch_flet_api()`). These monkey-patches handle breaking API changes:

1. `ft.alignment.center` and similar convenience properties
2. `ft.ImageFit` → `ft.BoxFit` rename
3. `ft.Image` constructor `src` parameter requirements
4. `ft.Dropdown` constructor `on_change` parameter handling
5. `ft.Spacer` removal (replaced with `ft.Container(expand=True)`)
6. `ft.border.all()` deprecation
7. `page.set_clipboard()` → `page.set_clipboard_async()` change
8. `page.run_task()` async function requirements

When working with Flet components, be aware these patches exist and avoid breaking them.

### Type Checking Configuration

- **mypy** (pyproject.toml): Strict mode enabled with specific overrides
  - External libraries (`nbtlib`, `anvil`, `flet`, `requests`) ignore missing imports
  - Many internal modules have `ignore_errors = true` due to incomplete type annotations
- **pyright** (pyrightconfig.json): Basic type checking mode
- **flake8** (.flake8): Max line length 100, complexity 15, ignores E203/W503

### Logging System

Use the unified logger from `core/logger.py`:
```python
from core.logger import logger

logger.info("Operation succeeded", module="migration")
logger.error("Operation failed", module="migration")
logger.debug("Debug info", module="migration")
```

Supports console output (colored), file rotation, and UI log panel integration.

### Theme System

Theme configuration in `app/ui/theme.py`:
```python
from app.ui.theme import THEME, mc_border, mc_shadow

container = ft.Container(
    bgcolor=THEME.bg_card,
    border=mc_border(2),
    shadow=mc_shadow(4),
)
```

Features Minecraft-style design with dark color scheme and predefined border/shadow effects.

### GUI Optimization Modules

Located in `app/ui/`:
- **accessibility.py**: WCAG 2.1 AA compliance, keyboard navigation, screen reader support
- **keyboard_shortcuts.py**: Global shortcuts (Ctrl+S, Ctrl+O, F1, F5, Ctrl+/)
- **performance.py**: Frame rate monitoring, memory tracking, operation timing
- **feedback.py**: In-app feedback forms, error auto-reporting
- **notifications.py**: Toast notifications, progress dialogs, confirmation prompts
- **hang_detector.py**: UI freeze detection and recovery

## Service Layer Patterns

Services typically follow this structure:
```python
from dataclasses import dataclass
from typing import Callable, Optional

@dataclass
class ServiceResult:
    """Service operation result"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

class MyService:
    def process(
        self,
        path: str,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> ServiceResult:
        if log_callback:
            log_callback("Starting operation...")
        # ... operation logic ...
        if progress_callback:
            progress_callback(0.5)  # 50% complete
        return ServiceResult(success=True, data=result)
```

## Dependencies

Core dependencies (requirements.txt):
- `flet>=0.84.0` and `flet-desktop>=0.84.0` - GUI framework
- `nbtlib` - NBT data parsing
- `anvil-parser2` - Minecraft region file parsing
- `psutil` - Performance monitoring
- `Pillow` - Image processing
- `send2trash` - Safe file deletion
- `requests` - HTTP requests
- `typing_extensions` - Extended type hints

## Working with NBT Data

This project uses `nbtlib` for NBT manipulation and `anvil-parser2` for region file access. Core utilities in `core/nbt_utils.py` and `core/omni/` provide higher-level abstractions.

The `WorldSession` class (`core/omni/world_session.py`) provides the main interface for accessing world data (level.dat, player data, region files).

## Project-Specific Conventions

- Primary language is Chinese (中文) for comments and UI, with English translations via i18n
- Commit messages use conventional commits: `feat:`, `fix:`, `docs:`, `style:`, `refactor:`, `perf:`, `test:`, `chore:`
- Error logs for packaged builds are written to `startup_error.log` in the executable directory
- Use `app/ui/components/` for reusable UI components (`buttons.py`, `cards.py`, `fields.py`, `layout.py`)
- The `Application` class (`app/application.py`) is the central coordinator - avoid creating global state elsewhere
