"""Repository for the orders table (broker order log)."""

from sqlalchemy.orm import Session

from rita.models.orders import OrderModel
from rita.repositories.base import SqlRepository
from rita.schemas.orders import Order


class OrdersRepository(SqlRepository[Order, OrderModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, OrderModel, Order, "order_id")
