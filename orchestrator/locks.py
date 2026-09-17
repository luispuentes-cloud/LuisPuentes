from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from .models import ArtifactClaim, utcnow, utcnow_iso
from .state import ControlStore


class ArtifactLockManager:
    def __init__(self, store: ControlStore, default_ttl_seconds: int = 3600) -> None:
        self.store = store
        self.default_ttl_seconds = default_ttl_seconds

    def acquire(
        self,
        artifact_path: str,
        lane_key: str,
        owner: str,
        *,
        task_id: str | None = None,
        write_capable: bool = True,
        ttl_seconds: int | None = None,
    ) -> ArtifactClaim:
        if write_capable:
            existing = self.store.get_active_write_claim(artifact_path)
            if existing and existing.lane_key != lane_key:
                raise PermissionError(
                    f"Artifact {artifact_path} is write-locked by lane {existing.lane_key}"
                )
        ttl = ttl_seconds or self.default_ttl_seconds
        acquired_at = utcnow_iso()
        expires_at = (utcnow() + timedelta(seconds=ttl)).isoformat()
        claim = ArtifactClaim(
            claim_id=str(uuid4()),
            workspace=self.store.workspace,
            artifact_path=artifact_path,
            lane_key=lane_key,
            task_id=task_id,
            owner=owner,
            write_capable=write_capable,
            acquired_at=acquired_at,
            expires_at=expires_at,
        )
        self.store.save_claim(claim)
        lane = self.store.get_lane(lane_key)
        if lane:
            claims = list(lane.active_artifact_claims)
            if artifact_path not in claims:
                claims.append(artifact_path)
            lane.active_artifact_claims = claims
            lane.updated_at = utcnow_iso()
            self.store.upsert_lane(lane)
        self.store.append_event(
            "artifact.claim.acquired",
            entity_type="artifact",
            entity_id=artifact_path,
            payload={"lane_key": lane_key, "write_capable": write_capable},
        )
        return claim

    def release(self, artifact_path: str, lane_key: str) -> bool:
        claims = self.store.list_active_claims()
        released = False
        for claim in claims:
            if claim.artifact_path == artifact_path and claim.lane_key == lane_key:
                claim.released_at = utcnow_iso()
                self.store.save_claim(claim)
                released = True
        if released:
            lane = self.store.get_lane(lane_key)
            if lane:
                lane.active_artifact_claims = [
                    path for path in lane.active_artifact_claims if path != artifact_path
                ]
                lane.updated_at = utcnow_iso()
                self.store.upsert_lane(lane)
            self.store.append_event(
                "artifact.claim.released",
                entity_type="artifact",
                entity_id=artifact_path,
                payload={"lane_key": lane_key},
            )
        return released

    def recover_stale(self, now: datetime | None = None) -> list[ArtifactClaim]:
        current = now or utcnow()
        recovered: list[ArtifactClaim] = []
        for claim in self.store.list_active_claims():
            if claim.expires_at and datetime.fromisoformat(claim.expires_at) < current:
                claim.released_at = utcnow_iso()
                self.store.save_claim(claim)
                lane = self.store.get_lane(claim.lane_key)
                if lane:
                    lane.active_artifact_claims = [
                        path
                        for path in lane.active_artifact_claims
                        if path != claim.artifact_path
                    ]
                    lane.updated_at = utcnow_iso()
                    self.store.upsert_lane(lane)
                self.store.append_event(
                    "artifact.claim.recovered",
                    entity_type="artifact",
                    entity_id=claim.artifact_path,
                    payload={"lane_key": claim.lane_key},
                )
                recovered.append(claim)
        return recovered
