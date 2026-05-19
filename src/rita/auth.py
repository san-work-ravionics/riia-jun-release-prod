from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.database import get_db
from rita.models.user import UserModel

bearer_scheme = HTTPBearer()


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.security.jwt_expiry_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(
        payload,
        settings.security.jwt_secret.get_secret_value(),
        algorithm=settings.security.jwt_algorithm,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> UserModel:
    settings = get_settings()
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.security.jwt_secret.get_secret_value(),
            algorithms=[settings.security.jwt_algorithm],
        )
        subject: str = payload.get("sub")
        if subject is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
            
        if subject == "rita-dev" and settings.env == "development":
            return UserModel(id="rita-dev", can_access_ops=True, can_assist_research=True, can_create_portfolio=True, can_review_portfolio=True)

        user = db.query(UserModel).filter(UserModel.id == subject).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

class RequireRole:
    def __init__(self, role_name: str):
        self.role_name = role_name

    def __call__(self, user: UserModel = Depends(get_current_user)):
        if getattr(user, self.role_name, False) is not True:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail=f"Permission denied: requires {self.role_name}"
            )
        return user
