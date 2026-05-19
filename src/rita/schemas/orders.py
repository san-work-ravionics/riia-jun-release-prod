"""Pydantic schemas for the orders table (broker order log)."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class OrderBase(BaseModel):
    instrument: str = Field(max_length=64)
    underlying: Literal["NIFTY", "BANKNIFTY"]
    product: Literal["NRML", "MIS", "CNC"] = "NRML"
    order_type: Literal["BUY", "SELL"]
    quantity: int = Field(ge=0)
    quantity_filled: int = Field(ge=0)
    avg_price: float = Field(ge=0)
    status: Literal["COMPLETE", "PENDING", "CANCELLED", "REJECTED"]
    placed_at: datetime


class OrderCreate(OrderBase):
    pass


class Order(OrderBase):
    model_config = ConfigDict(from_attributes=True)

    order_id: str
    recorded_at: datetime
