"""布局优化示例 - 展示如何使用优化组件降低信息密度

本文件展示了如何使用 layout_enhanced.py 中的组件来优化布局。
"""

import flet as ft
from app.ui.theme import THEME
from app.ui.components.layout_enhanced import (
    CollapsibleSection,
    EnhancedCard,
    GroupContainer,
    GuideCard,
    StatusCard,
    EmptyState,
    spaced_row,
    spaced_column,
    section_divider,
    add_breathing_space,
)
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, checkbox, label


def example_migrator_layout():
    """示例：优化后的存档转换布局

    改进点：
    1. 使用 GuideCard 提供操作引导
    2. 使用 GroupContainer 分组相关控件
    3. 使用 CollapsibleSection 折叠次要信息
    4. 增加留白和间距
    """

    # 操作引导
    guide = GuideCard(
        title="操作指南",
        steps=[
            "1. 设置源存档：在左侧边栏点击「设置当前存档」",
            "2. 选择输出目录：点击「浏览」按钮选择目标位置",
            "3. 选择目标版本：在版本转换区域选择目标 Minecraft 版本",
            "4. 开始转换：点击顶部「开始转换」按钮",
        ],
        tips=[
            "转换前建议备份原始存档",
            "快速模式仅复制UUID文件，完整模式会进行深度转换",
        ],
    )

    # 存档配置组
    dir_group = GroupContainer(
        title="存档配置",
        icon="📁",
        controls=[
            text_field(label="当前源存档", hint_text="请选择世界文件夹"),
            spaced_row([
                text_field(label="输出目录", hint_text="默认为程序当前目录", expand=True),
                btn_ghost("📂 浏览", width=90),
            ]),
            text_field(label="世界文件夹名", hint_text="例如: world", value="world"),
        ],
    )

    # 版本转换组（使用可折叠区域）
    version_options = ft.Column([
        spaced_row([
            ft.Dropdown(
                label="目标平台",
                options=[ft.dropdown.Option("java", "Java 版")],
                value="java",
                width=150,
            ),
            ft.Dropdown(
                label="目标版本",
                options=[ft.dropdown.Option("3953", "1.21.4 (最新正式版)")],
                value="3953",
                width=280,
            ),
        ]),
        checkbox("剥离 1.20.5+ 数据组件（降级到旧版时推荐）", value=True),
        checkbox("将未知方块替换为 air", value=True),
    ], spacing=8)

    version_section = CollapsibleSection(
        title="版本转换",
        icon="🔄",
        content=version_options,
        initially_expanded=True,
        help_text="降级到旧版本时，建议启用这些选项以避免兼容性问题",
    )

    # 玩家配置组（使用可折叠区域）
    player_options = ft.Column([
        text_field(label="手动指定玩家 (选填)", hint_text="多个玩家用英文逗号分隔"),
        section_divider(),
        label("UUID 查询"),
        ft.Text("输入玩家名查询对应的 UUID", size=11, color=THEME.text_muted),
        spaced_row([
            text_field(hint_text="输入玩家名查询 UUID", expand=True),
            btn_primary("查询", width=90),
        ]),
        ft.Container(
            content=ft.Text("在此显示查询结果", size=11, color=THEME.text_muted),
            bgcolor=THEME.log_bg,
            border_radius=6,
            padding=12,
            height=100,
        ),
    ], spacing=8)

    player_section = CollapsibleSection(
        title="玩家配置",
        icon="👥",
        content=player_options,
        initially_expanded=False,
        help_text="配置玩家数据转换和 UUID 映射",
    )

    # 组合布局
    left_column = spaced_column([
        guide,
        dir_group,
        version_section,
        player_section,
    ], spacing=24)

    return left_column


def example_search_layout():
    """示例：优化后的搜索布局

    改进点：
    1. 使用 EmptyState 显示空状态引导
    2. 使用 StatusCard 显示搜索状态
    3. 使用 CollapsibleSection 折叠高级选项
    """

    # 空状态引导
    empty_state = EmptyState(
        icon=ft.Icons.SEARCH,
        title="开始搜索",
        description="在左侧设置搜索条件，然后点击「开始搜索」按钮",
        action_text="查看帮助",
        on_action=lambda e: print("显示帮助"),
    )

    # 搜索状态
    status_card = StatusCard(
        title="搜索状态",
        status="未开始",
        icon="📊",
    )

    # 搜索条件组
    search_criteria = GroupContainer(
        title="搜索条件",
        icon="🔍",
        controls=[
            ft.Dropdown(
                label="搜索范围",
                options=[
                    ft.dropdown.Option("entity", "生物实体"),
                    ft.dropdown.Option("block", "方块"),
                    ft.dropdown.Option("container", "容器"),
                ],
                value="entity",
            ),
            ft.Dropdown(
                label="目标来源",
                options=[
                    ft.dropdown.Option("preset", "使用预设"),
                    ft.dropdown.Option("custom", "输入 ID"),
                ],
                value="preset",
            ),
            ft.Dropdown(
                label="实体类型",
                options=[
                    ft.dropdown.Option("minecraft:villager", "村民 (minecraft:villager)"),
                    ft.dropdown.Option("minecraft:zombie", "僵尸 (minecraft:zombie)"),
                ],
            ),
        ],
    )

    # 维度选择组
    dimension_group = GroupContainer(
        title="维度",
        icon="🌍",
        controls=[
            checkbox("主世界", value=True),
            checkbox("下界", value=True),
            checkbox("末地", value=True),
        ],
    )

    # 高级选项（可折叠）
    advanced_options = ft.Column([
        checkbox("显示坐标详情", value=True),
        checkbox("显示区块信息", value=False),
        checkbox("显示实体数据", value=False),
    ], spacing=8)

    advanced_section = CollapsibleSection(
        title="高级选项",
        icon="⚙️",
        content=advanced_options,
        initially_expanded=False,
        help_text="这些选项会影响搜索结果的详细程度",
    )

    # 组合布局
    left_column = spaced_column([
        search_criteria,
        dimension_group,
        advanced_section,
        btn_primary("🔍 开始搜索", height=42),
    ], spacing=20)

    return left_column, empty_state, status_card


def example_results_layout():
    """示例：优化后的结果展示布局

    改进点：
    1. 使用 EnhancedCard 展示结果详情
    2. 增加结果项之间的间距
    3. 提供快捷操作按钮
    """

    # 结果项示例
    def build_result_item(index, target_id, dimension, x, y, z):
        """构建单个结果项"""
        return ft.Container(
            content=ft.Row([
                ft.Text(f"#{index}", size=11, color=THEME.mc_gold, width=40),
                ft.Column([
                    ft.Text(target_id, size=12, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{dimension} ({x}, {y}, {z})", size=11, color=THEME.text_muted),
                    ft.Row([
                        ft.TextButton("复制坐标", style=ft.ButtonStyle(padding=ft.Padding(8, 4, 8, 4))),
                        ft.TextButton("在地图中查看", style=ft.ButtonStyle(padding=ft.Padding(8, 4, 8, 4))),
                    ], spacing=8),
                ], spacing=4, expand=True),
            ], spacing=12),
            padding=12,
            bgcolor=THEME.bg_card,
            border_radius=6,
        )

    # 结果列表
    results_list = spaced_column([
        build_result_item(1, "minecraft:villager", "主世界", 100, 64, 200),
        build_result_item(2, "minecraft:villager", "主世界", 150, 65, 250),
        build_result_item(3, "minecraft:villager", "下界", -50, 70, 100),
    ], spacing=8)

    # 结果统计
    stats_card = EnhancedCard(
        title="搜索统计",
        content=ft.Column([
            ft.Text("找到 3 个结果", size=13, color=THEME.text_primary),
            ft.Text("主世界: 2 个, 下界: 1 个", size=12, color=THEME.text_secondary),
        ], spacing=4),
        icon="📊",
        description="搜索耗时: 2.3 秒",
    )

    return results_list, stats_card


def example_empty_state_with_guide():
    """示例：带引导的空状态

    改进点：
    1. 使用 EmptyState 显示友好的空状态
    2. 提供详细的操作指南
    3. 使用图标和颜色引导用户
    """

    return ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.SEARCH, size=64, color=THEME.text_muted),
            ft.Container(height=16),
            ft.Text("开始搜索", size=20, weight=ft.FontWeight.BOLD),
            ft.Container(height=12),
            ft.Text(
                "在左侧设置搜索条件，然后点击「开始搜索」按钮",
                size=14,
                color=THEME.text_secondary,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Container(height=24),
            ft.Container(
                content=ft.Column([
                    ft.Text("📖 操作指南", size=14, weight=ft.FontWeight.BOLD),
                    ft.Container(height=12),
                    ft.Text("1️⃣  选择搜索范围", size=13),
                    ft.Text("     • 实体：村民、僵尸、动物等生物", size=12, color=THEME.text_muted),
                    ft.Text("     • 方块：钻石矿、箱子等方块", size=12, color=THEME.text_muted),
                    ft.Text("     • 容器：箱子、桶、潜影盒等", size=12, color=THEME.text_muted),
                    ft.Container(height=12),
                    ft.Text("2️⃣  选择目标类型", size=13),
                    ft.Text("     • 使用预设：从列表中选择", size=12, color=THEME.text_muted),
                    ft.Text("     • 自定义：输入目标 ID", size=12, color=THEME.text_muted),
                    ft.Container(height=12),
                    ft.Text("3️⃣  选择维度", size=13),
                    ft.Text("     • 主世界、下界、末地", size=12, color=THEME.text_muted),
                    ft.Container(height=12),
                    ft.Text("4️⃣  点击「开始搜索」", size=13),
                ], spacing=4),
                padding=20,
                bgcolor=THEME.bg_secondary,
                border_radius=8,
            ),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=40,
    )
