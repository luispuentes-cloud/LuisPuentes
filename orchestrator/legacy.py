from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .coordinator import Coordinator


def inventory_legacy_inbox(inbox_root: Path) -> list[dict[str, Any]]:
    if not inbox_root.exists():
        return []
    inventory: list[dict[str, Any]] = []
    for path in sorted(inbox_root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        stat = path.stat()
        inventory.append(
            {
                "filename": path.name,
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }
        )
    return inventory


def audit_or_import_legacy_inbox(
    coordinator: Coordinator,
    inbox_root: Path,
    *,
    mapping_path: Path | None = None,
) -> dict[str, Any]:
    inventory = inventory_legacy_inbox(inbox_root)
    if mapping_path is None:
        return {"inventory": inventory, "imported": [], "skipped": []}

    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict):
        raise ValueError("Legacy mapping must be a JSON object")
    available = {item["filename"] for item in inventory}
    normalized_workspace = os.path.normcase(
        str(Path(coordinator.workspace).resolve())
    )
    validated: list[tuple[str, str, Path, str]] = []
    for filename, route in mapping.items():
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError(f"Legacy mapping filename is not flat: {filename!r}")
        if filename not in available:
            raise FileNotFoundError(f"Legacy inbox file not found: {filename}")
        if not isinstance(route, dict):
            raise ValueError(f"Route for {filename} must be an object")
        mapped_workspace = route.get("workspace")
        target = route.get("target")
        if not isinstance(mapped_workspace, str) or not isinstance(target, str):
            raise ValueError(f"Route for {filename} requires workspace and target")
        if os.path.normcase(str(Path(mapped_workspace).resolve())) != normalized_workspace:
            raise ValueError(
                f"Legacy mapping workspace differs from coordinator: {filename}"
            )
        source = (inbox_root / filename).resolve()
        if source.parent != inbox_root.resolve():
            raise ValueError(f"Legacy mapping escaped inbox root: {filename}")
        import_id = hashlib.sha256(str(source).encode("utf-8")).hexdigest()
        validated.append((filename, target, source, import_id))

    imported: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for filename, target, source, import_id in validated:
        if coordinator.store.has_legacy_import(import_id):
            skipped.append({"filename": filename, "reason": "already_imported"})
            continue
        message = coordinator.inbox_send(
            target=target,
            objective=f"Legacy inbox reference: {filename}",
            sender="legacy-inbox-import",
            evidence=[str(source)],
            metadata={
                "legacy_import_id": import_id,
                "legacy_filename": filename,
                "content_imported": False,
            },
        )
        coordinator.store.record_legacy_import(
            import_id,
            filename,
            message.message_id,
        )
        imported.append(
            {
                "filename": filename,
                "message_id": message.message_id,
                "target": target,
                "import_id": import_id,
            }
        )
    return {"inventory": inventory, "imported": imported, "skipped": skipped}
