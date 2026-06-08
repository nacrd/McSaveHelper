"""World Info Panel component"""
import flet as ft
import datetime
from typing import Callable, Dict, List, Optional

from app.ui.theme import THEME, mc_border
from app.ui.components.cards import card, placeholder

from core.omni.world_session import WorldInfo
from app.ui.views.explorer.utils import safe_update


class WorldInfoPanel(ft.Column):
    """存档信息展示面板 - 分组卡片式布局"""

    GAME_TYPE_MAP: Dict[int, str] = {
        0: "生存模式", 1: "创造模式", 2: "冒险模式", 3: "旁观模式"}
    DIFFICULTY_MAP: Dict[int, str] = {0: "和平", 1: "简单", 2: "普通", 3: "困难"}

    def __init__(
        self,
        t_cb: Optional[Callable[..., str]] = None,
        on_backup_click: Optional[Callable] = None,
        on_restore_click: Optional[Callable] = None,
    ) -> None:
        super().__init__(spacing=12, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self._t = t_cb or (lambda k, d="", **kw: d)
        self._on_backup_click = on_backup_click
        self._on_restore_click = on_restore_click

        # 美化的占位符
        self._placeholder = ft.Container(
            content=ft.Column([
                ft.Text("📦", size=48, text_align=ft.TextAlign.CENTER),
                ft.Container(height=12),
                ft.Text(
                    "请先设置当前存档以查看信息",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_secondary,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=8),
                ft.Text(
                    "通过侧边栏「设置当前存档」选择 Minecraft 世界目录",
                    size=13,
                    color=THEME.text_muted,
                    text_align=ft.TextAlign.CENTER,
                ),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=20, right=20, top=40, bottom=40),
            bgcolor=THEME.bg_card,
            border=mc_border(2),
        )
        self.controls = [self._placeholder]

    def update_info(self,
                    world_info: Optional[WorldInfo],
                    stats: Optional[Dict[str,
                                         int]] = None) -> None:
        """更新存档信息显示"""
        self.controls.clear()
        if world_info is None:
            self.controls.append(
                placeholder(
                    icon="⚠️",
                    title="未找到存档信息",
                    subtitle="该目录可能不是有效的 Minecraft 世界存档",
                    height=200,
                )
            )
            safe_update(self)
            return

        # ── 1. 基本信息 ──
        basic_rows = []
        if world_info.level_name:
            basic_rows.append(self._row("🏷️ 存档名称", world_info.level_name))
        if world_info.version_name:
            ver = world_info.version_name
            if world_info.version_snapshot:
                ver += "（快照）"
            if world_info.version_series:
                ver += f" | 系列: {world_info.version_series}"
            basic_rows.append(
                self._row(
                    "📦 游戏版本", f"{ver}（ID: {
                        world_info.version}）"))
        elif world_info.version:
            basic_rows.append(self._row("📦 游戏版本 ID", str(world_info.version)))

        gt = self.GAME_TYPE_MAP.get(
            world_info.game_type) if world_info.game_type is not None else None
        if gt:
            basic_rows.append(self._row("🎮 游戏模式", gt))

        diff = self.DIFFICULTY_MAP.get(
            world_info.difficulty) if world_info.difficulty is not None else None
        if diff is not None:
            basic_rows.append(self._row("⚔️ 难度", diff))

        if world_info.hardcore is not None:
            basic_rows.append(
                self._row(
                    "💀 极限模式",
                    "是" if world_info.hardcore else "否"))

        if world_info.allow_commands is not None:
            basic_rows.append(
                self._row(
                    "⌨️ 允许命令",
                    "是" if world_info.allow_commands else "否"))

        if world_info.was_modded is not None:
            basic_rows.append(
                self._row(
                    "🔧 使用过模组",
                    "是" if world_info.was_modded else "否"))

        if world_info.initialized is not None:
            basic_rows.append(
                self._row(
                    "✅ 已初始化",
                    "是" if world_info.initialized else "否"))

        if basic_rows:
            self.controls.append(self._section_card("📋 基本信息", basic_rows))

        # ── 2. 世界生成 ──
        gen_rows = []
        if world_info.seed is not None:
            gen_rows.append(self._row("🌱 世界种子", str(world_info.seed)))
        if world_info.spawn_x is not None:
            gen_rows.append(
                self._row(
                    "📍 出生点",
                    f"X: {
                        world_info.spawn_x}  Y: {
                        world_info.spawn_y}  Z: {
                        world_info.spawn_z}"))
        if gen_rows:
            self.controls.append(self._section_card("🌍 世界生成", gen_rows))

        # ── 3. 时间与天气 ──
        time_rows = []
        if world_info.last_played:
            try:
                dt = datetime.datetime.fromtimestamp(
                    world_info.last_played / 1000)
                time_rows.append(
                    self._row(
                        "🕐 最后游玩",
                        dt.strftime("%Y-%m-%d %H:%M:%S")))
            except Exception:
                time_rows.append(
                    self._row(
                        "🕐 最后游玩", str(
                            world_info.last_played)))
        if world_info.time is not None:
            ticks = int(world_info.time)
            days = ticks // 24000
            time_rows.append(self._row("⏱️ 总游戏时间", f"{ticks} 刻（约 {days} 天）"))
        if world_info.day_time is not None:
            dt_ticks = int(world_info.day_time) % 24000
            if dt_ticks < 6000:
                tod = "☀️ 白天"
            elif dt_ticks < 12000:
                tod = "🌅 日落"
            elif dt_ticks < 13000:
                tod = "🌙 夜晚"
            elif dt_ticks < 18000:
                tod = "🌙 深夜"
            elif dt_ticks < 23000:
                tod = "🌄 日出"
            else:
                tod = "☀️ 黎明"
            time_rows.append(self._row("🌞 当前时段", f"{tod}（{dt_ticks} 刻）"))
        if world_info.raining is not None:
            rain = "🌧️ 是" if world_info.raining else "☀️ 否"
            time_rows.append(self._row("🌧️ 正在下雨", rain))
        if world_info.thundering is not None:
            thunder = "⛈️ 是" if world_info.thundering else "☀️ 否"
            time_rows.append(self._row("⛈️ 正在雷暴", thunder))
        if time_rows:
            self.controls.append(self._section_card("⏰ 时间与天气", time_rows))

        # ── 4. 统计信息 ──
        stat_rows = []
        if stats:
            if stats.get("world_path"):
                stat_rows.append(
                    self._row(
                        "📂 存档路径", str(
                            stats.get("world_path"))))
            stat_rows.append(
                self._row(
                    "👥 玩家数", str(
                        stats.get(
                            "player_count", 0))))
            stat_rows.append(
                self._row(
                    "🧭 维度数", str(
                        stats.get(
                            "dimension_count", 0))))
            stat_rows.append(
                self._row(
                    "🗺️ 区域文件数", str(
                        stats.get(
                            "region_count", 0))))
        if stat_rows:
            self.controls.append(self._section_card("📊 统计信息", stat_rows))

        # ── 5. 数据包 ──
        if world_info.data_packs:
            dp_rows = []
            enabled = world_info.data_packs.get("enabled", [])
            disabled = world_info.data_packs.get("disabled", [])
            if enabled:
                dp_rows.append(self._row("✅ 已启用", ", ".join(
                    enabled[:10]) + ("..." if len(enabled) > 10 else "")))
            if disabled:
                dp_rows.append(self._row("❌ 已禁用", ", ".join(
                    disabled[:10]) + ("..." if len(disabled) > 10 else "")))
            if dp_rows:
                self.controls.append(self._section_card("📦 数据包", dp_rows))

        # ── 6. 其他信息 ──
        other_rows = []
        if world_info.server_brands:
            other_rows.append(
                self._row(
                    "🖥️ 服务器品牌", ", ".join(
                        str(b) for b in world_info.server_brands)))
        if other_rows:
            self.controls.append(self._section_card("🔧 其他", other_rows))

        # ── 7. 备份恢复 ──
        backup_buttons = ft.Row([
            ft.ElevatedButton(
                "📦 创建备份",
                icon=ft.Icons.BACKUP,
                bgcolor=THEME.accent,
                color=THEME.text_invert,
                on_click=self._on_backup_click,
            ),
            ft.ElevatedButton(
                "🔄 恢复备份",
                icon=ft.Icons.RESTORE,
                bgcolor=THEME.bg_card,
                color=THEME.text_primary,
                on_click=self._on_restore_click,
            ),
        ], spacing=12)
        self.controls.append(
            card(
                ft.Column([
                    ft.Text("🛡️ 备份与恢复", size=15, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                    ft.Divider(height=6, color=THEME.border_subtle),
                    ft.Text(
                        "创建存档备份以防数据丢失，或从之前的备份恢复",
                        size=12,
                        color=THEME.text_muted,
                    ),
                    ft.Container(height=8),
                    backup_buttons,
                ], spacing=6),
                padding=14,
            )
        )

        if not self.controls:
            self.controls.append(
                ft.Text(
                    "存档信息为空",
                    size=14,
                    color=THEME.text_muted,
                    text_align=ft.TextAlign.CENTER))
        safe_update(self)

    def _section_card(self, title: str, rows: List[ft.Row]) -> ft.Container:
        """创建分组信息卡片"""
        return card(
            ft.Column([
                ft.Text(title, size=15, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                ft.Divider(height=6, color=THEME.border_subtle),
                *rows,
            ], spacing=6),
            padding=14,
        )

    def _row(self, label: str, value: str) -> ft.Row:
        """创建一行信息"""
        return ft.Row([
            ft.Text(label, size=13, color=THEME.text_secondary, width=130),
            ft.Text(str(value), size=13, color=THEME.text_primary, selectable=True, expand=True),
        ], vertical_alignment=ft.CrossAxisAlignment.START)
