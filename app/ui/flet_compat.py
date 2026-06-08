"""Flet API 兼容层 - 统一不同版本的 API 差异"""
import flet as ft
from typing import Optional, Any, Callable


# ============================================================================
# Alignment 兼容
# ============================================================================
class AlignmentCompat:
    """兼容旧版 ft.alignment 便捷属性"""

    @staticmethod
    def center():
        return ft.alignment.Alignment(0, 0)

    @staticmethod
    def top_left():
        return ft.alignment.Alignment(-1, -1)

    @staticmethod
    def top_center():
        return ft.alignment.Alignment(0, -1)

    @staticmethod
    def top_right():
        return ft.alignment.Alignment(1, -1)

    @staticmethod
    def center_left():
        return ft.alignment.Alignment(-1, 0)

    @staticmethod
    def center_right():
        return ft.alignment.Alignment(1, 0)

    @staticmethod
    def bottom_left():
        return ft.alignment.Alignment(-1, 1)

    @staticmethod
    def bottom_center():
        return ft.alignment.Alignment(0, 1)

    @staticmethod
    def bottom_right():
        return ft.alignment.Alignment(1, 1)


alignment = AlignmentCompat()


# ============================================================================
# Image 兼容
# ============================================================================
def Image(
    src: Optional[str] = None,
    src_base64: Optional[str] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    fit: Optional[Any] = None,
    repeat: Optional[Any] = None,
    border_radius: Optional[Any] = None,
    tooltip: Optional[str] = None,
    visible: Optional[bool] = None,
    **kwargs
) -> ft.Image:
    """兼容旧版 Image 构造函数（src 可选）"""
    # Flet 0.85+ 要求 src 必传，旧版可选
    if src is None and src_base64 is None:
        src = ""  # 提供默认空字符串

    return ft.Image(
        src=src,
        src_base64=src_base64,
        width=width,
        height=height,
        fit=fit,
        repeat=repeat,
        border_radius=border_radius,
        tooltip=tooltip,
        visible=visible,
        **kwargs
    )


# ============================================================================
# BoxFit / ImageFit 兼容
# ============================================================================
class ImageFit:
    """兼容旧版 ft.ImageFit（现在是 ft.BoxFit）"""
    NONE = ft.BoxFit.NONE
    CONTAIN = ft.BoxFit.CONTAIN
    COVER = ft.BoxFit.COVER
    FILL = ft.BoxFit.FILL
    FIT_HEIGHT = ft.BoxFit.FIT_HEIGHT
    FIT_WIDTH = ft.BoxFit.FIT_WIDTH
    SCALE_DOWN = ft.BoxFit.SCALE_DOWN


# ============================================================================
# Dropdown 兼容
# ============================================================================
def Dropdown(
    label: Optional[str] = None,
    value: Optional[str] = None,
    options: Optional[list] = None,
    width: Optional[float] = None,
    on_change: Optional[Callable] = None,
    on_select: Optional[Callable] = None,
    **kwargs
) -> ft.Dropdown:
    """兼容旧版 Dropdown 构造函数（on_change 作为构造参数）"""
    dropdown = ft.Dropdown(
        label=label,
        value=value,
        options=options,
        width=width,
        **kwargs
    )

    # Flet 0.85+ 不支持 on_change 作为构造参数，需要事后设置
    if on_change is not None:
        dropdown.on_change = on_change
    if on_select is not None:
        dropdown.on_select = on_select

    return dropdown


# ============================================================================
# ResponsiveRow 兼容（规避 Wrap 布局问题）
# ============================================================================
def ResponsiveRow(
    controls: Optional[list] = None,
    spacing: Optional[float] = None,
    **kwargs
) -> ft.Row:
    """
    兼容旧版 ResponsiveRow，在 Flet 0.85 中避免使用 Wrap 布局

    注意：这会失去响应式布局能力，建议手动使用 Row/Column 组合
    """
    return ft.Row(
        controls=controls,
        spacing=spacing,
        vertical_alignment=ft.CrossAxisAlignment.START,
        **kwargs
    )


# ============================================================================
# 版本检测
# ============================================================================
def get_flet_version() -> str:
    """获取当前 Flet 版本"""
    return getattr(ft, '__version__', 'unknown')


def is_flet_085_or_later() -> bool:
    """检测是否为 Flet 0.85+"""
    try:
        version = get_flet_version()
        if version == 'unknown':
            return True  # 假设是新版本
        major, minor = map(int, version.split('.')[:2])
        return (major, minor) >= (0, 85)
    except Exception:
        return True  # 出错时假设是新版本
