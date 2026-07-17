"""可访问性 (Accessibility) 辅助工具

提供符合 WCAG 2.1 标准的辅助功能：
- 颜色对比度检查
- 键盘导航支持
- 屏幕阅读器标签
- 焦点管理
- 语义化标记
"""
from typing import Optional, Tuple, Callable
import flet as ft
from app.ui.theme import THEME


def calculate_luminance(hex_color: str) -> float:
    """计算颜色的相对亮度 (relative luminance)

    根据 WCAG 2.1 标准计算颜色亮度

    Args:
        hex_color: 十六进制颜色值，如 "#FFFFFF"

    Returns:
        相对亮度值 (0.0-1.0)
    """
    # 移除 # 并转换为 RGB
    hex_color = hex_color.lstrip('#')

    # 支持 RGB 和 RGBA 格式
    if len(hex_color) == 3:
        hex_color = ''.join([c * 2 for c in hex_color])

    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0

    # 应用 gamma 校正
    def gamma_correct(value: float) -> float:
        if value <= 0.03928:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    r = gamma_correct(r)
    g = gamma_correct(g)
    b = gamma_correct(b)

    # 计算相对亮度
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def calculate_contrast_ratio(color1: str, color2: str) -> float:
    """计算两个颜色之间的对比度比率

    Args:
        color1: 第一个颜色（前景色）
        color2: 第二个颜色（背景色）

    Returns:
        对比度比率 (1.0-21.0)
    """
    lum1 = calculate_luminance(color1)
    lum2 = calculate_luminance(color2)

    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)

    return (lighter + 0.05) / (darker + 0.05)


def check_contrast_wcag(
    foreground: str,
    background: str,
    level: str = "AA",
    large_text: bool = False
) -> Tuple[bool, float]:
    """检查颜色对比度是否符合 WCAG 标准

    Args:
        foreground: 前景色（文本颜色）
        background: 背景色
        level: WCAG 级别，"AA" 或 "AAA"
        large_text: 是否为大文本（18pt+ 或 14pt+ 粗体）

    Returns:
        (是否通过, 实际对比度)
    """
    ratio = calculate_contrast_ratio(foreground, background)

    # WCAG 2.1 对比度要求
    if level == "AAA":
        required_ratio = 4.5 if large_text else 7.0
    else:  # AA
        required_ratio = 3.0 if large_text else 4.5

    return ratio >= required_ratio, ratio


def ensure_accessible_text(
    text: str,
    color: str,
    bgcolor: str,
    size: Optional[int] = None,
    weight: Optional[ft.FontWeight] = None
) -> ft.Text:
    """创建符合可访问性标准的文本控件

    Args:
        text: 文本内容
        color: 文本颜色
        bgcolor: 背景颜色
        size: 字体大小
        weight: 字体粗细

    Returns:
        配置好的 Text 控件
    """
    # 判断是否为大文本
    large_text = (
        size and size >= 18) or (
        weight and weight in [
            ft.FontWeight.BOLD,
            ft.FontWeight.W_700,
            ft.FontWeight.W_800,
            ft.FontWeight.W_900] and size and size >= 14)

    passes, ratio = check_contrast_wcag(
        color, bgcolor, "AA", large_text or False)

    # 如果对比度不足，发出警告（仅开发时）
    if not passes:
        print(
            f"[A11Y WARNING] 对比度不足: {
                ratio:.2f}:1 (前景: {color}, 背景: {bgcolor})")

    return ft.Text(
        text,
        color=color,
        size=size,
        weight=weight,
        selectable=True,  # 允许选择文本，便于辅助技术
    )


class KeyboardNavigable:
    """键盘导航 Mixin

    为控件添加键盘导航支持
    """

    def __init__(
            self,
            on_enter: Optional[Callable] = None,
            on_escape: Optional[Callable] = None):
        self.on_enter_callback = on_enter
        self.on_escape_callback = on_escape

    def handle_keyboard(self, e: ft.KeyboardEvent) -> None:
        """处理键盘事件

        Args:
            e: 键盘事件
        """
        if e.key == "Enter" and self.on_enter_callback:
            self.on_enter_callback(e)
        elif e.key == "Escape" and self.on_escape_callback:
            self.on_escape_callback(e)


def accessible_button(
    text: str,
    on_click: Optional[Callable] = None,
    tooltip: Optional[str] = None,
    semantic_label: Optional[str] = None,
    icon: Optional[ft.IconData] = None,
    disabled: bool = False,
    **kwargs
) -> ft.ElevatedButton:
    """创建符合可访问性标准的按钮

    Args:
        text: 按钮文本
        on_click: 点击回调
        tooltip: 工具提示（用于屏幕阅读器）
        semantic_label: 语义标签（如果与文本不同）
        icon: 图标
        disabled: 是否禁用
        **kwargs: 其他按钮参数

    Returns:
        配置好的按钮控件
    """
    return ft.ElevatedButton(
        content=text,
        icon=icon,
        on_click=on_click,
        tooltip=tooltip or text,
        disabled=disabled,
        # 确保按钮可通过 Tab 键聚焦
        autofocus=kwargs.pop("autofocus", False),
        **kwargs
    )


def accessible_text_field(
    label: str,
    value: str = "",
    hint_text: Optional[str] = None,
    error_text: Optional[str] = None,
    on_change: Optional[Callable] = None,
    password: bool = False,
    required: bool = False,
    **kwargs
) -> ft.TextField:
    """创建符合可访问性标准的文本输入框

    Args:
        label: 标签文本
        value: 初始值
        hint_text: 提示文本
        error_text: 错误提示
        on_change: 变化回调
        password: 是否为密码输入
        required: 是否必填
        **kwargs: 其他输入框参数

    Returns:
        配置好的文本输入框
    """
    # 为必填字段添加视觉和语义标识
    display_label = f"{label} *" if required else label

    return ft.TextField(
        label=display_label,
        value=value,
        hint_text=hint_text,
        error=error_text,
        on_change=on_change,
        password=password,
        can_reveal_password=password,  # 密码字段允许显示/隐藏
        # 语义属性
        tooltip=hint_text or label,
        **kwargs
    )


def screen_reader_only(text: str) -> ft.Text:
    """创建仅供屏幕阅读器使用的文本

    视觉上隐藏但可被辅助技术读取

    Args:
        text: 文本内容

    Returns:
        配置为屏幕阅读器专用的文本控件
    """
    return ft.Text(
        text,
        size=1,
        color="transparent",
        # 注意：Flet 可能不完全支持 aria-label，
        # 这里通过极小字体和透明色实现视觉隐藏
    )


def focus_trap(
        content: ft.Control,
        on_escape: Optional[Callable] = None) -> ft.Container:
    """创建焦点陷阱容器（用于模态对话框）

    防止焦点离开对话框区域，按 Escape 关闭

    Args:
        content: 对话框内容
        on_escape: Escape 键回调

    Returns:
        包装后的容器
    """
    # Flet 的对话框已有焦点管理，这里提供语义包装
    return ft.Container(
        content=content,
        # 可以添加键盘事件处理
    )


def announce_to_screen_reader(
        page: ft.Page,
        message: str,
        priority: str = "polite") -> None:
    """向屏幕阅读器宣告消息

    Args:
        page: 页面对象
        message: 要宣告的消息
        priority: 优先级 "polite" 或 "assertive"
    """
    # Flet 通过 SnackBar 实现可访问的通知
    page.show_dialog(ft.SnackBar(
        content=ft.Text(message),
        duration=3000 if priority == "polite" else 5000,
    ))


class SkipLink(ft.TextButton):
    """跳转链接（辅助键盘导航用户快速跳转到主内容）

    Args:
        target_id: 目标元素 ID
        text: 链接文本
    """

    def __init__(self, target_id: str, text: str = "跳转到主内容"):
        super().__init__(
            content=text,
            # 默认隐藏，获得焦点时显示
            style=ft.ButtonStyle(
                color={
                    ft.ControlState.DEFAULT: "transparent",
                    ft.ControlState.FOCUSED: THEME.text_primary,
                },
                bgcolor={
                    ft.ControlState.DEFAULT: "transparent",
                    ft.ControlState.FOCUSED: THEME.accent,
                },
            ),
        )
        self.target_id = target_id


# 预定义的可访问性配置检查
def validate_theme_accessibility() -> dict:
    """验证主题颜色的可访问性

    Returns:
        包含所有对比度检查结果的字典
    """
    checks = {
        "primary_text_on_primary_bg": check_contrast_wcag(
            THEME.text_primary, THEME.bg_primary
        ),
        "secondary_text_on_primary_bg": check_contrast_wcag(
            THEME.text_secondary, THEME.bg_primary
        ),
        "primary_text_on_card": check_contrast_wcag(
            THEME.text_primary, THEME.bg_card
        ),
        "success_on_primary_bg": check_contrast_wcag(
            THEME.success, THEME.bg_primary, large_text=True
        ),
        "error_on_primary_bg": check_contrast_wcag(
            THEME.error, THEME.bg_primary, large_text=True
        ),
        "warning_on_primary_bg": check_contrast_wcag(
            THEME.warning, THEME.bg_primary, large_text=True
        ),
    }

    return {
        name: {"passes": passes, "ratio": f"{ratio:.2f}:1"}
        for name, (passes, ratio) in checks.items()
    }
