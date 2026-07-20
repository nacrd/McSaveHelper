"""Typed models for the player domain service."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from core.omni.player_manager import (
    PlayerAbilities,
    PlayerContainers,
    PlayerDeathLocation,
    PlayerPose,
    PlayerSpawn,
    PlayerState,
)

NbtPathPart = Union[str, int]
NbtPath = Tuple[NbtPathPart, ...]
ValueKind = str  # "float" | "int" | "str" | "bool"


@dataclass(frozen=True)
class PlayerEditSpec:
    """One editable player NBT field exposed to the UI form."""

    field_id: str
    nbt_path: NbtPath
    label_key: str
    value_kind: ValueKind
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    read_only: bool = False


@dataclass(frozen=True)
class PlayerRef:
    uuid_norm: str
    uuid_hyphen: str
    name: Optional[str]
    dat_path: Optional[Path] = None

    @property
    def display_name(self) -> str:
        return self.name or self.uuid_hyphen or self.uuid_norm


@dataclass(frozen=True)
class PlayerSummary:
    ref: PlayerRef
    state: PlayerState
    pose: PlayerPose
    spawn: PlayerSpawn
    death: Optional[PlayerDeathLocation]
    abilities: PlayerAbilities
    inventory_count: int
    ender_count: int
    equipment_count: int
    issues: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PlayerContainersView:
    """Service-level container view with dict items for UI grids."""

    inventory: Tuple[Dict[str, Any], ...]
    equipment: Tuple[Dict[str, Any], ...]
    ender_items: Tuple[Dict[str, Any], ...]
    selected_slot: Optional[int] = None

    @classmethod
    def from_containers(
        cls,
        containers: PlayerContainers,
        selected_slot: Optional[int] = None,
    ) -> "PlayerContainersView":
        return cls(
            inventory=tuple(item.to_dict() for item in containers.inventory),
            equipment=tuple(item.to_dict() for item in containers.equipment),
            ender_items=tuple(item.to_dict() for item in containers.ender_items),
            selected_slot=selected_slot,
        )


@dataclass(frozen=True)
class PlayerEditResult:
    """Outcome of building staged NBT changes from a form."""

    changes: Tuple[Any, ...]  # NbtChange, kept loose to avoid cycles
    errors: Tuple[str, ...] = ()
    staged_count: int = 0


@dataclass(frozen=True)
class PlayerExportBundle:
    summary: PlayerSummary
    containers: PlayerContainersView
    items_included: bool = True

    def to_dict(self) -> Dict[str, Any]:
        ref = self.summary.ref
        state = self.summary.state
        pose = self.summary.pose
        spawn = self.summary.spawn
        death = self.summary.death
        abilities = self.summary.abilities
        payload: Dict[str, Any] = {
            "uuid": ref.uuid_hyphen or ref.uuid_norm,
            "uuid_norm": ref.uuid_norm,
            "name": ref.name,
            "dat_path": str(ref.dat_path) if ref.dat_path else None,
            "state": {
                "health": state.health,
                "food_level": state.food_level,
                "food_saturation": state.food_saturation,
                "xp_level": state.xp_level,
                "xp_total": state.xp_total,
                "xp_p": state.xp_p,
                "air": state.air,
                "dimension": state.dimension,
                "game_type": state.game_type,
                "selected_slot": state.selected_slot,
                "score": state.score,
            },
            "pose": {
                "x": pose.x,
                "y": pose.y,
                "z": pose.z,
                "yaw": pose.yaw,
                "pitch": pose.pitch,
            },
            "spawn": {
                "x": spawn.x,
                "y": spawn.y,
                "z": spawn.z,
                "dimension": spawn.dimension,
                "forced": spawn.forced,
            },
            "death": None
            if death is None
            else {
                "dimension": death.dimension,
                "x": death.x,
                "y": death.y,
                "z": death.z,
            },
            "abilities": {
                "flying": abilities.flying,
                "may_fly": abilities.may_fly,
                "instabuild": abilities.instabuild,
                "invulnerable": abilities.invulnerable,
                "may_build": abilities.may_build,
                "walk_speed": abilities.walk_speed,
                "fly_speed": abilities.fly_speed,
            },
            "counts": {
                "inventory": self.summary.inventory_count,
                "ender": self.summary.ender_count,
                "equipment": self.summary.equipment_count,
            },
            "issues": list(self.summary.issues),
        }
        if self.items_included:
            payload["inventory"] = list(self.containers.inventory)
            payload["equipment"] = list(self.containers.equipment)
            payload["ender_items"] = list(self.containers.ender_items)
        return payload


# Field registry — single source of paths for form + stage.
PLAYER_EDIT_SPECS: Tuple[PlayerEditSpec, ...] = (
    PlayerEditSpec("Health", ("Health",), "player.edit.health", "float", 0, 1024),
    PlayerEditSpec(
        "foodLevel", ("foodLevel",), "player.edit.food", "int", 0, 20
    ),
    PlayerEditSpec(
        "foodSaturationLevel",
        ("foodSaturationLevel",),
        "player.edit.saturation",
        "float",
        0,
        20,
    ),
    PlayerEditSpec(
        "XpLevel", ("XpLevel",), "player.edit.xp_level", "int", 0, None
    ),
    PlayerEditSpec(
        "XpTotal", ("XpTotal",), "player.edit.xp_total", "int", 0, None
    ),
    PlayerEditSpec("XpP", ("XpP",), "player.edit.xp_p", "float", 0, 1),
    PlayerEditSpec("Air", ("Air",), "player.edit.air", "int", 0, 300),
    PlayerEditSpec("Pos.0", ("Pos", 0), "player.edit.pos_x", "float"),
    PlayerEditSpec("Pos.1", ("Pos", 1), "player.edit.pos_y", "float"),
    PlayerEditSpec("Pos.2", ("Pos", 2), "player.edit.pos_z", "float"),
    PlayerEditSpec(
        "Dimension", ("Dimension",), "player.edit.dimension", "str"
    ),
    PlayerEditSpec(
        "playerGameType",
        ("playerGameType",),
        "player.edit.game_type",
        "int",
        0,
        3,
    ),
    PlayerEditSpec(
        "SelectedItemSlot",
        ("SelectedItemSlot",),
        "player.edit.selected_slot",
        "int",
        0,
        8,
    ),
    PlayerEditSpec("SpawnX", ("SpawnX",), "player.edit.spawn_x", "int"),
    PlayerEditSpec("SpawnY", ("SpawnY",), "player.edit.spawn_y", "int"),
    PlayerEditSpec("SpawnZ", ("SpawnZ",), "player.edit.spawn_z", "int"),
    PlayerEditSpec(
        "SpawnDimension",
        ("SpawnDimension",),
        "player.edit.spawn_dimension",
        "str",
    ),
    PlayerEditSpec(
        "SpawnForced",
        ("SpawnForced",),
        "player.edit.spawn_forced",
        "bool",
    ),
    PlayerEditSpec(
        "abilities.flying",
        ("abilities", "flying"),
        "player.edit.flying",
        "bool",
    ),
    PlayerEditSpec(
        "abilities.mayfly",
        ("abilities", "mayfly"),
        "player.edit.mayfly",
        "bool",
    ),
    PlayerEditSpec(
        "abilities.instabuild",
        ("abilities", "instabuild"),
        "player.edit.instabuild",
        "bool",
    ),
    PlayerEditSpec(
        "abilities.invulnerable",
        ("abilities", "invulnerable"),
        "player.edit.invulnerable",
        "bool",
    ),
    PlayerEditSpec(
        "abilities.mayBuild",
        ("abilities", "mayBuild"),
        "player.edit.may_build",
        "bool",
    ),
    PlayerEditSpec(
        "abilities.walkSpeed",
        ("abilities", "walkSpeed"),
        "player.edit.walk_speed",
        "float",
        0,
        1,
    ),
    PlayerEditSpec(
        "abilities.flySpeed",
        ("abilities", "flySpeed"),
        "player.edit.fly_speed",
        "float",
        0,
        1,
    ),
)

_SPECS_BY_ID: Dict[str, PlayerEditSpec] = {
    spec.field_id: spec for spec in PLAYER_EDIT_SPECS
}


def get_edit_spec(field_id: str) -> Optional[PlayerEditSpec]:
    return _SPECS_BY_ID.get(field_id)
