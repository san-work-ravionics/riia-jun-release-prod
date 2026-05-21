from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

import uuid
from rita.auth import create_access_token
from rita.limiter import limiter
from rita.config import get_settings
from rita.database import get_db
from rita.models.user import UserModel
from rita.models.login_event import LoginEventModel

from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi import Depends
from jose import jwt
import requests
import datetime

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, body: TokenRequest) -> TokenResponse:
    if body.password != "rita-dev":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(subject=body.username)
    return TokenResponse(access_token=token)

def _callback_uri(request: Request, settings) -> str:
    """Build the OAuth callback URI.

    Uses RITA_BASE_URL when set (needed for EC2/HTTP deployments where there
    is no reverse proxy to rewrite the scheme).  Falls back to auto-detection
    from the incoming request.
    """
    if settings.security.base_url:
        return settings.security.base_url.rstrip("/") + "/auth/google/callback"
    return str(request.url_for("google_callback"))


@router.get("/google/login")
def google_login(request: Request):
    settings = get_settings()
    redirect_uri = _callback_uri(request, settings)

    url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        "response_type=code&"
        f"client_id={settings.security.google_client_id}&"
        f"redirect_uri={redirect_uri}&"
        "scope=openid%20email%20profile&"
        "access_type=offline"
    )
    return RedirectResponse(url)

@router.get("/google/callback")
def google_callback(request: Request, code: str, db: Session = Depends(get_db)):
    settings = get_settings()
    redirect_uri = _callback_uri(request, settings)

    # Exchange code for token
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": settings.security.google_client_id,
        "client_secret": settings.security.google_client_secret.get_secret_value(),
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    resp = requests.post(token_url, data=data)
    if not resp.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not validate credentials")
        
    tokens = resp.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No id_token received")
        
    # Decode id_token securely obtained via backend TLS connection
    payload = jwt.decode(id_token, "", options={"verify_signature": False, "verify_aud": False, "verify_exp": False})
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email not found in Google profile")

    # Check or create user in DB
    user = db.query(UserModel).filter(UserModel.id == email).first()
    if not user:
        user = UserModel(id=email)
        db.add(user)
    user.last_login_date = datetime.datetime.utcnow()
    if user.first_login_date is None:
        user.first_login_date = datetime.datetime.utcnow()
    db.add(LoginEventModel(id=str(uuid.uuid4()), user_id=user.id, logged_at=datetime.datetime.utcnow()))
    db.commit()

    # Generate internal JWT
    token = create_access_token(subject=email)
    
    # Send user back to dashboard.
    response = RedirectResponse(url=f"/dashboard/index.html?token={token}")
    return response
