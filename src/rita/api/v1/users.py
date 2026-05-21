from __future__ import annotations

from typing import List
import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from rita.database import get_db
from rita.models.user import UserModel

router = APIRouter(prefix="/api/v1/users", tags=["users"])

class UserResponse(BaseModel):
    id: str
    last_login_date: datetime.datetime | None
    can_assist_research: bool
    can_create_portfolio: bool
    can_review_portfolio: bool
    can_access_ops: bool

    class Config:
        from_attributes = True
        orm_mode = True

class UserRolesUpdate(BaseModel):
    can_assist_research: bool
    can_create_portfolio: bool
    can_review_portfolio: bool
    can_access_ops: bool

@router.get("", response_model=List[UserResponse])
def list_users(db: Session = Depends(get_db)):
    users = db.query(UserModel).all()
    return users

@router.put("/{user_id}/roles", response_model=UserResponse)
def update_user_roles(user_id: str, payload: UserRolesUpdate, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    user.can_assist_research = payload.can_assist_research
    user.can_create_portfolio = payload.can_create_portfolio
    user.can_review_portfolio = payload.can_review_portfolio
    user.can_access_ops = payload.can_access_ops
    
    db.commit()
    db.refresh(user)
    return user
