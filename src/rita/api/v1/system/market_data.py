"""System CRUD router for the market data table."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.market_data import MarketDataCacheRepository
from rita.schemas.market_data import MarketDataCache

router = APIRouter(prefix="/api/v1/system/market_data", tags=["system:market_data"])


def get_repo(db: Session = Depends(get_db)) -> MarketDataCacheRepository:
    return MarketDataCacheRepository(db)


@router.get("/", response_model=list[MarketDataCache])
def list_all(repo: MarketDataCacheRepository = Depends(get_repo)):
    return repo.read_all()


@router.get("/{id}", response_model=MarketDataCache)
def get_one(id: str, repo: MarketDataCacheRepository = Depends(get_repo)):
    record = repo.find_by_id(id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"MarketDataCache {id!r} not found")
    return record


@router.put("/{id}", response_model=MarketDataCache)
def upsert(id: str, body: MarketDataCache, repo: MarketDataCacheRepository = Depends(get_repo)):
    return repo.upsert(body)


@router.delete("/{id}", status_code=204)
def delete(id: str, repo: MarketDataCacheRepository = Depends(get_repo)):
    removed = repo.delete(id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"MarketDataCache {id!r} not found")
