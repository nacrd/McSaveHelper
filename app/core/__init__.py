"""Application Core Managers

This package contains the core manager classes that handle different aspects
of the application lifecycle and functionality.
"""

from .window_manager import WindowManager
from .dialog_manager import DialogManager
from .view_manager import ViewHost, ViewManager, ViewManagerDependencies
from .view_catalog import LazyViewFactory, ViewCatalog
from .progress_manager import ProgressManager
from .gui_optimizer import GUIOptimizer
from .save_context_manager import SaveContextManager

__all__ = [
    "WindowManager",
    "DialogManager",
    "ViewManager",
    "ViewHost",
    "ViewManagerDependencies",
    "LazyViewFactory",
    "ViewCatalog",
    "ProgressManager",
    "GUIOptimizer",
    "SaveContextManager",
]
