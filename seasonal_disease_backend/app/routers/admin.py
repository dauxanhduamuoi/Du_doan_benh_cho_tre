from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LoginSession, User, UserPermission, UserProfile
from app.permissions import ADMIN_PERMISSION_CODES, PERMISSION_CODES, feature_permission_codes, permission_dicts
from app.schemas import UserCreate, UserOut
from app.security import get_user_permissions, hash_password, require_admin, require_admin_permission

router = APIRouter(prefix="/api/admin", tags=["Admin"])

# Vai trò mặc định FE hiển thị. Admin có thể thêm vai trò custom (vd: "y_tá",
# "kỹ thuật viên") trực tiếp từ UI — BE chỉ kiểm tra format chứ không khoá
# danh sách cố định.
DEFAULT_ROLES = ["admin", "staff"]


def _validate_role(role: str) -> str:
    role = (role or "").strip()
    if role not in DEFAULT_ROLES:
        raise HTTPException(status_code=400, detail="Vai trò chỉ gồm admin hoặc staff.")
    return role


class UpdateRolePayload(BaseModel):
    role: str


class UpdateActivePayload(BaseModel):
    is_active: bool


class UpdatePermissionsPayload(BaseModel):
    permissions: list[str] = []


class ResetPasswordPayload(BaseModel):
    password: str


class BulkCreateUsersPayload(BaseModel):
    username_prefix: str
    count: int
    password: str
    role: str = "staff"
    permissions: list[str]
    full_name_prefix: str | None = None
    position: str | None = None


def _serialize_admin_session(session: LoginSession) -> dict:
    return {
        "id": session.id,
        "ip_address": session.ip_address,
        "user_agent": session.user_agent,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_seen_at": session.last_seen_at.isoformat() if session.last_seen_at else None,
        "revoked_at": session.revoked_at.isoformat() if session.revoked_at else None,
    }


def _validate_permissions(permissions: list[str]) -> list[str]:
    clean = sorted({p.strip() for p in permissions if p and p.strip()})
    invalid = [p for p in clean if p not in PERMISSION_CODES]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Quyền không hợp lệ: {', '.join(invalid)}")
    return clean


def _set_user_permissions(db: Session, user: User, permissions: list[str]) -> None:
    clean = _validate_permissions(permissions)
    admin_permissions = [p for p in clean if p in ADMIN_PERMISSION_CODES]
    if user.role == "admin":
        clean = admin_permissions
        if not clean:
            raise HTTPException(status_code=400, detail="T?i kho?n admin ph?i c? ?t nh?t m?t quy?n qu?n tr? n?ng cao.")
    elif admin_permissions:
        raise HTTPException(
            status_code=400,
            detail="Ng??i d?ng h? th?ng kh?ng ???c c?p quy?n qu?n tr? admin.",
        )
    db.query(UserPermission).filter(UserPermission.user_id == user.id).delete()
    for code in clean:
        db.add(UserPermission(user_id=user.id, permission_code=code))


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


@router.post("/users", response_model=UserOut)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.create_user")),
):
    role = _validate_role(payload.role)

    existed = db.query(User).filter(User.username == payload.username).first()
    if existed:
        raise HTTPException(status_code=400, detail="Username đã tồn tại.")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=role,
        is_active=True,
    )

    db.add(user)
    db.flush()
    if payload.position:
        db.add(UserProfile(user_id=user.id, position=payload.position.strip() or None))
    _set_user_permissions(db, user, payload.permissions)
    db.commit()
    db.refresh(user)

    return _serialize_user(db, user)


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    users = db.query(User).order_by(User.id.desc()).all()
    return [_serialize_user(db, user) for user in users]


@router.get("/roles")
def list_roles(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return {"roles": DEFAULT_ROLES}


@router.get("/permissions")
def list_permissions(
    admin: User = Depends(require_admin),
):
    return {
        "permissions": permission_dicts(),
        "default_staff_permissions": feature_permission_codes(),
    }


@router.patch("/users/{user_id}/role", response_model=UserOut)
def update_user_role(
    user_id: int,
    payload: UpdateRolePayload,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.assign_permissions")),
):
    role = _validate_role(payload.role)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")

    if user.id == admin.id and role != "admin":
        raise HTTPException(
            status_code=400,
            detail="Không thể tự hạ quyền admin của chính mình.",
        )

    user.role = role
    db.query(UserPermission).filter(UserPermission.user_id == user.id).delete()
    default_codes = ADMIN_PERMISSION_CODES if role == "admin" else feature_permission_codes()
    for code in default_codes:
        db.add(UserPermission(user_id=user.id, permission_code=code))
    db.commit()
    db.refresh(user)

    return _serialize_user(db, user)


@router.patch("/users/{user_id}/active", response_model=UserOut)
def update_user_active(
    user_id: int,
    payload: UpdateActivePayload,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.toggle_user")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")

    if user.id == admin.id and not payload.is_active:
        raise HTTPException(
            status_code=400,
            detail="Không thể tự khóa chính tài khoản admin đang đăng nhập.",
        )

    user.is_active = payload.is_active

    # Khoá tài khoản đồng nghĩa thu hồi mọi session đang mở của họ
    if not payload.is_active:
        now = datetime.utcnow()
        sessions = (
            db.query(LoginSession)
            .filter(
                LoginSession.user_id == user.id,
                LoginSession.revoked_at.is_(None),
            )
            .all()
        )
        for s in sessions:
            s.revoked_at = now

    db.commit()
    db.refresh(user)

    return _serialize_user(db, user)


@router.patch("/users/{user_id}/permissions", response_model=UserOut)
def update_user_permissions(
    user_id: int,
    payload: UpdatePermissionsPayload,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.assign_permissions")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")

    _set_user_permissions(db, user, payload.permissions)
    db.commit()
    db.refresh(user)
    return _serialize_user(db, user)


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    payload: ResetPasswordPayload,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.reset_password")),
):
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu phải có ít nhất 6 ký tự.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")

    user.password_hash = hash_password(payload.password)
    now = datetime.utcnow()
    sessions = (
        db.query(LoginSession)
        .filter(LoginSession.user_id == user.id, LoginSession.revoked_at.is_(None))
        .all()
    )
    for s in sessions:
        s.revoked_at = now
    db.commit()
    return {"username": user.username, "message": "?? reset m?t kh?u v? thu h?i c?c phi?n ??ng nh?p c?."}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.delete_user")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Không thể xóa chính tài khoản admin đang đăng nhập.")

    db.query(UserPermission).filter(UserPermission.user_id == user.id).delete()
    db.query(UserProfile).filter(UserProfile.user_id == user.id).delete()
    db.query(LoginSession).filter(LoginSession.user_id == user.id).delete()
    db.delete(user)
    db.commit()
    return {"message": "Đã xóa tài khoản."}


@router.post("/users/bulk")
def bulk_create_users(
    payload: BulkCreateUsersPayload,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_permission("admin.create_user")),
):
    prefix = payload.username_prefix.strip()
    if not prefix:
        raise HTTPException(status_code=400, detail="Tiền tố username không được để trống.")
    if payload.count < 1 or payload.count > 500:
        raise HTTPException(status_code=400, detail="Số lượng tài khoản phải từ 1 đến 500.")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu chung phải có ít nhất 6 ký tự.")
    if not payload.permissions:
        raise HTTPException(status_code=400, detail="Tạo hàng loạt bắt buộc phải chọn phân quyền.")

    role = _validate_role(payload.role)
    permissions = _validate_permissions(payload.permissions)
    created = []
    for i in range(1, payload.count + 1):
        username = f"{prefix}{i:03d}"
        if db.query(User).filter(User.username == username).first():
            raise HTTPException(status_code=400, detail=f"Username đã tồn tại: {username}")
        full_name = f"{payload.full_name_prefix.strip()} {i:03d}" if payload.full_name_prefix else None
        user = User(
            username=username,
            password_hash=hash_password(payload.password),
            full_name=full_name,
            role=role,
            is_active=True,
        )
        db.add(user)
        db.flush()
        if payload.position:
            db.add(UserProfile(user_id=user.id, position=payload.position.strip() or None))
        _set_user_permissions(db, user, permissions)
        created.append({"username": username, "password": payload.password, "role": role})

    db.commit()
    return {"created": created}


@router.get("/users/{user_id}/sessions")
def list_user_sessions(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user.")

    sessions = (
        db.query(LoginSession)
        .filter(LoginSession.user_id == user_id)
        .order_by(LoginSession.last_seen_at.desc())
        .all()
    )

    return [_serialize_admin_session(s) for s in sessions]
