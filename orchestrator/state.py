from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .models import (
    ApprovalRequest,
    ApprovalStatus,
    ArtifactClaim,
    LaneRecord,
    LaneStatus,
    MessageEnvelope,
    MessageStatus,
    TaskEnvelope,
    TaskStatus,
    normalize_lane_key,
    utcnow,
    utcnow_iso,
)

SCHEMA_VERSION = 2
_REGISTRY_RETRY_ERRORS = {errno.EACCES, errno.EPERM, errno.EBUSY, errno.EEXIST, errno.EAGAIN}
_WINDOWS_SHARING_ERRORS = {5, 32}


def workspace_hash(workspace: str) -> str:
    normalized = str(Path(workspace).resolve())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def default_state_root() -> Path:
    return Path.home() / ".cursor" / "orchestrator" / "state"


def workspace_db_path(workspace: str, state_root: Path | None = None) -> Path:
    root = state_root or default_state_root()
    return root / f"workspace_{workspace_hash(workspace)}.sqlite3"


def list_known_workspaces(state_root: Path | None = None) -> list[dict[str, Any]]:
    """Enumerate every workspace that has a control store, read-only.

    This is how one console shows a cross-client picture without holding more
    than one live coordinator: isolation stays structural — one process, one
    active workspace — while the operator still sees where work is waiting.

    Tolerant by design. A locked, partial, or foreign database is reported with
    an error rather than breaking the view.
    """
    root = state_root or default_state_root()
    workspaces: list[dict[str, Any]] = []
    if not root.exists():
        return workspaces
    for db_path in sorted(root.glob("workspace_*.sqlite3")):
        entry: dict[str, Any] = {
            "workspace_hash": db_path.stem.removeprefix("workspace_"),
            "workspace": None,
            "lanes": 0,
            "queued": 0,
            "running": 0,
            "awaiting_approval": 0,
            "pending_messages": 0,
            "heartbeat": {},
        }
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'workspace'"
            ).fetchone()
            if row:
                entry["workspace"] = row["value"]
            entry["lanes"] = conn.execute(
                "SELECT COUNT(*) AS n FROM lanes WHERE status != 'retired'"
            ).fetchone()["n"]
            for status in ("queued", "running", "awaiting_approval"):
                entry[status] = conn.execute(
                    "SELECT COUNT(*) AS n FROM tasks WHERE status = ?",
                    (status,),
                ).fetchone()["n"]
            entry["pending_messages"] = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE status = 'pending'"
            ).fetchone()["n"]
            heartbeat = conn.execute(
                "SELECT value FROM meta WHERE key = 'service_heartbeat'"
            ).fetchone()
            if heartbeat:
                try:
                    parsed = json.loads(heartbeat["value"])
                    if isinstance(parsed, dict):
                        entry["heartbeat"] = parsed
                except json.JSONDecodeError:
                    pass
            # A heartbeat says "running" forever if the process died, so the
            # pid has to be checked before claiming a console is reachable.
            pid = entry["heartbeat"].get("pid")
            entry["live"] = bool(
                entry["heartbeat"].get("state") == "running"
                and isinstance(pid, int)
                and is_process_alive(pid)
            )
        except (sqlite3.Error, OSError) as err:
            entry["error"] = str(err)
        finally:
            if conn is not None:
                conn.close()
        workspaces.append(entry)
    return workspaces


def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        try:
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                handle,
                ctypes.byref(exit_code),
            ):
                return False
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _is_retryable_os_error(err: OSError) -> bool:
    winerror = getattr(err, "winerror", None)
    if winerror in _WINDOWS_SHARING_ERRORS:
        return True
    return err.errno in _REGISTRY_RETRY_ERRORS


@contextlib.contextmanager
def _exclusive_file_lock(lock_path: Path, *, attempts: int = 12) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
    try:
        if os.fstat(handle).st_size == 0:
            os.write(handle, b"\0")
        os.lseek(handle, 0, os.SEEK_SET)
        last_error: OSError | None = None
        for attempt in range(attempts):
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as err:
                last_error = err
                if not _is_retryable_os_error(err) and os.name != "nt":
                    raise
                time.sleep(min(0.05 * (2**attempt), 0.4))
        else:
            raise last_error or OSError("Timed out acquiring registry lock")
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(handle)


def _replace_with_retry(source: Path, destination: Path, *, attempts: int = 12) -> None:
    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except OSError as err:
            last_error = err
            if not _is_retryable_os_error(err):
                raise
            time.sleep(min(0.05 * (2**attempt), 0.4))
    raise last_error or OSError(f"Failed to replace {destination}")


class ControlStore:
    def __init__(self, workspace: str, state_root: Path | None = None) -> None:
        self.workspace = str(Path(workspace).resolve())
        self.state_root = state_root or default_state_root()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.db_path = workspace_db_path(self.workspace, self.state_root)
        self._conn: sqlite3.Connection | None = None
        self._connect_lock = threading.Lock()
        self._registry_lock = threading.Lock()
        self._sql_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            with self._connect_lock:
                if self._conn is None:
                    self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    self._conn.row_factory = sqlite3.Row
                    self._conn.execute("PRAGMA journal_mode = WAL")
                    self._conn.execute("PRAGMA busy_timeout = 5000")
                    self._conn.execute("PRAGMA foreign_keys = ON")
                    self._migrate()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def reopen(self) -> sqlite3.Connection:
        self.close()
        return self.connect()

    @property
    def backup_root(self) -> Path:
        return self.state_root / "backups" / workspace_hash(self.workspace)

    @property
    def registry_path(self) -> Path:
        return self.state_root / "registry" / f"{workspace_hash(self.workspace)}.json"

    @property
    def service_lock_path(self) -> Path:
        return self.state_root / "services" / f"{workspace_hash(self.workspace)}.lock"

    def live_service_owner_token(self) -> str | None:
        try:
            payload = json.loads(self.service_lock_path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid", 0))
            token = payload.get("token")
            if pid <= 0 or not isinstance(token, str) or not token:
                return None
            return token if is_process_alive(pid) else None
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return None

    def backup_daily(
        self,
        *,
        retention_days: int = 14,
        now: datetime | None = None,
    ) -> Path:
        current = now or utcnow()
        self.backup_root.mkdir(parents=True, exist_ok=True)
        backup_path = self.backup_root / f"{current.date().isoformat()}.sqlite3"
        if not backup_path.exists():
            destination = sqlite3.connect(backup_path)
            try:
                self.connect().backup(destination)
            finally:
                destination.close()
        cutoff = current.date() - timedelta(days=retention_days)
        for candidate in self.backup_root.glob("*.sqlite3"):
            try:
                backup_date = datetime.strptime(candidate.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if backup_date < cutoff:
                candidate.unlink()
        return backup_path

    def list_backups(self) -> list[Path]:
        if not self.backup_root.exists():
            return []
        return sorted(self.backup_root.glob("*.sqlite3"), reverse=True)

    def restore_backup(self, backup_path: Path | None = None) -> Path:
        source = backup_path or next(iter(self.list_backups()), None)
        if source is None or not source.exists():
            raise FileNotFoundError("No workspace backup is available")
        source = source.resolve()
        if self.backup_root.resolve() not in source.parents:
            raise ValueError("Backup must belong to this workspace namespace")
        self.close()
        shutil.copy2(source, self.db_path)
        self.connect()
        return source

    def export_lane_registry(self, output_path: Path | None = None) -> Path:
        path = output_path or self.registry_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(path.name + ".lock")
        last_error: OSError | None = None
        for attempt in range(12):
            temporary = path.with_name(f"{path.stem}.{os.getpid()}.{uuid4().hex}.tmp")
            try:
                with self._registry_lock:
                    with _exclusive_file_lock(lock_path):
                        registry = self._registry_payload()
                        temporary.write_text(
                            json.dumps(registry, indent=2),
                            encoding="utf-8",
                        )
                        _replace_with_retry(temporary, path)
                return path
            except OSError as err:
                last_error = err
                if not _is_retryable_os_error(err):
                    raise
                time.sleep(min(0.05 * (2**attempt), 0.4))
            finally:
                temporary.unlink(missing_ok=True)
        raise last_error or OSError(f"Failed to export lane registry to {path}")

    def _registry_payload(self) -> dict[str, Any]:
        lanes: list[dict[str, Any]] = []
        for lane in self.list_lanes():
            payload = lane.to_dict()
            payload["workspace"] = workspace_hash(self.workspace)
            payload["config"] = {
                key: value
                for key, value in payload.get("config", {}).items()
                if key not in {"api_key", "secrets"}
            }
            lanes.append(payload)
        return {
            "schema_version": 1,
            "workspace_hash": workspace_hash(self.workspace),
            "generated_at": utcnow_iso(),
            "lanes": lanes,
        }

    def _migrate(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        conn.executescript(self._schema_sql())
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('workspace', ?)",
                (self.workspace,),
            )
            conn.commit()
        elif int(row["value"]) < SCHEMA_VERSION:
            conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()

    def set_meta(self, key: str, value: Any) -> None:
        self.connect().execute(
            """
            INSERT INTO meta(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, json.dumps(value)),
        )
        self.connect().commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.connect().execute(
            "SELECT value FROM meta WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set_service_heartbeat(self, payload: dict[str, Any]) -> None:
        self.set_meta("service_heartbeat", payload)

    def get_service_heartbeat(self) -> dict[str, Any] | None:
        value = self.get_meta("service_heartbeat")
        return value if isinstance(value, dict) else None

    def has_legacy_import(self, import_id: str) -> bool:
        row = self.connect().execute(
            """
            SELECT 1 FROM legacy_imports
            WHERE workspace = ? AND import_id = ?
            """,
            (self.workspace, import_id),
        ).fetchone()
        return row is not None

    def record_legacy_import(
        self,
        import_id: str,
        source_name: str,
        message_id: str,
    ) -> None:
        self.connect().execute(
            """
            INSERT OR IGNORE INTO legacy_imports(
                import_id, workspace, source_name, message_id, imported_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (import_id, self.workspace, source_name, message_id, utcnow_iso()),
        )
        self.connect().commit()

    @staticmethod
    def _schema_sql() -> str:
        return """
        CREATE TABLE IF NOT EXISTS lanes (
            workspace TEXT NOT NULL,
            lane_key TEXT NOT NULL,
            status TEXT NOT NULL,
            current_agent_id TEXT,
            prior_agent_ids TEXT NOT NULL DEFAULT '[]',
            handover_path TEXT,
            last_activity TEXT,
            context_health_score REAL NOT NULL DEFAULT 1.0,
            owner TEXT,
            active_artifact_claims TEXT NOT NULL DEFAULT '[]',
            model TEXT,
            config TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (workspace, lane_key)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            lane_key TEXT NOT NULL,
            objective TEXT NOT NULL,
            sender TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            permissions TEXT NOT NULL,
            idempotency_key TEXT,
            reply_to TEXT,
            evidence TEXT NOT NULL DEFAULT '[]',
            artifacts TEXT NOT NULL DEFAULT '[]',
            spec_id TEXT,
            ttl_seconds INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            agent_id TEXT,
            run_id TEXT,
            failure_kind TEXT,
            error_message TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            UNIQUE(workspace, idempotency_key)
        );

        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            sender TEXT NOT NULL,
            target TEXT NOT NULL,
            objective TEXT NOT NULL,
            status TEXT NOT NULL,
            permissions TEXT NOT NULL,
            reply_to TEXT,
            evidence TEXT NOT NULL DEFAULT '[]',
            ttl_seconds INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS artifact_claims (
            claim_id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            lane_key TEXT NOT NULL,
            task_id TEXT,
            owner TEXT NOT NULL,
            write_capable INTEGER NOT NULL,
            acquired_at TEXT NOT NULL,
            expires_at TEXT,
            released_at TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_write_claim
            ON artifact_claims(workspace, artifact_path)
            WHERE write_capable = 1 AND released_at IS NULL;

        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            task_id TEXT NOT NULL,
            lane_key TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            resolved_at TEXT,
            resolver TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            event_type TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metrics (
            metric_id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL,
            name TEXT NOT NULL,
            value REAL NOT NULL,
            labels TEXT NOT NULL DEFAULT '{}',
            recorded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS legacy_imports (
            import_id TEXT NOT NULL,
            workspace TEXT NOT NULL,
            source_name TEXT NOT NULL,
            message_id TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            PRIMARY KEY (workspace, import_id)
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(workspace, status);
        CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(workspace, status);
        CREATE INDEX IF NOT EXISTS idx_events_created ON events(workspace, created_at);
        """

    def upsert_lane(self, lane: LaneRecord) -> None:
        lane.lane_key = normalize_lane_key(lane.lane_key)
        with self._sql_lock:
            conn = self.connect()
            conn.execute(
            """
            INSERT INTO lanes (
                workspace, lane_key, status, current_agent_id, prior_agent_ids,
                handover_path, last_activity, context_health_score, owner,
                active_artifact_claims, model, config, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace, lane_key) DO UPDATE SET
                status=excluded.status,
                current_agent_id=excluded.current_agent_id,
                prior_agent_ids=excluded.prior_agent_ids,
                handover_path=excluded.handover_path,
                last_activity=excluded.last_activity,
                context_health_score=excluded.context_health_score,
                owner=excluded.owner,
                active_artifact_claims=excluded.active_artifact_claims,
                model=excluded.model,
                config=excluded.config,
                updated_at=excluded.updated_at
            """,
            (
                lane.workspace,
                lane.lane_key,
                lane.status.value,
                lane.current_agent_id,
                json.dumps(lane.prior_agent_ids),
                lane.handover_path,
                lane.last_activity,
                lane.context_health_score,
                lane.owner,
                json.dumps(lane.active_artifact_claims),
                lane.model,
                json.dumps(lane.config),
                lane.created_at,
                lane.updated_at,
            ),
        )
            conn.commit()

    def get_lane(self, lane_key: str) -> LaneRecord | None:
        lane_key = normalize_lane_key(lane_key)
        with self._sql_lock:
            row = self.connect().execute(
                "SELECT * FROM lanes WHERE workspace = ? AND lane_key = ?",
                (self.workspace, lane_key),
            ).fetchone()
        return self._row_to_lane(row) if row else None

    def list_lanes(self) -> list[LaneRecord]:
        with self._sql_lock:
            rows = self.connect().execute(
                "SELECT * FROM lanes WHERE workspace = ? ORDER BY lane_key",
                (self.workspace,),
            ).fetchall()
        return [self._row_to_lane(row) for row in rows]

    def ensure_lane(self, lane_key: str, owner: str | None = None, model: str | None = None) -> LaneRecord:
        lane_key = normalize_lane_key(lane_key)
        lane = self.get_lane(lane_key)
        if lane:
            return lane
        now = utcnow_iso()
        lane = LaneRecord(
            workspace=self.workspace,
            lane_key=lane_key,
            status=LaneStatus.IDLE,
            owner=owner,
            model=model,
            created_at=now,
            updated_at=now,
        )
        self.upsert_lane(lane)
        return lane

    def delete_lane(self, lane_key: str) -> None:
        lane_key = normalize_lane_key(lane_key)
        conn = self.connect()
        conn.execute(
            "DELETE FROM lanes WHERE workspace = ? AND lane_key = ?",
            (self.workspace, lane_key),
        )
        conn.commit()
        self.export_lane_registry()

    def save_task(self, task: TaskEnvelope) -> None:
        task.lane_key = normalize_lane_key(task.lane_key)
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, workspace, lane_key, objective, sender, target, status,
                permissions, idempotency_key, reply_to, evidence, artifacts, spec_id,
                ttl_seconds, created_at, updated_at, expires_at, agent_id, run_id,
                failure_kind, error_message, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                status=excluded.status,
                evidence=excluded.evidence,
                updated_at=excluded.updated_at,
                expires_at=excluded.expires_at,
                agent_id=excluded.agent_id,
                run_id=excluded.run_id,
                failure_kind=excluded.failure_kind,
                error_message=excluded.error_message,
                metadata=excluded.metadata
            """,
            (
                task.task_id,
                task.workspace,
                task.lane_key,
                task.objective,
                task.sender,
                task.target,
                task.status.value,
                json.dumps(task.permissions.to_dict()),
                task.idempotency_key,
                task.reply_to,
                json.dumps(task.evidence),
                json.dumps(task.artifacts),
                task.spec_id,
                task.ttl_seconds,
                task.created_at,
                task.updated_at,
                task.expires_at,
                task.agent_id,
                task.run_id,
                task.failure_kind.value if task.failure_kind else None,
                task.error_message,
                json.dumps(task.metadata),
            ),
        )
        conn.commit()

    def get_task(self, task_id: str) -> TaskEnvelope | None:
        row = self.connect().execute(
            "SELECT * FROM tasks WHERE task_id = ? AND workspace = ?",
            (task_id, self.workspace),
        ).fetchone()
        return self._row_to_task(row) if row else None

    def get_task_by_idempotency(self, idempotency_key: str) -> TaskEnvelope | None:
        row = self.connect().execute(
            "SELECT * FROM tasks WHERE workspace = ? AND idempotency_key = ?",
            (self.workspace, idempotency_key),
        ).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self, status: TaskStatus | None = None) -> list[TaskEnvelope]:
        conn = self.connect()
        if status:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE workspace = ? AND status = ? ORDER BY created_at",
                (self.workspace, status.value),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE workspace = ? ORDER BY created_at",
                (self.workspace,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def recover_interrupted_tasks(
        self,
        *,
        live_service_token: str | None = None,
    ) -> list[str]:
        """Atomically requeue runs not owned by the live workspace service."""
        recovered: list[str] = []
        now = utcnow_iso()
        with self._sql_lock:
            conn = self.connect()
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE workspace = ? AND status = ?
                    ORDER BY created_at
                    """,
                    (self.workspace, TaskStatus.RUNNING.value),
                ).fetchall()
                for row in rows:
                    metadata = json.loads(row["metadata"])
                    run_owner = metadata.get("run_owner")
                    if live_service_token and run_owner == live_service_token:
                        continue
                    task_id = row["task_id"]
                    claims = conn.execute(
                        """
                        SELECT lane_key, artifact_path FROM artifact_claims
                        WHERE workspace = ? AND task_id = ? AND released_at IS NULL
                        """,
                        (self.workspace, task_id),
                    ).fetchall()
                    metadata["restart_recovered_at"] = now
                    metadata["restart_recovery_count"] = (
                        int(metadata.get("restart_recovery_count", 0)) + 1
                    )
                    metadata["interrupted_run_id"] = row["run_id"]
                    metadata.pop("run_owner", None)
                    conn.execute(
                        """
                        UPDATE tasks
                        SET status = ?, run_id = NULL, updated_at = ?, metadata = ?
                        WHERE workspace = ? AND task_id = ? AND status = ?
                        """,
                        (
                            TaskStatus.QUEUED.value,
                            now,
                            json.dumps(metadata),
                            self.workspace,
                            task_id,
                            TaskStatus.RUNNING.value,
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE artifact_claims SET released_at = ?
                        WHERE workspace = ? AND task_id = ? AND released_at IS NULL
                        """,
                        (now, self.workspace, task_id),
                    )
                    by_lane: dict[str, set[str]] = {}
                    for claim in claims:
                        by_lane.setdefault(claim["lane_key"], set()).add(
                            claim["artifact_path"]
                        )
                    for lane_key, released_paths in by_lane.items():
                        lane_row = conn.execute(
                            """
                            SELECT active_artifact_claims FROM lanes
                            WHERE workspace = ? AND lane_key = ?
                            """,
                            (self.workspace, lane_key),
                        ).fetchone()
                        if lane_row:
                            active = json.loads(lane_row["active_artifact_claims"])
                            active = [
                                path for path in active if path not in released_paths
                            ]
                            conn.execute(
                                """
                                UPDATE lanes SET active_artifact_claims = ?, updated_at = ?
                                WHERE workspace = ? AND lane_key = ?
                                """,
                                (json.dumps(active), now, self.workspace, lane_key),
                            )
                    conn.execute(
                        """
                        INSERT INTO events(
                            event_id, workspace, event_type, entity_type,
                            entity_id, payload, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            self.workspace,
                            "task.restart_recovered",
                            "task",
                            task_id,
                            json.dumps(
                                {
                                    "interrupted_run_id": row["run_id"],
                                    "released_claims": len(claims),
                                }
                            ),
                            now,
                        ),
                    )
                    recovered.append(task_id)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return recovered

    def save_message(self, message: MessageEnvelope) -> None:
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO messages (
                message_id, workspace, sender, target, objective, status, permissions,
                reply_to, evidence, ttl_seconds, created_at, updated_at, expires_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                status=excluded.status,
                updated_at=excluded.updated_at,
                expires_at=excluded.expires_at,
                metadata=excluded.metadata
            """,
            (
                message.message_id,
                message.workspace,
                message.sender,
                message.target,
                message.objective,
                message.status.value,
                json.dumps(message.permissions.to_dict()),
                message.reply_to,
                json.dumps(message.evidence),
                message.ttl_seconds,
                message.created_at,
                message.updated_at,
                message.expires_at,
                json.dumps(message.metadata),
            ),
        )
        conn.commit()

    def get_message(self, message_id: str) -> MessageEnvelope | None:
        row = self.connect().execute(
            "SELECT * FROM messages WHERE message_id = ? AND workspace = ?",
            (message_id, self.workspace),
        ).fetchone()
        return self._row_to_message(row) if row else None

    def list_messages(self, status: MessageStatus | None = None) -> list[MessageEnvelope]:
        conn = self.connect()
        if status:
            rows = conn.execute(
                "SELECT * FROM messages WHERE workspace = ? AND status = ? ORDER BY created_at",
                (self.workspace, status.value),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages WHERE workspace = ? ORDER BY created_at",
                (self.workspace,),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def save_claim(self, claim: ArtifactClaim) -> None:
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO artifact_claims (
                claim_id, workspace, artifact_path, lane_key, task_id, owner,
                write_capable, acquired_at, expires_at, released_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(claim_id) DO UPDATE SET
                released_at=excluded.released_at,
                expires_at=excluded.expires_at
            """,
            (
                claim.claim_id,
                claim.workspace,
                claim.artifact_path,
                claim.lane_key,
                claim.task_id,
                claim.owner,
                1 if claim.write_capable else 0,
                claim.acquired_at,
                claim.expires_at,
                claim.released_at,
            ),
        )
        conn.commit()

    def get_active_write_claim(self, artifact_path: str) -> ArtifactClaim | None:
        row = self.connect().execute(
            """
            SELECT * FROM artifact_claims
            WHERE workspace = ? AND artifact_path = ? AND write_capable = 1 AND released_at IS NULL
            """,
            (self.workspace, artifact_path),
        ).fetchone()
        return self._row_to_claim(row) if row else None

    def list_active_claims(self) -> list[ArtifactClaim]:
        rows = self.connect().execute(
            """
            SELECT * FROM artifact_claims
            WHERE workspace = ? AND released_at IS NULL
            ORDER BY acquired_at
            """,
            (self.workspace,),
        ).fetchall()
        return [self._row_to_claim(row) for row in rows]

    def save_approval(self, approval: ApprovalRequest) -> None:
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO approvals (
                approval_id, workspace, task_id, lane_key, action, reason, status,
                requested_at, resolved_at, resolver, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(approval_id) DO UPDATE SET
                status=excluded.status,
                resolved_at=excluded.resolved_at,
                resolver=excluded.resolver,
                metadata=excluded.metadata
            """,
            (
                approval.approval_id,
                approval.workspace,
                approval.task_id,
                approval.lane_key,
                approval.action,
                approval.reason,
                approval.status.value,
                approval.requested_at,
                approval.resolved_at,
                approval.resolver,
                json.dumps(approval.metadata),
            ),
        )
        conn.commit()

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        row = self.connect().execute(
            "SELECT * FROM approvals WHERE approval_id = ? AND workspace = ?",
            (approval_id, self.workspace),
        ).fetchone()
        return self._row_to_approval(row) if row else None

    def list_approvals(self, status: ApprovalStatus | None = None) -> list[ApprovalRequest]:
        conn = self.connect()
        if status:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE workspace = ? AND status = ? ORDER BY requested_at",
                (self.workspace, status.value),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE workspace = ? ORDER BY requested_at",
                (self.workspace,),
            ).fetchall()
        return [self._row_to_approval(row) for row in rows]

    def append_event(
        self,
        event_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_id = str(uuid4())
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO events(event_id, workspace, event_type, entity_type, entity_id, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                self.workspace,
                event_type,
                entity_type,
                entity_id,
                json.dumps(payload or {}),
                utcnow_iso(),
            ),
        )
        conn.commit()
        return event_id

    def list_events(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT * FROM events WHERE workspace = ? ORDER BY created_at DESC LIMIT ?
            """,
            (self.workspace, limit),
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def record_metric(self, name: str, value: float, labels: dict[str, Any] | None = None) -> str:
        metric_id = str(uuid4())
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO metrics(metric_id, workspace, name, value, labels, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                metric_id,
                self.workspace,
                name,
                value,
                json.dumps(labels or {}),
                utcnow_iso(),
            ),
        )
        conn.commit()
        return metric_id

    def list_metrics(self, name: str | None = None) -> list[dict[str, Any]]:
        conn = self.connect()
        if name:
            rows = conn.execute(
                "SELECT * FROM metrics WHERE workspace = ? AND name = ? ORDER BY recorded_at",
                (self.workspace, name),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM metrics WHERE workspace = ? ORDER BY recorded_at",
                (self.workspace,),
            ).fetchall()
        return [
            {
                "metric_id": row["metric_id"],
                "name": row["name"],
                "value": row["value"],
                "labels": json.loads(row["labels"]),
                "recorded_at": row["recorded_at"],
            }
            for row in rows
        ]

    def expire_orphans(self, now: datetime | None = None) -> dict[str, int]:
        current = now or utcnow()
        counts = {"tasks": 0, "messages": 0}
        conn = self.connect()
        for row in conn.execute(
            """
            SELECT task_id FROM tasks
            WHERE workspace = ? AND status IN ('queued', 'paused')
              AND expires_at IS NOT NULL AND expires_at < ?
            """,
            (self.workspace, current.isoformat()),
        ).fetchall():
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (TaskStatus.EXPIRED.value, utcnow_iso(), row["task_id"]),
            )
            counts["tasks"] += 1
        for row in conn.execute(
            """
            SELECT message_id FROM messages
            WHERE workspace = ? AND status = 'pending'
              AND expires_at IS NOT NULL AND expires_at < ?
            """,
            (self.workspace, current.isoformat()),
        ).fetchall():
            conn.execute(
                "UPDATE messages SET status = ?, updated_at = ? WHERE message_id = ?",
                (MessageStatus.EXPIRED.value, utcnow_iso(), row["message_id"]),
            )
            counts["messages"] += 1
        conn.commit()
        return counts

    def dead_letter_task(self, task_id: str, reason: str) -> None:
        conn = self.connect()
        conn.execute(
            """
            UPDATE tasks SET status = ?, error_message = ?, updated_at = ?
            WHERE task_id = ? AND workspace = ?
            """,
            (TaskStatus.DEAD_LETTER.value, reason, utcnow_iso(), task_id, self.workspace),
        )
        conn.commit()

    def dead_letter_message(self, message_id: str, reason: str) -> None:
        conn = self.connect()
        conn.execute(
            """
            UPDATE messages SET status = ?, updated_at = ?,
                metadata = json_set(COALESCE(metadata, '{}'), '$.dead_letter_reason', ?)
            WHERE message_id = ? AND workspace = ?
            """,
            (MessageStatus.DEAD_LETTER.value, utcnow_iso(), reason, message_id, self.workspace),
        )
        conn.commit()

    @staticmethod
    def _row_to_lane(row: sqlite3.Row) -> LaneRecord:
        return LaneRecord(
            workspace=row["workspace"],
            lane_key=row["lane_key"],
            status=LaneStatus(row["status"]),
            current_agent_id=row["current_agent_id"],
            prior_agent_ids=json.loads(row["prior_agent_ids"]),
            handover_path=row["handover_path"],
            last_activity=row["last_activity"],
            context_health_score=row["context_health_score"],
            owner=row["owner"],
            active_artifact_claims=json.loads(row["active_artifact_claims"]),
            model=row["model"],
            config=json.loads(row["config"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskEnvelope:
        from .models import FailureKind, Permissions

        failure = row["failure_kind"]
        return TaskEnvelope(
            task_id=row["task_id"],
            workspace=row["workspace"],
            lane_key=row["lane_key"],
            objective=row["objective"],
            sender=row["sender"],
            target=row["target"],
            status=TaskStatus(row["status"]),
            permissions=Permissions.from_dict(json.loads(row["permissions"])),
            idempotency_key=row["idempotency_key"],
            reply_to=row["reply_to"],
            evidence=json.loads(row["evidence"]),
            artifacts=json.loads(row["artifacts"]),
            spec_id=row["spec_id"],
            ttl_seconds=row["ttl_seconds"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            agent_id=row["agent_id"],
            run_id=row["run_id"],
            failure_kind=FailureKind(failure) if failure else None,
            error_message=row["error_message"],
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> MessageEnvelope:
        from .models import Permissions

        return MessageEnvelope(
            message_id=row["message_id"],
            workspace=row["workspace"],
            sender=row["sender"],
            target=row["target"],
            objective=row["objective"],
            status=MessageStatus(row["status"]),
            permissions=Permissions.from_dict(json.loads(row["permissions"])),
            reply_to=row["reply_to"],
            evidence=json.loads(row["evidence"]),
            ttl_seconds=row["ttl_seconds"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _row_to_claim(row: sqlite3.Row) -> ArtifactClaim:
        return ArtifactClaim(
            claim_id=row["claim_id"],
            workspace=row["workspace"],
            artifact_path=row["artifact_path"],
            lane_key=row["lane_key"],
            task_id=row["task_id"],
            owner=row["owner"],
            write_capable=bool(row["write_capable"]),
            acquired_at=row["acquired_at"],
            expires_at=row["expires_at"],
            released_at=row["released_at"],
        )

    @staticmethod
    def _row_to_approval(row: sqlite3.Row) -> ApprovalRequest:
        return ApprovalRequest(
            approval_id=row["approval_id"],
            workspace=row["workspace"],
            task_id=row["task_id"],
            lane_key=row["lane_key"],
            action=row["action"],
            reason=row["reason"],
            status=ApprovalStatus(row["status"]),
            requested_at=row["requested_at"],
            resolved_at=row["resolved_at"],
            resolver=row["resolver"],
            metadata=json.loads(row["metadata"]),
        )


def compute_expires_at(ttl_seconds: int | None, created_at: str | None = None) -> str | None:
    if not ttl_seconds:
        return None
    base = datetime.fromisoformat(created_at) if created_at else utcnow()
    return (base + timedelta(seconds=ttl_seconds)).isoformat()
