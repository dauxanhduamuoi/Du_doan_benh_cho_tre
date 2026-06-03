import sys
import os
import getpass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.database import Base, engine, SessionLocal
from app.models import User
from app.security import hash_password

Base.metadata.create_all(bind=engine)

db = SessionLocal()

username = os.getenv("ADMIN_USERNAME", "admin")
password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Nhập mật khẩu cho admin mới: ").strip()

if not password:
    raise SystemExit("Mật khẩu admin không được để trống.")

existed = db.query(User).filter(User.username == username).first()

if existed:
    print("Admin đã tồn tại.")
else:
    admin = User(
        username=username,
        password_hash=hash_password(password),
        full_name="Administrator",
        role="admin",
        is_active=True,
    )

    db.add(admin)
    db.commit()

    print("Đã tạo admin mặc định.")
    print("Username:", username)
    print("Password: <không hiển thị>")

db.close()
