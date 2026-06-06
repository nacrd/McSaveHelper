"""Migrator View —— 批量迁移主界面"""
import flet as ft
from typing import TYPE_CHECKING, Optional, Any
from pathlib import Path

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, checkbox, label
from app.ui.components.cards import card, section_title

if TYPE_CHECKING:
    from app.application import Application


class MigratorView(ft.Column):
    """批量迁移视图 — 左右两栏布局"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app: "Application" = app
        self._build()

    @property
    def _t(self):
        return self.app._t

    def _build(self) -> None:
        self.controls.clear()
        content = ft.Row(
            [self._build_left(), ft.Container(width=18), self._build_right()],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.controls.append(content)

    # ─── 左栏 ──────────────────────────────────

    def _build_left(self) -> ft.Column:
        col = ft.Column(spacing=18)
        col.expand = True

        # 存档目录配置卡片
        col.controls.append(self._build_dir_card())
        # 批量存档目录（可切换）
        col.controls.append(self._build_batch_card())
        # 手动玩家名
        col.controls.append(self._build_manual_card())

        return col

    def _build_dir_card(self) -> ft.Container:
        mc = self.app.config.migration
        dir_s = ft.Column(spacing=0)
        dir_s.controls.append(section_title(
            self._t("left_panel.archive_config", "📁 存档目录配置")))

        self._src_field = text_field(
            label=self._t("left_panel.client_archive", "客户端存档"),
            hint_text=self._t("left_panel.placeholder_select_world", "选择世界文件夹 (包含 level.dat)"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        dir_s.controls.append(ft.Container(
            content=ft.Row([
                self._src_field,
                btn_ghost(self._t("left_panel.browse", "📂 浏览"), width=90, height=38,
                          on_click=lambda e: self.app.set_src()),
            ], spacing=10),
            padding=ft.Padding(left=20, right=20, bottom=8),
        ))

        self._dest_field = text_field(
            label=self._t("left_panel.server_root", "服务端根目录"),
            hint_text=self._t("left_panel.placeholder_default_dir", "默认为程序当前目录"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        dir_s.controls.append(ft.Container(
            content=ft.Row([
                self._dest_field,
                btn_ghost(self._t("left_panel.browse", "📂 浏览"), width=90, height=38,
                          on_click=lambda e: self.app.set_dest()),
            ], spacing=10),
            padding=ft.Padding(left=20, right=20, bottom=8),
        ))

        self._name_field = text_field(
            label=self._t("left_panel.world_folder_name", "世界文件夹名"),
            hint_text=self._t("left_panel.placeholder_world_name", "例如: world"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        dir_s.controls.append(ft.Container(
            content=self._name_field,
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = dir_s
        return c

    def _build_batch_card(self) -> ft.Container:
        self._batch_card = card(ft.Column(spacing=0), padding=0)
        batch_s = ft.Column(spacing=0)
        batch_s.controls.append(section_title(
            self._t("left_panel.batch_archive_dir", "批量存档目录")))
        bf = ft.Column(spacing=8)

        self._batch_dir_field = text_field(
            hint_text=self._t("left_panel.placeholder_batch_dir", "选择包含多个世界存档的目录"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        bf.controls.append(ft.Row([
            self._batch_dir_field,
            btn_ghost(self._t("left_panel.browse", "📂 浏览"), width=90, height=38,
                      on_click=lambda e: self.app.set_batch_dir()),
            btn_primary(self._t("left_panel.scan", "🔍 扫描"), width=90, height=38,
                        on_click=lambda e: self._scan_batch()),
        ], spacing=10))

        self._batch_result = ft.Text("", size=11, color=THEME.text_muted)
        bf.controls.append(self._batch_result)
        batch_s.controls.append(ft.Container(
            content=bf, padding=ft.Padding(left=20, right=20, bottom=18)))
        self._batch_card.content = batch_s
        self._batch_card.visible = False
        return self._batch_card

    def _build_manual_card(self) -> ft.Container:
        manual_s = ft.Column(spacing=0)
        manual_s.controls.append(section_title(
            self._t("left_panel.manual_players", "👥 手动指定玩家 (选填)")))
        self._manual_field = text_field(
            hint_text=self._t("left_panel.placeholder_manual_names",
                              "多个玩家用英文逗号分隔，例如: Steve, Alex"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        manual_s.controls.append(ft.Container(
            content=self._manual_field,
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))
        c = card(ft.Column(spacing=0), padding=0)
        c.content = manual_s
        return c

    # ─── 右栏 ──────────────────────────────────

    def _build_right(self) -> ft.Column:
        col = ft.Column(spacing=18)
        col.expand = True

        col.controls.append(self._build_mode_card())
        col.controls.append(self._build_uuid_card())
        col.controls.append(self._build_options_card())
        return col

    def _build_mode_card(self) -> ft.Container:
        mc = self.app.config.migration
        mode_s = ft.Column(spacing=0)
        mode_s.controls.append(section_title(
            self._t("right_panel.mode_settings", "模式设置")))

        def mode_changed(e: ft.ControlEvent) -> None:
            self.app.config.migration.mode = e.control.value

        self._mode_fast = ft.Radio(value="fast",
                                    label=self._t("right_panel.fast_mode", "⚡ 快速模式"))
        self._mode_full = ft.Radio(value="full",
                                    label=self._t("right_panel.full_mode", "🧠 完整模式"))
        mode_group = ft.RadioGroup(
            content=ft.Row([self._mode_fast, self._mode_full], spacing=30),
            value=mc.mode, on_change=mode_changed,
        )
        mode_s.controls.append(ft.Container(
            content=mode_group,
            padding=ft.Padding(left=20, right=20, top=12, bottom=8),
        ))
        mode_s.controls.append(ft.Container(
            content=ft.Text(
                self._t("right_panel.mode_description",
                        "快速模式：仅复制UUID文件；完整模式：深度NBT修补"),
                size=11, color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = mode_s
        return c

    def _build_uuid_card(self) -> ft.Container:
        uuid_s = ft.Column(spacing=0)
        uuid_s.controls.append(section_title(
            self._t("right_panel.uuid_query", "UUID 查询")))

        self._query_field = text_field(
            hint_text=self._t("right_panel.placeholder_player_name", "输入玩家名"),
            expand=True,
        )
        uuid_s.controls.append(ft.Container(
            content=ft.Row([
                self._query_field,
                btn_primary(self._t("right_panel.query_button", "查询"), width=90, height=38,
                            on_click=lambda e: self._query_uuid()),
            ], spacing=10),
            padding=ft.Padding(left=20, right=20, top=12, bottom=8),
        ))

        self._query_result = ft.Text(
            self._t("right_panel.query_result_placeholder", "在此显示查询结果"),
            size=11, color=THEME.text_muted,
        )
        uuid_s.controls.append(ft.Container(
            content=ft.Container(
                content=self._query_result, bgcolor=THEME.log_bg,
                border=ft.Border(left=ft.BorderSide(1, THEME.log_border), top=ft.BorderSide(1, THEME.log_border), right=ft.BorderSide(1, THEME.log_border), bottom=ft.BorderSide(1, THEME.log_border)), border_radius=8,
                padding=12, height=110,
            ),
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = uuid_s
        return c

    def _build_options_card(self) -> ft.Container:
        mc = self.app.config.migration
        opt_s = ft.Column(spacing=0)
        opt_s.controls.append(section_title(
            self._t("right_panel.migration_options", "迁移选项")))

        self._offline_cb = checkbox(
            self._t("right_panel.offline_mode", "离线模式（不请求Mojang API）"),
            value=mc.offline_mode,
            on_change=lambda e: setattr(self.app.config.migration, 'offline_mode', e.control.value),
        )
        self._clean_cb = checkbox(
            self._t("right_panel.clean_mode", "精简存档（移除缓存/日志）"),
            value=mc.clean_mode,
            on_change=lambda e: setattr(self.app.config.migration, 'clean_mode', e.control.value),
        )
        self._pure_clean_cb = checkbox(
            self._t("right_panel.pure_clean_mode", "纯净扫描（移除模组方块/实体）"),
            value=mc.pure_clean_mode,
            on_change=lambda e: setattr(self.app.config.migration, 'pure_clean_mode', e.control.value),
        )
        self._batch_mode_cb = checkbox(
            self._t("right_panel.batch_mode", "批量处理模式"),
            value=mc.batch_mode,
            on_change=lambda e: self._toggle_batch(e.control.value),
        )

        cb_col = ft.Column(
            [self._offline_cb, self._clean_cb, self._pure_clean_cb, self._batch_mode_cb],
            spacing=8,
        )
        opt_s.controls.append(ft.Container(
            content=cb_col,
            padding=ft.Padding(left=20, right=20, top=12, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = opt_s
        return c

    # ─── 回调 ──────────────────────────────────

    def _sync_field_to_config(self) -> None:
        """将输入字段值同步到迁移配置"""
        mc = self.app.config.migration
        mc.src_path = self._src_field.value or ""
        mc.dest_path = self._dest_field.value or ""
        mc.world_name = self._name_field.value or "world"
        mc.batch_dir_path = self._batch_dir_field.value or ""
        mc.manual_names = self._manual_field.value or ""

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

    def _toggle_batch(self, enabled: bool) -> None:
        self.app.config.migration.batch_mode = enabled
        self._batch_card.visible = enabled
        self._batch_card.update()

    def _query_uuid(self) -> None:
        name = self._query_field.value.strip()
        if not name:
            return
        offline_uuid = self.app.uuid.generate_offline_uuid(name)
        online_uuid, official_name = self.app.uuid.query_online_uuid(name, self.app.log)

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
