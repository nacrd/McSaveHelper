"""Migrator view - main conversion interface"""
import flet as ft
from typing import TYPE_CHECKING, Optional, Callable, Any
from ui.constants import COLORS
from ui.widgets import card, section_title, label, btn_primary, btn_ghost, text_field, checkbox, LogPanel
from core.i18n import t

if TYPE_CHECKING:
    from ui.app import App


class MigratorView(ft.Column):
    def __init__(self, app: "App") -> None:
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app: "App" = app
        self._build()

    def _build(self) -> None:
        self.controls.clear()
        content = ft.Row([
            self._build_left(),
            ft.Container(width=18),
            self._build_right(),
        ], expand=True, vertical_alignment=ft.CrossAxisAlignment.START)
        self.controls.append(content)

    def _build_left(self) -> ft.Column:
        col = ft.Column(spacing=18)
        col.expand = True

        dir_col = ft.Column(spacing=0)
        dir_col.expand = True
        dir_card = card(dir_col, padding=0)
        dir_sections = ft.Column(spacing=0)
        dir_sections.controls.append(section_title(
            t("left_panel.archive_config", "📁 存档目录配置")))

        self._src_field = text_field(
            label=t("left_panel.client_archive", "客户端存档"),
            hint_text=t("left_panel.placeholder_select_world", "选择世界文件夹 (包含 level.dat)"),
            on_change=lambda e: setattr(self.app, 'src_path', e.control.value),
        )
        btn_row1 = ft.Row([self._src_field,
                           btn_ghost(t("left_panel.browse", "📂 浏览"), width=90, height=38,
                                     on_click=self.app.choose_src)], spacing=10)
        dir_sections.controls.append(
            ft.Container(content=btn_row1, padding=ft.padding.only(left=20, right=20, bottom=8)))

        self._dest_field = text_field(
            label=t("left_panel.server_root", "服务端根目录"),
            hint_text=t("left_panel.placeholder_default_dir", "默认为程序当前目录"),
            on_change=lambda e: setattr(self.app, 'dest_path', e.control.value),
        )
        btn_row2 = ft.Row([self._dest_field,
                           btn_ghost(t("left_panel.browse", "📂 浏览"), width=90, height=38,
                                     on_click=self.app.choose_dest)], spacing=10)
        dir_sections.controls.append(
            ft.Container(content=btn_row2, padding=ft.padding.only(left=20, right=20, bottom=8)))

        self._name_field = text_field(
            label=t("left_panel.world_folder_name", "世界文件夹名"),
            hint_text=t("left_panel.placeholder_world_name", "例如: world"),
            on_change=lambda e: setattr(self.app, 'world_name', e.control.value),
        )
        dir_sections.controls.append(
            ft.Container(content=self._name_field, padding=ft.padding.only(left=20, right=20, bottom=18)))
        dir_card.content = dir_sections
        col.controls.append(dir_card)

        self._batch_card: ft.Container = card(ft.Column(spacing=8), padding=0)
        batch_s = ft.Column(spacing=0)
        batch_s.controls.append(section_title(
            t("left_panel.batch_archive_dir", "批量存档目录")))
        bf = ft.Column(spacing=8)
        self._batch_dir_field = text_field(
            label="",
            hint_text=t("left_panel.placeholder_batch_dir", "选择包含多个世界存档的目录"),
            on_change=lambda e: setattr(self.app, 'batch_dir_path', e.control.value),
        )
        br = ft.Row([
            self._batch_dir_field,
            btn_ghost(t("left_panel.browse", "📂 浏览"), width=90, height=38,
                      on_click=self.app.choose_batch_dir),
            btn_primary(t("left_panel.scan", "🔍 扫描"), width=90, height=38,
                        on_click=lambda e: self.app.scan_batch_worlds()),
        ], spacing=10)
        bf.controls.append(br)
        self._batch_result: ft.Text = ft.Text("", size=11, color=COLORS["text_muted"])
        bf.controls.append(self._batch_result)
        batch_s.controls.append(
            ft.Container(content=bf, padding=ft.padding.only(left=20, right=20, bottom=18)))
        self._batch_card.content = batch_s
        self._batch_card.visible = False
        col.controls.append(self._batch_card)

        manual_card = card(ft.Column(spacing=0), padding=0)
        manual_s = ft.Column(spacing=0)
        manual_s.controls.append(section_title(
            t("left_panel.manual_players", "👥 手动指定玩家 (选填)")))
        self._manual_field = text_field(
            hint_text=t("left_panel.placeholder_manual_names",
                        "多个玩家用英文逗号分隔，例如: Steve, Alex"),
            on_change=lambda e: setattr(self.app, 'manual_names', e.control.value),
        )
        manual_s.controls.append(
            ft.Container(content=self._manual_field, padding=ft.padding.only(left=20, right=20, bottom=18)))
        manual_card.content = manual_s
        col.controls.append(manual_card)

        log_header = ft.Row([
            ft.Text(t("left_panel.run_log", "📋 运行日志"), size=15,
                    weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
            btn_ghost(t("left_panel.clear_log", "🗑️ 清空"), width=80, height=32,
                      on_click=lambda e: self.app.clear_log()),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        log_card = card(ft.Column([
            log_header,
            ft.Container(content=self.app.log_panel, bgcolor=COLORS["log_bg"],
                         border=ft.border.all(1, COLORS["log_border"]),
                         border_radius=8, padding=8, expand=True),
        ], spacing=8), padding=15)
        col.controls.append(log_card)

        return col

    def _build_right(self) -> ft.Column:
        col = ft.Column(spacing=18)
        col.expand = True

        mode_card = card(ft.Column(spacing=0), padding=0)
        mode_s = ft.Column(spacing=0)
        mode_s.controls.append(section_title(
            t("right_panel.mode_settings", "模式设置")))

        def mode_changed(e: ft.ControlEvent) -> None:
            self.app.mode = e.control.value

        self._mode_fast: ft.Radio = ft.Radio(
            value="fast", label=t("right_panel.fast_mode", "⚡ 快速模式"))
        self._mode_full: ft.Radio = ft.Radio(
            value="full", label=t("right_panel.full_mode", "🧠 完整模式"))
        mode_group = ft.RadioGroup(
            content=ft.Row([self._mode_fast, self._mode_full], spacing=30),
            value=self.app.mode, on_change=mode_changed,  # type: ignore[arg-type]
        )
        mode_s.controls.append(
            ft.Container(content=mode_group, padding=ft.padding.only(left=20, right=20, top=12, bottom=8)))
        mode_s.controls.append(
            ft.Container(
                content=ft.Text(
                    t("right_panel.mode_description",
                      "快速模式：仅复制UUID文件；完整模式：深度NBT修补"),
                    size=11, color=COLORS["text_muted"]),
                padding=ft.padding.only(left=20, right=20, bottom=18)))
        mode_card.content = mode_s
        col.controls.append(mode_card)

        uuid_card = card(ft.Column(spacing=0), padding=0)
        uuid_s = ft.Column(spacing=0)
        uuid_s.controls.append(section_title(
            t("right_panel.uuid_query", "UUID 查询")))

        def query_click(e: ft.ControlEvent) -> None:
            result = self.app.query_uuid()
            if result:
                self._query_result.value = result
                self._query_result.update()

        def name_changed(e: ft.ControlEvent) -> None:
            self.app.query_name = e.control.value

        self._query_field = text_field(
            hint_text=t("right_panel.placeholder_player_name", "输入玩家名"),
            expand=True, on_change=name_changed,
        )
        qr = ft.Row([
            self._query_field,
            btn_primary(t("right_panel.query_button", "查询"), width=90, height=38, on_click=query_click),
        ], spacing=10)
        uuid_s.controls.append(
            ft.Container(content=qr, padding=ft.padding.only(left=20, right=20, top=12, bottom=8)))
        self._query_result: ft.Text = ft.Text(
            t("right_panel.query_result_placeholder", "在此显示查询结果"),
            size=11, color=COLORS["text_muted"])
        rb = ft.Container(
            content=self._query_result, bgcolor=COLORS["log_bg"],
            border=ft.border.all(1, COLORS["log_border"]), border_radius=8,
            padding=12, height=110,
        )
        uuid_s.controls.append(
            ft.Container(content=rb, padding=ft.padding.only(left=20, right=20, bottom=18)))
        uuid_card.content = uuid_s
        col.controls.append(uuid_card)

        opt_card = card(ft.Column(spacing=0), padding=0)
        opt_s = ft.Column(spacing=0)
        opt_s.controls.append(section_title(
            t("right_panel.migration_options", "迁移选项")))

        def offline_changed(e: ft.ControlEvent) -> None:
            self.app.offline_mode = e.control.value

        def clean_changed(e: ft.ControlEvent) -> None:
            self.app.clean_mode = e.control.value

        def pure_changed(e: ft.ControlEvent) -> None:
            self.app.pure_clean_mode = e.control.value

        def batch_changed(e: ft.ControlEvent) -> None:
            self.app.batch_mode = e.control.value
            self._batch_card.visible = e.control.value
            self.update()

        opts = ft.Column(spacing=6)
        self._offline_cb: ft.Checkbox = checkbox(
            t("right_panel.offline_mode", "仅离线模式"), on_change=offline_changed)
        self._clean_cb: ft.Checkbox = checkbox(
            t("right_panel.clean_mode", "清理缓存/日志"), value=True, on_change=clean_changed)
        self._pure_cb: ft.Checkbox = checkbox(
            t("right_panel.pure_clean_mode", "纯净清理（移除模组内容）"), on_change=pure_changed)
        self._batch_cb: ft.Checkbox = checkbox(
            t("right_panel.batch_mode", "批量处理模式"), on_change=batch_changed)
        opts.controls.extend([self._offline_cb, self._clean_cb, self._pure_cb, self._batch_cb])
        opt_s.controls.append(
            ft.Container(content=opts, padding=ft.padding.only(left=20, right=20, top=12, bottom=18)))
        opt_card.content = opt_s
        col.controls.append(opt_card)

        adv_card = card(ft.Column(spacing=0), padding=0)
        adv_s = ft.Column(spacing=0)
        adv_s.controls.append(section_title(
            t("right_panel.advanced_settings", "高级设置")))

        def version_changed(e: ft.ControlEvent) -> None:
            self.app.version_detection = e.control.value
            self.app._save_config()

        def concurrent_changed(e: ft.ControlEvent) -> None:
            try:
                self.app.max_concurrent = int(e.control.value)
                self.app._save_config()
            except ValueError:
                pass

        adv_items = ft.Column(spacing=8)
        self._version_cb: ft.Checkbox = checkbox(
            t("right_panel.version_detection", "启用版本自动检测"),
            value=self.app.version_detection, on_change=version_changed,
        )
        adv_items.controls.append(self._version_cb)
        conc_row = ft.Row([
            ft.Text(t("right_panel.max_concurrent", "最大并发数 (1-16)"), size=12,
                    weight=ft.FontWeight.BOLD, color=COLORS["text_secondary"]),
            text_field(value=str(self.app.max_concurrent), width=60, expand=False,
                       on_change=concurrent_changed),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        adv_items.controls.append(conc_row)
        adv_s.controls.append(
            ft.Container(content=adv_items, padding=ft.padding.only(left=20, right=20, top=12, bottom=18)))
        adv_card.content = adv_s
        col.controls.append(adv_card)

        map_card = card(ft.Column(spacing=0), padding=0)
        map_s = ft.Column(spacing=0)
        map_s.controls.append(section_title(
            t("right_panel.custom_mapping_rules", "⚙️ 自定义映射规则")))

        def use_map_changed(e: ft.ControlEvent) -> None:
            self.app.use_custom_mapping = e.control.value
            self.app._save_config()

        self._use_map_cb: ft.Checkbox = checkbox(
            t("right_panel.enable_custom_mapping", "启用自定义映射规则"),
            value=self.app.use_custom_mapping, on_change=use_map_changed,
        )
        map_items = ft.Column(spacing=8)
        map_items.controls.append(self._use_map_cb)

        map_items.controls.append(
            ft.Row([
                btn_primary(t("right_panel.quick_scan_and_match", "🔍 快速扫描并匹配"), height=38,
                            on_click=lambda e: self.app._switch_to_mappings_view()),
                ft.TextButton(
                    content=t("right_panel.edit_rules", "编辑详细规则..."),
                    style=ft.ButtonStyle(color=COLORS["accent_light"]),
                    on_click=lambda e: self.app._switch_to_mappings_view()),
            ], spacing=10),
        )
        self._scan_result: ft.Text = ft.Text("", size=11, color=COLORS["text_muted"])
        map_items.controls.append(self._scan_result)
        map_s.controls.append(
            ft.Container(content=map_items, padding=ft.padding.only(left=20, right=20, top=12, bottom=18)))
        map_card.content = map_s
        col.controls.append(map_card)

        return col
