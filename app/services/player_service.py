"""Player service — list / summary / containers / edit proposals / export."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from nbtlib import Compound

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
from core.omni.player_manager import PlayerManager
from core.omni.world_session import WorldSession
from core.uuid_utils import format_uuid_with_hyphens, normalize_uuid


LogCallback = Callable[[str, str], None]


class PlayerService:
    """Application service for Explorer player features."""

    def __init__(self, log: Optional[LogCallback] = None) -> None:
        self._log = log or (lambda msg, lvl="INFO": None)

    def list_players(self, session: WorldSession) -> List[PlayerRef]:
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

    def build_edit_changes(
        self,
        uuid: str,
        player_data: Any,
        field_values: Mapping[str, str],
        *,
        specs: Optional[Sequence[PlayerEditSpec]] = None,
        target_label: Optional[str] = None,
    ) -> PlayerEditResult:
        """Build staged NbtChange list from form field_id -> raw string values."""
        if player_data is None:
            return PlayerEditResult(changes=(), errors=("missing_player_data",))

        norm = normalize_uuid(uuid)
        label = target_label or f"player:{format_uuid_with_hyphens(norm)}"
        selected_specs = list(specs) if specs is not None else list(PLAYER_EDIT_SPECS)
        changes: List[NbtChange] = []
        errors: List[str] = []

        for spec in selected_specs:
            if spec.read_only:
                continue
            if spec.field_id not in field_values:
                continue
            raw = field_values[spec.field_id]
            if raw is None or str(raw).strip() == "":
                continue

            validation_error = self._validate_field(spec, str(raw))
            if validation_error:
                errors.append(f"{spec.field_id}:{validation_error}")
                continue

            try:
                old_value = self._get_tag_at_path(player_data, list(spec.nbt_path))
            except (KeyError, IndexError, TypeError):
                errors.append(f"{spec.field_id}:path_missing")
                continue

            try:
                new_value = coerce_like_tag(str(raw), old_value)
            except Exception as exc:
                errors.append(f"{spec.field_id}:coerce:{exc}")
                continue

            if tag_display_value(old_value) == tag_display_value(new_value):
                continue

            changes.append(
                NbtChange.create(
                    target=uuid,
                    target_label=label,
                    format="nbt",
                    path=spec.nbt_path,
                    display_path=".".join(str(part) for part in spec.nbt_path),
                    old_value=old_value,
                    new_value=new_value,
                )
            )

        return PlayerEditResult(
            changes=tuple(changes),
            errors=tuple(errors),
            staged_count=len(changes),
        )

    def build_teleport_to_death_changes(
        self,
        uuid: str,
        player_data: Any,
        *,
        target_label: Optional[str] = None,
    ) -> PlayerEditResult:
        """Stage Pos + Dimension updates from LastDeathLocation."""
        if player_data is None:
            return PlayerEditResult(changes=(), errors=("missing_player_data",))
        manager = PlayerManager(log_callback=self._log)
        death = manager.extract_death(player_data)
        if death is None or death.x is None or death.y is None or death.z is None:
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
        """Read current field values for form population."""
        values: Dict[str, str] = {}
        if player_data is None:
            return values
        for spec in specs or PLAYER_EDIT_SPECS:
            try:
                value = self._get_tag_at_path(player_data, list(spec.nbt_path))
                values[spec.field_id] = tag_display_value(value)
            except (KeyError, IndexError, TypeError):
                values[spec.field_id] = ""
        return values

    @staticmethod
    def edit_specs() -> Sequence[PlayerEditSpec]:
        return PLAYER_EDIT_SPECS

    @staticmethod
    def get_spec(field_id: str) -> Optional[PlayerEditSpec]:
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
