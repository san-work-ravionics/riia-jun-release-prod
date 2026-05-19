"""Repository for the snapshots table (manoeuvre position snapshots)."""

from sqlalchemy.orm import Session

from rita.models.snapshots import SnapshotModel
from rita.repositories.base import SqlRepository
from rita.schemas.snapshots import Snapshot


class SnapshotsRepository(SqlRepository[Snapshot, SnapshotModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, SnapshotModel, Snapshot, "snapshot_id")
