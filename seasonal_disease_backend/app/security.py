from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from .database import get_db
from .models import LoginSession, User, UserPermission

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    to_encode = data.copy()

    expire = datetime.utcnow() + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    to_encode.update({"exp": expire})

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không xác thực được tài khoản.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise _credentials_exception()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = _decode_token(token)
    username = payload.get("sub")

    if not username:
        raise _credentials_exception()

    user = db.query(User).filter(User.username == username).first()

    if not user or not user.is_active:
        raise _credentials_exception()

    sid = payload.get("sid")

    if sid is not None:
        session = db.query(LoginSession).filter(LoginSession.id == sid).first()

        if not session or session.user_id != user.id or session.revoked_at is not None:
            raise _credentials_exception()

        session.last_seen_at = datetime.utcnow()
        db.commit()

    return user


def get_current_session_id(token: str = Depends(oauth2_scheme)) -> int | None:
    """
    Trả về sid trong JWT, dùng để FE biết session nào là current khi liệt kê.
    Trả về None nếu token không có sid (token cũ trước khi có session tracking).
    """
    payload = _decode_token(token)
    sid = payload.get("sid")
    if sid is None:
        return None
    try:
        return int(sid)
    except (TypeError, ValueError):
        return None


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Chỉ admin mới được thực hiện chức năng này.",
        )
    return current_user


def get_user_permissions(db: Session, user: User) -> list[str]:
    rows = (
        db.query(UserPermission.permission_code)
        .filter(UserPermission.user_id == user.id)
        .order_by(UserPermission.permission_code)
        .all()
    )
    return [r[0] for r in rows if r[0]]


def user_has_permission(db: Session, user: User, code: str) -> bool:
    if user.role == "admin" and code.startswith("feature."):
        return True
    # Admin cũ chưa có bảng quyền explicit vẫn có toàn quyền để tránh tự khóa hệ thống.
    permissions = get_user_permissions(db, user)
    if user.role == "admin" and not permissions:
        return True
    return code in permissions


def require_permission(code: str):
    def checker(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        if not user_has_permission(db, current_user, code):
            raise HTTPException(
                status_code=403,
                detail="Tài khoản chưa được phân quyền để thực hiện chức năng này.",
            )
        return current_user

    return checker


def require_any_permission(codes: list[str] | tuple[str, ...]):
    def checker(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        if not any(user_has_permission(db, current_user, code) for code in codes):
            raise HTTPException(
                status_code=403,
                detail="Tài khoản chưa được phân quyền để thực hiện chức năng này.",
            )
        return current_user

    return checker


def require_admin_permission(code: str):
    def checker(
        db: Session = Depends(get_db),
        current_user: User = Depends(require_admin),
    ) -> User:
        if not user_has_permission(db, current_user, code):
            raise HTTPException(
                status_code=403,
                detail="Admin chưa được phân quyền quản trị chức năng này.",
            )
        return current_user

    return checker
