"""键盘快捷键管理器

提供全局键盘快捷键支持：
- 常用操作快捷键（Ctrl+S, Ctrl+O 等）
- 可配置的快捷键绑定
- 快捷键冲突检测
- 快捷键提示显示
"""
from typing import Dict, Callable, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
import flet as ft


class ModifierKey(Enum):
    """修饰键枚举"""
    CTRL = "ctrl"
    ALT = "alt"
    SHIFT = "shift"
    META = "meta"  # Windows键/Command键


@dataclass
class KeyBinding:
    """键盘绑定"""
    key: str
    modifiers: List[ModifierKey]
    callback: Callable
    description: str
    enabled: bool = True
    
    def matches(self, e: ft.KeyboardEvent) -> bool:
        """检查事件是否匹配此绑定
        
        Args:
            e: 键盘事件
            
        Returns:
            是否匹配
        """
        if not self.enabled:
            return False
        
        # 检查主键
        if e.key.lower() != self.key.lower():
            return False
        
        # 检查修饰键
        required_mods = {mod.value for mod in self.modifiers}
        actual_mods = set()
        
        if e.ctrl:
            actual_mods.add("ctrl")
        if e.alt:
            actual_mods.add("alt")
        if e.shift:
            actual_mods.add("shift")
        if e.meta:
            actual_mods.add("meta")
        
        return required_mods == actual_mods
    
    def to_string(self) -> str:
        """转换为易读的快捷键字符串
        
        Returns:
            如 "Ctrl+S", "Alt+Shift+D"
        """
        parts = []
        for mod in self.modifiers:
            if mod == ModifierKey.CTRL:
                parts.append("Ctrl")
            elif mod == ModifierKey.ALT:
                parts.append("Alt")
            elif mod == ModifierKey.SHIFT:
                parts.append("Shift")
            elif mod == ModifierKey.META:
                parts.append("Win")
        
        parts.append(self.key.upper())
        return "+".join(parts)


class KeyboardShortcutManager:
    """键盘快捷键管理器（单例）"""
    
    _instance: Optional['KeyboardShortcutManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        
        self.bindings: Dict[str, KeyBinding] = {}
        self.enabled: bool = True
        self._initialized = True
    
    def register(
        self,
        binding_id: str,
        key: str,
        callback: Callable,
        description: str,
        modifiers: Optional[List[ModifierKey]] = None,
        enabled: bool = True
    ) -> None:
        """注册快捷键
        
        Args:
            binding_id: 绑定唯一标识
            key: 按键（如 "s", "o", "F1"）
            callback: 回调函数
            description: 描述
            modifiers: 修饰键列表
            enabled: 是否启用
        """
        if modifiers is None:
            modifiers = []
        
        binding = KeyBinding(
            key=key,
            modifiers=modifiers,
            callback=callback,
            description=description,
            enabled=enabled
        )
        
        # 检查冲突
        for existing_id, existing_binding in self.bindings.items():
            if (existing_binding.key == key and 
                set(existing_binding.modifiers) == set(modifiers) and
                existing_id != binding_id):
                print(f"[WARNING] 快捷键冲突: {binding.to_string()} 已被 {existing_id} 使用")
        
        self.bindings[binding_id] = binding
    
    def unregister(self, binding_id: str) -> None:
        """注销快捷键
        
        Args:
            binding_id: 绑定唯一标识
        """
        if binding_id in self.bindings:
            del self.bindings[binding_id]
    
    def enable(self, binding_id: str) -> None:
        """启用快捷键
        
        Args:
            binding_id: 绑定唯一标识
        """
        if binding_id in self.bindings:
            self.bindings[binding_id].enabled = True
    
    def disable(self, binding_id: str) -> None:
        """禁用快捷键
        
        Args:
            binding_id: 绑定唯一标识
        """
        if binding_id in self.bindings:
            self.bindings[binding_id].enabled = False
    
    def handle_event(self, e: ft.KeyboardEvent) -> bool:
        """处理键盘事件
        
        Args:
            e: 键盘事件
            
        Returns:
            是否有快捷键被触发
        """
        if not self.enabled:
            return False
        
        for binding in self.bindings.values():
            if binding.matches(e):
                try:
                    binding.callback(e)
                    return True
                except Exception as ex:
                    print(f"[ERROR] 快捷键回调失败: {ex}")
                    return False
        
        return False
    
    def get_all_bindings(self) -> List[Tuple[str, str]]:
        """获取所有快捷键及其描述
        
        Returns:
            (快捷键字符串, 描述) 的列表
        """
        return [
            (binding.to_string(), binding.description)
            for binding in self.bindings.values()
            if binding.enabled
        ]
    
    def create_help_dialog(self) -> ft.AlertDialog:
        """创建快捷键帮助对话框
        
        Returns:
            包含所有快捷键的帮助对话框
        """
        bindings = self.get_all_bindings()
        
        rows = []
        for shortcut, description in sorted(bindings):
            rows.append(
                ft.Row([
                    ft.Text(
                        shortcut,
                        weight=ft.FontWeight.BOLD,
                        font_family="monospace",
                        size=14,
                    ),
                    ft.Text("—", color="grey"),
                    ft.Text(description, size=14),
                ], spacing=10)
            )
        
        return ft.AlertDialog(
            title=ft.Text("键盘快捷键", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    rows,
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=500,
                height=400,
            ),
            actions=[
                ft.TextButton("关闭", on_click=lambda e: None)
            ],
        )


# 全局快捷键管理器实例
shortcut_manager = KeyboardShortcutManager()


def register_default_shortcuts(
    on_save: Optional[Callable] = None,
    on_open: Optional[Callable] = None,
    on_help: Optional[Callable] = None,
    on_refresh: Optional[Callable] = None,
    on_quit: Optional[Callable] = None,
) -> None:
    """注册默认快捷键
    
    Args:
        on_save: 保存回调 (Ctrl+S)
        on_open: 打开回调 (Ctrl+O)
        on_help: 帮助回调 (F1)
        on_refresh: 刷新回调 (F5)
        on_quit: 退出回调 (Ctrl+Q)
    """
    if on_save:
        shortcut_manager.register(
            "save",
            "s",
            on_save,
            "保存当前配置",
            [ModifierKey.CTRL]
        )
    
    if on_open:
        shortcut_manager.register(
            "open",
            "o",
            on_open,
            "打开文件",
            [ModifierKey.CTRL]
        )
    
    if on_help:
        shortcut_manager.register(
            "help",
            "F1",
            on_help,
            "显示帮助",
            []
        )
    
    if on_refresh:
        shortcut_manager.register(
            "refresh",
            "F5",
            on_refresh,
            "刷新页面",
            []
        )
    
    if on_quit:
        shortcut_manager.register(
            "quit",
            "q",
            on_quit,
            "退出应用",
            [ModifierKey.CTRL]
        )
    
    # 显示快捷键帮助
    shortcut_manager.register(
        "show_shortcuts",
        "/",
        lambda e: print("[INFO] 快捷键帮助：请查看菜单"),
        "显示快捷键列表",
        [ModifierKey.CTRL]
    )


class ShortcutHint(ft.Container):
    """快捷键提示组件
    
    在UI中显示某个操作的快捷键提示
    """
    
    def __init__(self, shortcut: str, **kwargs):
        super().__init__(
            content=ft.Text(
                shortcut,
                size=10,
                color="grey",
                font_family="monospace",
            ),
            padding=ft.padding.symmetric(horizontal=4, vertical=2),
            border_radius=3,
            bgcolor="rgba(255, 255, 255, 0.1)",
            **kwargs
        )


def debounce_keyboard_input(callback: Callable, delay_ms: int = 300) -> Callable:
    """防抖动键盘输入处理器
    
    用于搜索框等场景，避免每次按键都触发操作
    
    Args:
        callback: 实际的处理函数
        delay_ms: 延迟毫秒数
        
    Returns:
        包装后的回调函数
    """
    import time
    import threading
    
    last_call_time = [0.0]
    timer: Optional[threading.Timer] = None
    
    def debounced(*args, **kwargs):
        nonlocal timer
        
        current_time = time.time()
        last_call_time[0] = current_time
        
        # 取消之前的定时器
        if timer is not None:
            timer.cancel()
        
        # 创建新的定时器
        def delayed_call():
            if time.time() - last_call_time[0] >= delay_ms / 1000.0:
                callback(*args, **kwargs)
        
        timer = threading.Timer(delay_ms / 1000.0, delayed_call)
        timer.start()
    
    return debounced
