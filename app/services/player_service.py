"""Player service — list / summary / containers / edit proposals / export."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from core.nbt import Compound

from app.models.nbt_edit import NbtChange
from app.services.player.models import (
    PLAYER_EDIT_SPECS,
    PlayerContainersView,
    PlayerEditResult,
    PlayerEditSpec,
    PlayerExportBundle,
    PlayerRef,
    PlayerSummary,
    get_edit_spec,
)
from app.services.nbt_value_utils import coerce_like_tag, tag_display_value
from core.omni.player_manager import (
    PlayerAttribute,
    PlayerEffect,
    PlayerManager,
)
from core.omni.world_session import WorldSession
from core.uuid_utils import format_uuid_with_hyphens, normalize_uuid


LogCallback = Callable[[str, str], None]


class PlayerService:
    """Explorer 玩家列表/摘要/容器/编辑提案/导出应用服务。

    无会话级缓存；每次调用通过 ``WorldSession`` 读 NBT，不直接写盘。
    """

    def __init__(self, log: Optional[LogCallback] = None) -> None:
        """注入可选日志回调。

        Args:
            log: ``(message, level)`` 日志；缺省为 no-op。
        """
        def _default_log(msg: str, lvl: str = "INFO") -> None:
            return None

        self._log: LogCallback = log or _default_log

    def list_players(self, session: WorldSession) -> List[PlayerRef]:
        """列出世界内全部玩家引用并按显示名排序。

        Args:
            session: 当前世界会话。

        Returns:
            按显示名与 UUID 排序的 ``PlayerRef`` 列表。
        """
        refs: List[PlayerRef] = []
        names = session.get_player_names()
        for uuid in session.get_player_uuids():
            norm = normalize_uuid(uuid)
            refs.append(
                PlayerRef(
                    uuid_norm=norm,
                    uuid_hyphen=format_uuid_with_hyphens(norm),
                    name=names.get(uuid) or session.get_known_player_name(norm),
                    dat_path=session.get_player_file_path(norm),
                )
            )
        refs.sort(key=lambda ref: (ref.display_name.lower(), ref.uuid_norm))
        return refs

    def load_summary(
        self,
        session: WorldSession,
        uuid: str,
    ) -> Optional[PlayerSummary]:
        """加载玩家摘要（状态、姿态、出生/死亡点、能力与问题标记）。

        Args:
            session: 当前世界会话。
            uuid: 玩家 UUID（任意连字符形式）。

        Returns:
            摘要；玩家数据与 ``.dat`` 路径均不存在时为 None。
        """
        data = session.get_player_data(uuid)
        if data is None and session.get_player_file_path(uuid) is None:
            return None
        manager = PlayerManager(log_callback=self._log)
        # Seed names from session so summary uses known display names.
        manager.seed_names(session.get_player_names())
        identity = manager.extract_identity(uuid, data)
        state = manager.extract_state(data)
        pose = manager.extract_pose(data)
        spawn = manager.extract_spawn(data)
        death = manager.extract_death(data)
        abilities = manager.extract_abilities(data)
        containers = manager.extract_containers(data)
        issues = self._collect_issues(state, data)
        return PlayerSummary(
            ref=PlayerRef(
                uuid_norm=identity.uuid_norm,
                uuid_hyphen=identity.uuid_hyphen,
                name=identity.name,
                dat_path=session.get_player_file_path(identity.uuid_norm),
            ),
            state=state,
            pose=pose,
            spawn=spawn,
            death=death,
            abilities=abilities,
            inventory_count=len(containers.inventory),
            ender_count=len(containers.ender_items),
            equipment_count=len(containers.equipment),
            issues=tuple(issues),
        )

    def load_containers(
        self,
        session: WorldSession,
        uuid: str,
    ) -> Optional[PlayerContainersView]:
        """加载背包、装备与末影箱视图。

        Args:
            session: 当前世界会话。
            uuid: 玩家 UUID。

        Returns:
            容器视图；玩家不存在时为 None。
        """
        data = session.get_player_data(uuid)
        if data is None and session.get_player_file_path(uuid) is None:
            return None
        manager = PlayerManager(log_callback=self._log)
        containers = manager.extract_containers(data)
        state = manager.extract_state(data)
        return PlayerContainersView.from_containers(
            containers,
            selected_slot=state.selected_slot,
        )

    def load_attributes(
        self,
        session: WorldSession,
        uuid: str,
    ) -> tuple[PlayerAttribute, ...]:
        """提取玩家属性列表。

        Args:
            session: 当前世界会话。
            uuid: 玩家 UUID。

        Returns:
            属性元组；无数据时可能为空。
        """
        data = session.get_player_data(uuid)
        return PlayerManager(log_callback=self._log).extract_attributes(data)

    def load_effects(
        self,
        session: WorldSession,
        uuid: str,
    ) -> tuple[PlayerEffect, ...]:
        """提取玩家状态效果列表。

        Args:
            session: 当前世界会话。
            uuid: 玩家 UUID。

        Returns:
            效果元组；无数据时可能为空。
        """
        data = session.get_player_data(uuid)
        return PlayerManager(log_callback=self._log).extract_effects(data)

    def open_nested_container(
        self,
        item: Dict[str, Any],
    ) -> Optional[List[Dict[str, Any]]]:
        """Return nested items if ``item`` is a shulker/bundle; else None."""
        item_id = str(item.get("id", "") or "")
        nested = PlayerManager.extract_nested_container_items(item)
        if nested:
            return nested
        if PlayerManager.is_container_item(item_id):
            return []
        return None

    def build_edit_changes(
        self,
        uuid: str,
        player_data: Any,
        field_values: Mapping[str, str],
        *,
        specs: Optional[Sequence[PlayerEditSpec]] = None,
        target_label: Optional[str] = None,
    ) -> PlayerEditResult:
        """从表单字段值构建暂存 ``NbtChange`` 列表。

        Args:
            uuid: 玩家 UUID（任意连字符形式）。
            player_data: 当前玩家 NBT 根。
            field_values: ``field_id ->`` 表单原始字符串。
            specs: 可选字段规格子集；默认使用全部可编辑规格。
            target_label: 变更展示标签；默认 ``player:<uuid>``。

        Returns:
            PlayerEditResult: 变更列表与校验/路径错误。
        """
        if player_data is None:
            return PlayerEditResult(changes=(), errors=("missing_player_data",))

        norm = normalize_uuid(uuid)
        label = target_label or f"player:{format_uuid_with_hyphens(norm)}"
        selected_specs = (
            list(specs) if specs is not None else list(PLAYER_EDIT_SPECS)
        )
        changes: List[NbtChange] = []
        errors: List[str] = []

        for spec in selected_specs:
            change_or_error = self._change_for_field(
                uuid=uuid,
                player_data=player_data,
                field_values=field_values,
                spec=spec,
                label=label,
            )
            if change_or_error is None:
                continue
            if isinstance(change_or_error, str):
                errors.append(change_or_error)
                continue
            changes.append(change_or_error)

        return PlayerEditResult(
            changes=tuple(changes),
            errors=tuple(errors),
            staged_count=len(changes),
        )

    def _change_for_field(
        self,
        *,
        uuid: str,
        player_data: Any,
        field_values: Mapping[str, str],
        spec: PlayerEditSpec,
        label: str,
    ) -> NbtChange | str | None:
        """为单个字段生成变更，或返回错误码字符串，或跳过。"""
        if spec.read_only or spec.field_id not in field_values:
            return None
        raw = field_values[spec.field_id]
        if raw is None or str(raw).strip() == "":
            return None

        validation_error = self._validate_field(spec, str(raw))
        if validation_error:
            return f"{spec.field_id}:{validation_error}"

        try:
            old_value = self._get_tag_at_path(player_data, list(spec.nbt_path))
        except (KeyError, IndexError, TypeError):
            return f"{spec.field_id}:path_missing"

        try:
            new_value = coerce_like_tag(str(raw), old_value)
        except (TypeError, ValueError) as exc:
            return f"{spec.field_id}:coerce:{exc}"
        except Exception as exc:
            # NBT 解析可能抛出库专属类型错误。
            return f"{spec.field_id}:coerce:{exc}"

        if tag_display_value(old_value) == tag_display_value(new_value):
            return None

        return NbtChange.create(
            target=uuid,
            target_label=label,
            format="nbt",
            path=spec.nbt_path,
            display_path=".".join(str(part) for part in spec.nbt_path),
            old_value=old_value,
            new_value=new_value,
        )

    def build_teleport_to_death_changes(
        self,
        uuid: str,
        player_data: Any,
        *,
        target_label: Optional[str] = None,
    ) -> PlayerEditResult:
        """根据 ``LastDeathLocation`` 生成传送到死亡点的暂存变更。

        Args:
            uuid: 玩家 UUID。
            player_data: 当前玩家 NBT。
            target_label: 可选变更展示标签。

        Returns:
            PlayerEditResult: 位置/维度变更；无死亡点时返回错误码
            ``no_death_location``。
        """
        if player_data is None:
            return PlayerEditResult(changes=(), errors=("missing_player_data",))
        manager = PlayerManager(log_callback=self._log)
        death = manager.extract_death(player_data)
        if (
            death is None
            or death.x is None
            or death.y is None
            or death.z is None
        ):
            return PlayerEditResult(changes=(), errors=("no_death_location",))

        field_values = {
            "Pos.0": str(death.x),
            "Pos.1": str(death.y),
            "Pos.2": str(death.z),
        }
        if death.dimension:
            field_values["Dimension"] = death.dimension
        return self.build_edit_changes(
            uuid,
            player_data,
            field_values,
            specs=[
                spec
                for spec in PLAYER_EDIT_SPECS
                if spec.field_id in field_values
            ],
            target_label=target_label,
        )

    def build_export(
        self,
        session: WorldSession,
        uuid: str,
        *,
        include_items: bool = True,
    ) -> Optional[PlayerExportBundle]:
        """构建玩家导出包。

        Args:
            session: 当前世界会话。
            uuid: 玩家 UUID。
            include_items: 是否附带物品列表。

        Returns:
            PlayerExportBundle | None: 玩家不存在时为 None。
        """
        summary = self.load_summary(session, uuid)
        if summary is None:
            return None
        containers = self.load_containers(session, uuid)
        if containers is None:
            containers = PlayerContainersView(
                inventory=(),
                equipment=(),
                ender_items=(),
            )
        return PlayerExportBundle(
            summary=summary,
            containers=containers,
            items_included=include_items,
        )

    def form_values_from_data(
        self,
        player_data: Any,
        *,
        specs: Optional[Sequence[PlayerEditSpec]] = None,
    ) -> Dict[str, str]:
        """从表数据读取字段当前值，供表单回填。

        Args:
            player_data: 玩家 NBT 根。
            specs: 可选字段规格子集。

        Returns:
            dict[str, str]: ``field_id ->`` 显示字符串；缺失路径为空串。
        """
        values: Dict[str, str] = {}
        if player_data is None:
            return values
        for spec in specs or PLAYER_EDIT_SPECS:
            try:
                value = self._get_tag_at_path(
                    player_data,
                    list(spec.nbt_path),
                )
                values[spec.field_id] = tag_display_value(value)
            except (KeyError, IndexError, TypeError):
                values[spec.field_id] = ""
        return values

    @staticmethod
    def edit_specs() -> Sequence[PlayerEditSpec]:
        """返回全部可编辑字段规格。

        Returns:
            ``PLAYER_EDIT_SPECS`` 序列。
        """
        return PLAYER_EDIT_SPECS

    @staticmethod
    def get_spec(field_id: str) -> Optional[PlayerEditSpec]:
        """按字段 id 查找编辑规格。

        Args:
            field_id: 表单字段标识。

        Returns:
            规格；未知 id 时为 None。
        """
        return get_edit_spec(field_id)

    def _collect_issues(
        self,
        state: Any,
        data: Optional[Compound],
    ) -> List[str]:
        issues: List[str] = []
        if data is None:
            issues.append("load_failed")
            return issues
        if state.health is not None and state.health <= 0:
            issues.append("zero_health")
        if state.food_level is not None and state.food_level <= 0:
            issues.append("starving")
        return issues

    @staticmethod
    def _get_tag_at_path(data: Any, path: List[Union[str, int]]) -> Any:
        node = data
        for part in path:
            node = node[part]
        return node

    @staticmethod
    def _validate_field(spec: PlayerEditSpec, raw: str) -> Optional[str]:
        text = raw.strip()
        if spec.value_kind == "str":
            return None
        if spec.value_kind == "bool":
            lowered = text.lower()
            if lowered in {"0", "1", "true", "false", "yes", "no"}:
                return None
            try:
                int(float(text))
                return None
            except ValueError:
                return "invalid_bool"
        try:
            number = float(text) if spec.value_kind == "float" else int(float(text))
        except ValueError:
            return "invalid_number"
        if spec.min_value is not None and number < spec.min_value:
            return "below_min"
        if spec.max_value is not None and number > spec.max_value:
            return "above_max"
        return None
