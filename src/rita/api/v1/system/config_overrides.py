"""System CRUD router for the config overrides table."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.config_overrides import ConfigOverridesRepository
from rita.schemas.config_overrides import ConfigOverride

router = APIRouter(prefix="/api/v1/system/config_overrides", tags=["system:config_overrides"])


def get_repo(db: Session = Depends(get_db)) -> ConfigOverridesRepository:
    return ConfigOverridesRepository(db)


@router.get("/", response_model=list[ConfigOverride])
def list_all(repo: ConfigOverridesRepository = Depends(get_repo)):
    return repo.read_all()


@router.get("/{id}", response_model=ConfigOverride)
def get_one(id: str, repo: ConfigOverridesRepository = Depends(get_repo)):
    record = repo.find_by_id(id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"ConfigOverride {id!r} not found")
    return record


@router.put("/{id}", response_model=ConfigOverride)
def upsert(id: str, body: ConfigOverride, repo: ConfigOverridesRepository = Depends(get_repo)):
    return repo.upsert(body)


@router.delete("/{id}", status_code=204)
def delete(id: str, repo: ConfigOverridesRepository = Depends(get_repo)):
    removed = repo.delete(id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"ConfigOverride {id!r} not found")
