"""System CRUD router for the audit table."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.audit import AuditLogRepository
from rita.schemas.audit import AuditLog

router = APIRouter(prefix="/api/v1/system/audit", tags=["system:audit"])


def get_repo(db: Session = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)


@router.get("/", response_model=list[AuditLog])
def list_all(repo: AuditLogRepository = Depends(get_repo)):
    return repo.read_all()


@router.get("/{id}", response_model=AuditLog)
def get_one(id: str, repo: AuditLogRepository = Depends(get_repo)):
    record = repo.find_by_id(id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"AuditLog {id!r} not found")
    return record


@router.put("/{id}", response_model=AuditLog)
def upsert(id: str, body: AuditLog, repo: AuditLogRepository = Depends(get_repo)):
    return repo.upsert(body)


@router.delete("/{id}", status_code=204)
def delete(id: str, repo: AuditLogRepository = Depends(get_repo)):
    removed = repo.delete(id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"AuditLog {id!r} not found")
