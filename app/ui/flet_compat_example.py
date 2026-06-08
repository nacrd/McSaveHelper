"""Flet 兼容层使用示例"""

# ============================================================================
# 方式 1：部分导入（推荐）
# ============================================================================
import flet as ft
from app.ui.flet_compat import alignment, Image, ImageFit, Dropdown

# 使用兼容的 alignment
container = ft.Container(
    alignment=alignment.center(),  # 兼容新旧版本
)

# 使用兼容的 Image（src 可选）
img = Image(
    width=100,
    height=100,
    fit=ImageFit.CONTAIN,  # 兼容 ft.ImageFit / ft.BoxFit
    visible=False,
)

# 使用兼容的 Dropdown（on_change 作为构造参数）
dropdown = Dropdown(
    label="选择",
    options=[ft.dropdown.Option("a"), ft.dropdown.Option("b")],
    on_change=lambda e: print(e.control.value),  # 兼容新旧版本
)


# ============================================================================
# 方式 2：完全替换（需要大量修改）
# ============================================================================
# import flet as ft_original
# from app.ui import flet_compat as ft
#
# # 所有 ft.xxx 自动使用兼容版本
# container = ft.Container(alignment=ft.alignment.center())


# ============================================================================
# 方式 3：Monkey Patch（不推荐，但改动最小）
# ============================================================================
# import flet as ft
# from app.ui.flet_compat import alignment, Image, ImageFit, Dropdown
#
# # 在应用入口处一次性替换
# ft.alignment.center = alignment.center
# ft.alignment.top_left = alignment.top_left
# # ... 其他属性
# ft.ImageFit = ImageFit
# ft.Image = Image
# ft.Dropdown = Dropdown
