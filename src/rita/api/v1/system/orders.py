"""System CRUD router for the orders table."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.orders import OrdersRepository
from rita.schemas.orders import Order

router = APIRouter(prefix="/api/v1/system/orders", tags=["system:orders"])


def get_repo(db: Session = Depends(get_db)) -> OrdersRepository:
    return OrdersRepository(db)


@router.get("/", response_model=list[Order])
def list_all(repo: OrdersRepository = Depends(get_repo)):
    return repo.read_all()


@router.get("/{id}", response_model=Order)
def get_one(id: str, repo: OrdersRepository = Depends(get_repo)):
    record = repo.find_by_id(id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Order {id!r} not found")
    return record


@router.put("/{id}", response_model=Order)
def upsert(id: str, body: Order, repo: OrdersRepository = Depends(get_repo)):
    return repo.upsert(body)


@router.delete("/{id}", status_code=204)
def delete(id: str, repo: OrdersRepository = Depends(get_repo)):
    removed = repo.delete(id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Order {id!r} not found")
