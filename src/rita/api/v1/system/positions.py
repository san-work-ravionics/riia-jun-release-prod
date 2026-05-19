"""System CRUD router for the positions table."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.positions import PositionsRepository
from rita.schemas.positions import Position

router = APIRouter(prefix="/api/v1/system/positions", tags=["system:positions"])


def get_repo(db: Session = Depends(get_db)) -> PositionsRepository:
    return PositionsRepository(db)


@router.get("/", response_model=list[Position])
def list_all(repo: PositionsRepository = Depends(get_repo)):
    return repo.read_all()


@router.get("/{id}", response_model=Position)
def get_one(id: str, repo: PositionsRepository = Depends(get_repo)):
    record = repo.find_by_id(id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Position {id!r} not found")
    return record


@router.put("/{id}", response_model=Position)
def upsert(id: str, body: Position, repo: PositionsRepository = Depends(get_repo)):
    return repo.upsert(body)


@router.delete("/{id}", status_code=204)
def delete(id: str, repo: PositionsRepository = Depends(get_repo)):
    removed = repo.delete(id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Position {id!r} not found")
