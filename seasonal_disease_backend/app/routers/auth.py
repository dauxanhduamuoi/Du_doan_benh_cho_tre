from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LoginSession, User, UserProfile
from app.schemas import TokenResponse
from app.security import (
    create_access_token,
    get_current_session_id,
    get_current_user,
    get_user_permissions,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class ChangePasswordPayload(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)


class UpdateProfilePayload(BaseModel):
    full_name: str | None = None
    birth_date: str | None = None
    gender: str | None = None
    position: str | None = None


def _serialize_user(db: Session, user: User) -> dict:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "permissions": get_user_permissions(db, user),
        "birth_date": profile.birth_date if profile else None,
        "gender": profile.gender if profile else None,
        "position": profile.position if profile else None,
    }


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    if not ua:
        return None
    return ua[:500]


def _serialize_session(session: LoginSession, current_sid: int | None) -> dict:
    return {
        "id": session.id,
        "ip_address": session.ip_address,
        "user_agent": session.user_agent,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_seen_at": session.last_seen_at.isoformat() if session.last_seen_at else None,
        "is_current": current_sid is not None and current_sid == session.id,
        "revoked_at": session.revoked_at.isoformat() if session.revoked_at else None,
    }


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Tài khoản đã bị khóa.")

    session = LoginSession(
        user_id=user.id,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    token = create_access_token(
        data={
            "sub": user.username,
            "role": user.role,
            "sid": session.id,
        }
    )

    return TokenResponse(access_token=token)


@router.get("/me")
def me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _serialize_user(db, current_user)


@router.patch("/profile")
def update_profile(
    payload: UpdateProfilePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.full_name = (payload.full_name or "").strip() or None
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
    profile.birth_date = (payload.birth_date or "").strip() or None
    profile.gender = (payload.gender or "").strip() or None
    profile.position = (payload.position or "").strip() or None
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)
    return _serialize_user(db, current_user)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không đúng.")

    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải khác mật khẩu cũ.")

    current_user.password_hash = hash_password(payload.new_password)
    db.commit()

    return {"message": "Đổi mật khẩu thành công."}


@router.get("/sessions")
def list_my_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_sid: int | None = Depends(get_current_session_id),
):
    sessions = (
        db.query(LoginSession)
        .filter(LoginSession.user_id == current_user.id)
        .order_by(LoginSession.last_seen_at.desc())
        .all()
    )
    return [_serialize_session(s, current_sid) for s in sessions]


@router.post("/sessions/{session_id}/revoke")
def revoke_my_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = (
        db.query(LoginSession)
        .filter(LoginSession.id == session_id, LoginSession.user_id == current_user.id)
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy session.")

    if session.revoked_at is None:
        session.revoked_at = datetime.utcnow()
        db.commit()

    return {"message": "Đã đăng xuất session."}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_sid: int | None = Depends(get_current_session_id),
):
    query = db.query(LoginSession).filter(
        LoginSession.user_id == current_user.id,
        LoginSession.revoked_at.is_(None),
    )

    if current_sid is not None:
        query = query.filter(LoginSession.id != current_sid)

    sessions = query.all()
    now = datetime.utcnow()

    for s in sessions:
        s.revoked_at = now

    db.commit()

    return {"revoked": len(sessions)}
