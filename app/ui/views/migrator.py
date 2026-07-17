"""Migrator View —— 存档转换主界面"""
import flet as ft
from typing import TYPE_CHECKING

from app.ui.theme import THEME, mc_border
from app.ui.icons import IconSet
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, checkbox, label, current_save_field
from app.ui.components.cards import card, section_title
from app.ui.components.layout import page_header
from app.ui.view_actions import ViewAction

if TYPE_CHECKING:
    from app.application import Application

VERSION_OPTIONS = [
    ("1.21.4", 3953, "最新正式版"),
    ("1.21.0", 3952, ""),
    ("1.20.6", 3839, "数据组件重构"),
    ("1.20.4", 3700, ""),
    ("1.20.2", 3698, ""),
    ("1.20.0", 3692, ""),
    ("1.19.4", 3337, ""),
    ("1.19.2", 3120, ""),
    ("1.18.2", 2975, ""),
    ("1.17.1", 2730, ""),
    ("1.16.5", 2586, ""),
    ("1.12.2", 1343, "扁平化前"),
]

PLATFORM_OPTIONS = [
    ("java", "Java 版"),
    ("bedrock", "基岩版"),
]


class MigratorView(ft.Column):
    """存档转换视图 — 左右两栏布局（优化版）"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=24, scroll=ft.ScrollMode.AUTO)  # 增加整体间距
        self.expand = True
        self.app: "Application" = app
        self._build()

    @property
    def _t(self):
        return self.app.translate

    def get_top_actions(self) -> list[ViewAction]:
        return [
            ViewAction(
                self._t("top_bar.start_conversion", "开始转换"),
                lambda event: self.app.start(),
            )
        ]

    def set_path_value(self, target: str, value: str) -> None:
        """Update a path control through the public view command boundary."""
        fields = {
            "source": self._src_field,
            "destination": self._dest_field,
            "batch": self._batch_dir_field,
        }
        try:
            field = fields[target]
        except KeyError as error:
            raise ValueError(f"未知路径目标: {target}") from error
        field.value = value
        try:
            field.update()
        except RuntimeError:
            pass

    def _build(self) -> None:
        self.controls.clear()
        self.controls.append(
            page_header(
                "存档转换",
                ft.Text(
                    "跨版本迁移世界、玩家数据、UUID 和资源映射",
                    size=12,
                    color=THEME.text_muted),
                icon=IconSet.PACKAGE,
            ))

        # 添加操作引导
        guide_card = ft.Container(
            content=ft.Column([
                ft.Text("📖 操作指南", size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary),
                ft.Container(height=8),
                ft.Text(
                    "1. 设置源存档：在左侧边栏点击「设置当前存档」\n"
                    "2. 选择输出目录：点击「浏览」按钮选择目标位置\n"
                    "3. 选择目标版本：在版本转换区域选择目标 Minecraft 版本\n"
                    "4. 开始转换：点击顶部「开始转换」按钮\n\n"
                    "💡 提示：转换前建议备份原始存档",
                    size=12,
                    color=THEME.text_secondary,
                ),
            ]),
            bgcolor=THEME.bg_secondary,
            padding=16,
            border_radius=8,
            border=ft.Border.all(1, THEME.border_subtle),
        )
        self.controls.append(guide_card)

        content = ft.Row(
            [self._build_left(), ft.Container(width=24), self._build_right()],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.controls.append(content)

    # ─── 左栏 ──────────────────────────────────

    def _build_left(self) -> ft.Column:
        col = ft.Column(spacing=24)  # 增加卡片间距
        col.expand = True
        col.controls.append(self._build_dir_card())
        col.controls.append(self._build_version_card())
        col.controls.append(self._build_player_card())
        return col

    def _build_dir_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title(
            self._t("left_panel.archive_config", "📁 存档配置")))

        # 添加说明文字
        s.controls.append(ft.Container(
            content=ft.Text(
                "设置要转换的源存档和输出位置",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        ))

        self._src_field = current_save_field(
            label="当前源存档",
            hint_text="请通过侧边栏「设置当前存档」设置世界文件夹 (包含 level.dat)",
        )
        self._src_field.on_change = lambda e: self._sync_field_to_config()
        s.controls.append(ft.Container(
            content=self._src_field,
            padding=ft.Padding(left=20, right=20, bottom=12),
        ))

        self._dest_field = text_field(
            label=self._t(
                "left_panel.server_root",
                "输出目录"),
            hint_text=self._t(
                "left_panel.placeholder_default_dir",
                "默认为程序当前目录"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        s.controls.append(ft.Container(
            content=ft.Row([
                self._dest_field,
                btn_ghost(self._t("left_panel.browse", "📂 浏览"), width=90, height=38,
                          on_click=lambda e: self.app.set_dest()),
            ], spacing=10),
            padding=ft.Padding(left=20, right=20, bottom=12),
        ))

        self._name_field = text_field(
            label=self._t(
                "left_panel.world_folder_name",
                "世界文件夹名"),
            hint_text=self._t(
                "left_panel.placeholder_world_name",
                "例如: world"),
            value=mc.world_name or "world",
            on_change=lambda e: self._sync_field_to_config(),
        )
        s.controls.append(ft.Container(
            content=self._name_field,
            padding=ft.Padding(left=20, right=20, bottom=20),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    def _build_version_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title("🔄 版本转换"))

        # 添加说明文字
        s.controls.append(ft.Container(
            content=ft.Text(
                "选择目标平台和版本，配置转换选项",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        ))

        self._vc_platform_dd = ft.Dropdown(
            options=[
                ft.dropdown.Option(
                    k,
                    v) for k,
                v in PLATFORM_OPTIONS],
            value=mc.target_platform or "java",
            width=150,
            border_color=THEME.border_standard,
            text_size=13,
            on_select=lambda e: setattr(
                self.app.config.migration,
                "target_platform",
                e.control.value),
        )
        self._vc_version_dd = ft.Dropdown(
            options=[ft.dropdown.Option(
                str(ver), f"{name} (ID: {ver}){'  — ' + note if note else ''}"
            ) for name, ver, note in VERSION_OPTIONS],
            value=mc.target_version or str(VERSION_OPTIONS[0][1]),
            width=280,
            border_color=THEME.border_standard,
            text_size=13,
            on_select=lambda _: self._on_version_change(),
        )
        s.controls.append(ft.Container(
            content=ft.Row([
                ft.Column([label("目标平台"), self._vc_platform_dd], spacing=4),
                ft.Column([label("目标版本"), self._vc_version_dd], spacing=4),
            ], spacing=16),
            padding=ft.Padding(left=20, right=20, top=12, bottom=12),
        ))

        # 创建复选框
        self._vc_strip_cb = ft.Checkbox(
            label="剥离 1.20.5+ 数据组件（降级到旧版时推荐）",
            value=True,
            label_style=ft.TextStyle(color=THEME.text_secondary),
        )
        self._vc_replace_cb = ft.Checkbox(
            label="将未知方块替换为 air",
            value=True,
            label_style=ft.TextStyle(color=THEME.text_secondary),
        )

        # 高级选项区域（增加视觉分隔）
        s.controls.append(ft.Container(
            content=ft.Column([
                ft.Text("高级选项", size=12, weight=ft.FontWeight.W_600,
                        color=THEME.text_secondary),
                ft.Container(height=8),
                self._vc_strip_cb,
                self._vc_replace_cb,
                ft.Container(height=8),
                ft.Text(
                    "💡 降级到旧版本时，建议启用这些选项以避免兼容性问题",
                    size=11,
                    color=THEME.text_muted,
                ),
            ], spacing=8),
            padding=ft.Padding(left=12, right=12, top=12, bottom=12),
            bgcolor=THEME.bg_secondary,
            border_radius=6,
            margin=ft.Margin(left=12, right=12, top=0, bottom=0),
        ))

        self._vc_options_col = ft.Column(
            [self._vc_strip_cb, self._vc_replace_cb], spacing=4,
        )

        self._vc_warn_box = ft.Text(
            "", size=11, color=THEME.warning, visible=False)
        s.controls.append(ft.Container(
            content=self._vc_warn_box,
            padding=ft.Padding(left=20, right=20, bottom=20),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    def _build_player_card(self) -> ft.Container:
        s = ft.Column(spacing=0)
        s.controls.append(section_title(
            self._t("left_panel.player_config", "👥 玩家配置")))

        # 添加说明文字
        s.controls.append(ft.Container(
            content=ft.Text(
                "配置玩家数据转换和 UUID 映射",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        ))

        self._manual_field = text_field(
            label="手动指定玩家 (选填)",
            hint_text=self._t("left_panel.placeholder_manual_names",
                              "多个玩家用英文逗号分隔，例如: Steve, Alex"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        s.controls.append(ft.Container(
            content=self._manual_field,
            padding=ft.Padding(left=20, right=20, bottom=12),
        ))

        # 使用分隔线分隔 UUID 查询区域
        s.controls.append(ft.Container(
            content=ft.Divider(height=1, color=THEME.border_subtle),
            padding=ft.Padding(left=20, right=20, top=8, bottom=8),
        ))

        s.controls.append(
            ft.Container(
                content=ft.Text(
                    "UUID 查询",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_secondary),
                padding=ft.Padding(
                    left=20,
                    right=20,
                    bottom=8),
            ))

        # 添加 UUID 查询说明
        s.controls.append(ft.Container(
            content=ft.Text(
                "输入玩家名查询对应的 UUID，用于离线模式玩家数据转换",
                size=11,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=8),
        ))

        self._query_field = text_field(
            hint_text="输入玩家名查询 UUID", expand=True,
        )
        s.controls.append(ft.Container(
            content=ft.Row([
                self._query_field,
                btn_primary("查询", width=90, height=38,
                            on_click=lambda e: self._query_uuid()),
            ], spacing=10),
            padding=ft.Padding(left=20, right=20, bottom=12),
        ))

        self._query_result = ft.Text(
            "在此显示查询结果",
            size=11, color=THEME.text_muted,
        )
        s.controls.append(ft.Container(
            content=ft.Container(
                content=self._query_result, bgcolor=THEME.log_bg,
                border=mc_border(2),
                border_radius=6,
                padding=12, height=120,  # 增加高度
            ),
            padding=ft.Padding(left=20, right=20, bottom=20),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    # ─── 右栏 ──────────────────────────────────

    def _build_right(self) -> ft.Column:
        col = ft.Column(spacing=24)  # 增加卡片间距
        col.expand = True
        col.controls.append(self._build_mode_card())
        col.controls.append(self._build_options_card())
        col.controls.append(self._build_batch_card())
        return col

    def _build_mode_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title(
            self._t("right_panel.mode_settings", "⚙️ 转换模式")))

        # 添加模式说明
        s.controls.append(ft.Container(
            content=ft.Text(
                "选择转换模式，影响转换速度和完整性",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        ))

        self._mode_fast = ft.Radio(
            value="fast", label=self._t(
                "right_panel.fast_mode", "⚡ 快速模式"))
        self._mode_full = ft.Radio(
            value="full", label=self._t(
                "right_panel.full_mode", "🧠 完整模式"))
        mode_group = ft.RadioGroup(
            content=ft.Row([self._mode_fast, self._mode_full], spacing=30),
            value=mc.mode,
            on_change=lambda _: self._on_mode_change(
                mode_group.value or "fast"
            ),
        )
        s.controls.append(ft.Container(
            content=mode_group,
            padding=ft.Padding(left=20, right=20, top=12, bottom=12),
        ))

        self._mode_desc = ft.Text(
            "⚡ 快速模式：仅复制UUID文件，速度最快",
            size=11, color=THEME.text_muted,
        )
        s.controls.append(ft.Container(
            content=self._mode_desc,
            padding=ft.Padding(left=20, right=20, bottom=20),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    def _build_options_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title(
            self._t("right_panel.migration_options", "📦 处理选项")))

        self._offline_cb = checkbox(
            self._t(
                "right_panel.offline_mode",
                "离线模式（不请求 Mojang API）"),
            value=mc.offline_mode,
            on_change=lambda e: setattr(
                self.app.config.migration,
                'offline_mode',
                e.control.value),
        )
        self._clean_cb = checkbox(
            self._t(
                "right_panel.clean_mode",
                "精简存档（移除缓存/日志）"),
            value=mc.clean_mode,
            on_change=lambda e: setattr(
                self.app.config.migration,
                'clean_mode',
                e.control.value),
        )
        self._pure_clean_cb = checkbox(
            self._t(
                "right_panel.pure_clean_mode",
                "纯净扫描（移除模组方块/实体）"),
            value=mc.pure_clean_mode,
            on_change=lambda e: setattr(
                self.app.config.migration,
                'pure_clean_mode',
                e.control.value),
        )

        cb_col = ft.Column(
            [self._offline_cb, self._clean_cb, self._pure_clean_cb],
            spacing=8,
        )
        s.controls.append(ft.Container(
            content=cb_col,
            padding=ft.Padding(left=20, right=20, top=12, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    def _build_batch_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title("📦 批量处理"))

        self._batch_mode_cb = checkbox(
            self._t("right_panel.batch_mode", "启用批量模式（一次处理多个存档）"),
            value=mc.batch_mode,
            on_change=lambda e: self._toggle_batch(e.control.value),
        )
        s.controls.append(ft.Container(
            content=self._batch_mode_cb,
            padding=ft.Padding(left=20, right=20, top=12, bottom=8),
        ))

        self._batch_dir_field = text_field(
            label="批量存档目录",
            hint_text="包含多个世界存档的目录",
            on_change=lambda e: self._sync_field_to_config(),
        )
        self._batch_scan_btn = btn_primary(
            "🔍 扫描", width=90, height=38, on_click=lambda e: self._scan_batch())
        self._batch_result = ft.Text("", size=11, color=THEME.text_muted)
        self._batch_detail_col = ft.Column([
            ft.Row([
                self._batch_dir_field,
                btn_ghost("📂 浏览", width=90, height=38,
                          on_click=lambda e: self.app.set_batch_dir()),
                self._batch_scan_btn,
            ], spacing=10),
            self._batch_result,
        ], spacing=8)
        s.controls.append(ft.Container(
            content=self._batch_detail_col,
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self._batch_detail_col.visible = mc.batch_mode
        return c

    # ─── 联动回调 ──────────────────────────────

    def _on_mode_change(self, mode: str) -> None:
        mc = self.app.config.migration
        mc.mode = mode
        is_fast = mode == "fast"

        self._mode_desc.value = (
            "⚡ 快速模式：仅复制UUID文件，速度最快"
            if is_fast
            else "🧠 完整模式：深度 NBT 修补 + 版本转换 + 物品ID迁移"
        )

        self._vc_options_col.disabled = is_fast
        if is_fast:
            self._vc_warn_box.visible = False
        else:
            self._on_version_update()

        self.update()

    def _on_version_change(self) -> None:
        self.app.config.migration.target_version = self._vc_version_dd.value or ""
        self._on_version_update()
        self.update()

    def _on_version_update(self) -> None:
        if self._mode_fast.value == "fast":
            return
        try:
            target_ver = int(self._vc_version_dd.value or "0")
            if target_ver < 2586:
                self._vc_warn_box.value = f"⚠️ 降到 ID {target_ver} 是较大跨度，部分新版本数据可能丢失。请确保已备份存档。"
                self._vc_warn_box.visible = True
                self._vc_strip_cb.value = True
                self._vc_replace_cb.value = True
            else:
                self._vc_warn_box.visible = False
        except (ValueError, TypeError):
            pass

    def _toggle_batch(self, enabled: bool) -> None:
        self.app.config.migration.batch_mode = enabled
        self._batch_detail_col.visible = enabled
        self._batch_detail_col.update()

    # ─── 工具回调 ──────────────────────────────

    def _sync_field_to_config(self) -> None:
        mc = self.app.config.migration
        mc.src_path = self._src_field.value or ""
        mc.dest_path = self._dest_field.value or ""
        mc.world_name = self._name_field.value or "world"
        mc.batch_dir_path = self._batch_dir_field.value or ""
        mc.manual_names = self._manual_field.value or ""
        mc.target_platform = self._vc_platform_dd.value or "java"
        mc.target_version = self._vc_version_dd.value or ""

    def _scan_batch(self) -> None:
        mc = self.app.config.migration
        result = self.app.migration.scan_batch_dir(mc.batch_dir_path)
        if result:
            self._batch_result.value = self.app.migration.scan_result
            self.app.log(self._t("messages.batch_scan_complete",
                                 "批量扫描完成: 找到 {count} 个世界存档",
                                 count=len(result)), "SUCCESS")
        else:
            self._batch_result.value = self._t("messages.no_valid_worlds",
                                               "未找到有效的世界存档")
            self.app.log(self._t("messages.batch_scan_no_worlds",
                                 "批量扫描: 未找到有效的世界存档"), "WARN")
        self._batch_result.update()

    def _query_uuid(self) -> None:
        name = self._query_field.value.strip()
        if not name:
            return
        offline_uuid = self.app.uuid.generate_offline_uuid(name)
        online_uuid, official_name = self.app.uuid.query_online_uuid(
            name, self.app.log)

        lines = [f"玩家: {name}"]
        lines.append(f"离线 UUID: {offline_uuid}")
        if online_uuid:
            lines.append(f"正版 UUID: {online_uuid}")
            if official_name and official_name != name:
                lines.append(f"官方名称: {official_name}")
        else:
            lines.append("正版 UUID: 未获取到（可能为离线账号）")

        self._query_result.value = "\n".join(lines)
        self._query_result.update()

    def on_save_selected(self, path: str) -> None:
        try:
            self._src_field.value = path
            self._sync_field_to_config()
            self._src_field.update()
        except Exception:
            pass
