from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import normalize_lane_key, utcnow_iso
from .state import ControlStore


_DATED_ARCHIVE = re.compile(
    r"(?:^|[_-])20\d{2}(?:[-_]?\d{2}){2}(?:[_-]|$)",
    re.IGNORECASE,
)
_LANE_HEADER = re.compile(
    r"^\s*(?:[-*]\s+)?\*\*Lane:\*\*\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_lane_identity(path: Path, suffix: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = _LANE_HEADER.search(text)
    if match:
        return normalize_lane_key(match.group(1))
    fallback = suffix.replace("_", " ")
    return normalize_lane_key(fallback)


def _handover_paths_equal(left: str | None, right: Path) -> bool:
    if not left:
        return False
    try:
        return Path(left).resolve() == right.resolve()
    except OSError:
        return False


def _lane_is_empty(store: ControlStore, lane_key: str) -> bool:
    lane = store.get_lane(lane_key)
    if lane is None:
        return True
    if lane.current_agent_id:
        return False
    return not any(task.lane_key == lane.lane_key for task in store.list_tasks())


def bootstrap_handovers(
    store: ControlStore,
    workspace: Path,
    *,
    include_brain: bool = False,
) -> dict[str, Any]:
    root = workspace.resolve()
    if root != Path(store.workspace).resolve():
        raise ValueError("Bootstrap workspace must match coordinator workspace")
    imported: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file():
            continue
        if not path.name.upper().startswith("SESSION_HANDOVER_"):
            continue
        if path.suffix.lower() != ".md":
            continue
        suffix = path.stem[len("SESSION_HANDOVER_") :]
        if _DATED_ARCHIVE.search(suffix):
            skipped.append({"file": path.name, "reason": "dated_archive"})
            continue
        if "brain" in suffix.casefold() and not include_brain:
            skipped.append({"file": path.name, "reason": "brain_excluded"})
            continue
        try:
            lane_key = parse_lane_identity(path, suffix)
        except ValueError:
            skipped.append({"file": path.name, "reason": "empty_lane"})
            continue
        normalized = lane_key.casefold()
        if normalized in seen:
            skipped.append({"file": path.name, "reason": "duplicate_lane"})
            continue

        handover_path = str(path.resolve())
        stale_aliases = [
            lane
            for lane in store.list_lanes()
            if _handover_paths_equal(lane.handover_path, path)
            and lane.lane_key != lane_key
        ]
        blocked = False
        for stale in stale_aliases:
            if _lane_is_empty(store, stale.lane_key):
                store.delete_lane(stale.lane_key)
                continue
            blocked = True
            conflicts.append(
                {
                    "file": path.name,
                    "canonical_lane_key": lane_key,
                    "stale_lane_key": stale.lane_key,
                    "reason": "stale_alias_in_use",
                    "handover_path": handover_path,
                }
            )
        if blocked:
            skipped.append({"file": path.name, "reason": "stale_alias_conflict"})
            continue

        seen.add(normalized)
        lane = store.ensure_lane(lane_key)
        lane.handover_path = handover_path
        lane.last_activity = lane.last_activity or utcnow_iso()
        lane.updated_at = utcnow_iso()
        store.upsert_lane(lane)
        imported.append({"lane_key": lane.lane_key, "handover_path": lane.handover_path})
    registry = store.export_lane_registry()
    errors = [
        item
        for item in imported
        if Path(item["handover_path"]).parent.resolve() != root
    ]
    if errors:
        raise ValueError("Bootstrap imported a handover outside the workspace root")
    return {
        "workspace": str(root),
        "imported": imported,
        "skipped": skipped,
        "conflicts": conflicts,
        "registry": str(registry),
    }
