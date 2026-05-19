"""System CRUD router for the alerts table."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.alerts import AlertsRepository
from rita.schemas.alerts import Alert

router = APIRouter(prefix="/api/v1/system/alerts", tags=["system:alerts"])


def get_repo(db: Session = Depends(get_db)) -> AlertsRepository:
    return AlertsRepository(db)


@router.get("/", response_model=list[Alert])
def list_all(repo: AlertsRepository = Depends(get_repo)):
    return repo.read_all()


@router.get("/{id}", response_model=Alert)
def get_one(id: str, repo: AlertsRepository = Depends(get_repo)):
    record = repo.find_by_id(id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Alert {id!r} not found")
    return record


@router.put("/{id}", response_model=Alert)
def upsert(id: str, body: Alert, repo: AlertsRepository = Depends(get_repo)):
    return repo.upsert(body)


@router.delete("/{id}", status_code=204)
def delete(id: str, repo: AlertsRepository = Depends(get_repo)):
    removed = repo.delete(id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Alert {id!r} not found")
