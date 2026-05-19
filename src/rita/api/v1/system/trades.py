"""System CRUD router for the trades table."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.trades import TradesRepository
from rita.schemas.trades import Trade

router = APIRouter(prefix="/api/v1/system/trades", tags=["system:trades"])


def get_repo(db: Session = Depends(get_db)) -> TradesRepository:
    return TradesRepository(db)


@router.get("/", response_model=list[Trade])
def list_all(repo: TradesRepository = Depends(get_repo)):
    return repo.read_all()


@router.get("/{id}", response_model=Trade)
def get_one(id: str, repo: TradesRepository = Depends(get_repo)):
    record = repo.find_by_id(id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Trade {id!r} not found")
    return record


@router.put("/{id}", response_model=Trade)
def upsert(id: str, body: Trade, repo: TradesRepository = Depends(get_repo)):
    return repo.upsert(body)


@router.delete("/{id}", status_code=204)
def delete(id: str, repo: TradesRepository = Depends(get_repo)):
    removed = repo.delete(id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Trade {id!r} not found")
