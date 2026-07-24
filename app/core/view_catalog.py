"""View factory registration without importing concrete UI modules eagerly."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Dict, Iterable, Optional, Tuple


ViewFactory = Callable[[Any], Any]
TopActionsFactory = Callable[[Any], Iterable[Any]]


@dataclass(frozen=True)
class LazyViewFactory:
    """按模块路径惰性导入并实例化视图类。

    避免组合根在启动时导入全部 UI 模块。
    """

    module: str
    class_name: str

    def __call__(self, app: Any) -> Any:
        """导入模块、取类并以 ``app`` 构造视图。

        Args:
            app: 应用协调器，传给视图构造函数。

        Returns:
            新建视图实例。
        """
        module = import_module(self.module)
        view_class = getattr(module, self.class_name)
        return view_class(app)


class ViewCatalog:
    """将稳定视图 id 映射到可替换工厂。

    注册须在首次 ``create`` 前完成；重复 id 会拒绝覆盖以防静默替换。
    """

    def __init__(self) -> None:
        """创建空注册表。"""
        self._factories: Dict[str, ViewFactory] = {}
        self._top_actions_factories: Dict[str, TopActionsFactory] = {}

    def register(
        self,
        view_id: str,
        factory: ViewFactory,
        *,
        top_actions_factory: Optional[TopActionsFactory] = None,
    ) -> None:
        """注册可调用工厂。

        Args:
            view_id: 非空稳定标识。
            factory: ``(app) -> view`` 可调用对象。

        Raises:
            ValueError: id 为空或已注册。
            TypeError: factory 不可调用。
        """
        if not view_id:
            raise ValueError("view_id 不能为空")
        if not callable(factory):
            raise TypeError("视图工厂必须可调用")
        if top_actions_factory is not None and not callable(top_actions_factory):
            raise TypeError("top_actions_factory must be callable")
        if view_id in self._factories:
            raise ValueError(f"视图已注册: {view_id}")
        self._factories[view_id] = factory
        if top_actions_factory is not None:
            self._top_actions_factories[view_id] = top_actions_factory

    def register_lazy(
        self,
        view_id: str,
        module: str,
        class_name: str,
        *,
        top_actions_factory: Optional[TopActionsFactory] = None,
    ) -> None:
        """注册惰性工厂（首次创建时才 import 模块）。

        Args:
            view_id: 稳定视图标识。
            module: 可 import 的模块路径。
            class_name: 模块内视图类名。
        """
        self.register(
            view_id,
            LazyViewFactory(module, class_name),
            top_actions_factory=top_actions_factory,
        )

    def create(self, view_id: str, app: Any) -> Any:
        """调用已注册工厂创建视图。

        Args:
            view_id: 已注册标识。
            app: 传给工厂的应用对象。

        Returns:
            工厂返回的视图实例。

        Raises:
            KeyError: 标识未注册。
        """
        try:
            factory = self._factories[view_id]
        except KeyError as exc:
            raise KeyError(f"未注册的视图: {view_id}") from exc
        return factory(app)

    def get_top_actions(self, view_id: str, view: Any) -> Tuple[Any, ...]:
        """Build registered top actions for one instantiated view.

        Args:
            view_id: Stable identifier registered with the view factory.
            view: Instantiated view consumed by the action factory.

        Returns:
            Immutable action sequence, or an empty tuple when none is defined.

        Raises:
            KeyError: The view identifier is not registered.
        """
        if view_id not in self._factories:
            raise KeyError(f"未注册的视图: {view_id}")
        factory = self._top_actions_factories.get(view_id)
        if factory is None:
            return ()
        return tuple(factory(view))

    @property
    def view_ids(self) -> Tuple[str, ...]:
        """当前已注册的视图 id 元组（注册顺序）。"""
        return tuple(self._factories)
