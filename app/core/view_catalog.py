"""View factory registration without importing concrete UI modules eagerly."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Dict, Tuple


ViewFactory = Callable[[Any], Any]


@dataclass(frozen=True)
class LazyViewFactory:
    module: str
    class_name: str

    def __call__(self, app: Any) -> Any:
        module = import_module(self.module)
        view_class = getattr(module, self.class_name)
        return view_class(app)


class ViewCatalog:
    """Map stable view identifiers to replaceable factories."""

    def __init__(self) -> None:
        self._factories: Dict[str, ViewFactory] = {}

    def register(self, view_id: str, factory: ViewFactory) -> None:
        if not view_id:
            raise ValueError("view_id 不能为空")
        if not callable(factory):
            raise TypeError("视图工厂必须可调用")
        if view_id in self._factories:
            raise ValueError(f"视图已注册: {view_id}")
        self._factories[view_id] = factory

    def register_lazy(self, view_id: str, module: str, class_name: str) -> None:
        self.register(view_id, LazyViewFactory(module, class_name))

    def create(self, view_id: str, app: Any) -> Any:
        try:
            factory = self._factories[view_id]
        except KeyError as exc:
            raise KeyError(f"未注册的视图: {view_id}") from exc
        return factory(app)

    @property
    def view_ids(self) -> Tuple[str, ...]:
        return tuple(self._factories)
