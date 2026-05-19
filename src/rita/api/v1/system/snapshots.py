"""System CRUD router for the snapshots table."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.snapshots import SnapshotsRepository
from rita.schemas.snapshots import Snapshot

router = APIRouter(prefix="/api/v1/system/snapshots", tags=["system:snapshots"])


def get_repo(db: Session = Depends(get_db)) -> SnapshotsRepository:
    return SnapshotsRepository(db)


@router.get("/", response_model=list[Snapshot])
def list_all(repo: SnapshotsRepository = Depends(get_repo)):
    return repo.read_all()


@router.get("/{id}", response_model=Snapshot)
def get_one(id: str, repo: SnapshotsRepository = Depends(get_repo)):
    record = repo.find_by_id(id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Snapshot {id!r} not found")
    return record


@router.put("/{id}", response_model=Snapshot)
def upsert(id: str, body: Snapshot, repo: SnapshotsRepository = Depends(get_repo)):
    return repo.upsert(body)


@router.delete("/{id}", status_code=204)
def delete(id: str, repo: SnapshotsRepository = Depends(get_repo)):
    removed = repo.delete(id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Snapshot {id!r} not found")
