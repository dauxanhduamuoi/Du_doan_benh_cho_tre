from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDef:
    code: str
    label: str
    group: str
    description: str = ""


FEATURE_PERMISSIONS = [
    PermissionDef("feature.dashboard", "Tổng quan", "Chức năng nhân viên"),
    PermissionDef("feature.data_import", "Import dữ liệu", "Chức năng nhân viên"),
    PermissionDef("feature.seasonal", "Phân tích theo mùa", "Chức năng nhân viên"),
    PermissionDef("feature.age_analysis", "Phân tích độ tuổi", "Chức năng nhân viên"),
    PermissionDef("feature.monthly_disease", "Nhóm bệnh theo tháng", "Chức năng nhân viên"),
    PermissionDef("feature.gender_analysis", "Phân tích giới tính", "Chức năng nhân viên"),
    PermissionDef("feature.disease_trend", "Xu hướng nhóm bệnh", "Chức năng nhân viên"),
    PermissionDef("feature.forecast", "Dự báo", "Chức năng nhân viên"),
    PermissionDef("feature.weather_risk", "AI thời tiết", "Chức năng nhân viên"),
    PermissionDef("feature.areas", "Khu vực", "Chức năng nhân viên"),
    PermissionDef("feature.reports", "Báo cáo", "Chức năng nhân viên"),
]

ADMIN_PERMISSIONS = [
    PermissionDef("admin.create_user", "Thêm tài khoản", "Quản trị"),
    PermissionDef("admin.delete_user", "Xóa tài khoản", "Quản trị"),
    PermissionDef("admin.reset_password", "Reset mật khẩu", "Quản trị"),
    PermissionDef("admin.assign_permissions", "Phân quyền tài khoản", "Quản trị"),
    PermissionDef("admin.toggle_user", "Khóa/mở tài khoản", "Quản trị"),
]

PERMISSIONS = [*FEATURE_PERMISSIONS, *ADMIN_PERMISSIONS]
PERMISSION_CODES = {p.code for p in PERMISSIONS}
FEATURE_PERMISSION_CODES = {p.code for p in FEATURE_PERMISSIONS}
ADMIN_PERMISSION_CODES = {p.code for p in ADMIN_PERMISSIONS}


def permission_dicts() -> list[dict]:
    return [
        {
            "code": p.code,
            "label": p.label,
            "group": p.group,
            "description": p.description,
        }
        for p in PERMISSIONS
    ]


def feature_permission_codes() -> list[str]:
    return [p.code for p in FEATURE_PERMISSIONS]
