from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DiseaseCode, MonthlyStatistic, PatientRecord, User
from app.security import require_permission

router = APIRouter(prefix="/api/reports", tags=["Reports"])

# Bucket theo tháng tuổi. Định nghĩa cứng để nhất quán giữa các lần báo cáo.
# (label, min_inclusive, max_inclusive). Dùng max_inclusive cho cả khoảng mở
# bằng cách đặt max=None.
AGE_MONTH_BUCKETS: list[tuple[str, int, int | None]] = [
    ("0-1 tháng", 0, 0),
    ("1-6 tháng", 1, 5),
    ("6-12 tháng", 6, 11),
    ("12-24 tháng", 12, 23),
    ("2-5 tuổi", 24, 59),
    ("Trên 5 tuổi", 60, None),
]


def _bucket_label(month_age: int) -> str | None:
    if month_age is None or month_age < 0:
        return None
    for label, lo, hi in AGE_MONTH_BUCKETS:
        if hi is None:
            if month_age >= lo:
                return label
        elif lo <= month_age <= hi:
            return label
    return None


@router.get("/by-age-months")
def report_by_age_months(
    data_type: str = Query("predict_current"),
    period_from: str | None = Query(None, description="YYYY-MM"),
    period_to: str | None = Query(None, description="YYYY-MM"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.reports")),
):
    """
    Báo cáo theo tháng tuổi: gom các nhóm bệnh theo bucket tháng tuổi.
    Dùng PatientRecord vì MonthlyStatistic chỉ có age_group đã gom sẵn.
    """
    query = db.query(
        PatientRecord.month_age,
        PatientRecord.disease_group,
        func.count(PatientRecord.id).label("case_count"),
    ).filter(
        PatientRecord.data_type == data_type,
        PatientRecord.month_age.isnot(None),
    )

    if period_from:
        query = query.filter(PatientRecord.period >= period_from)
    if period_to:
        query = query.filter(PatientRecord.period <= period_to)

    rows = query.group_by(
        PatientRecord.month_age,
        PatientRecord.disease_group,
    ).all()

    # Gom theo bucket
    buckets: dict[str, dict[str, int]] = {label: {} for label, _, _ in AGE_MONTH_BUCKETS}
    bucket_totals: dict[str, int] = {label: 0 for label, _, _ in AGE_MONTH_BUCKETS}

    for r in rows:
        label = _bucket_label(int(r.month_age))
        if label is None:
            continue
        dg = r.disease_group or "Không rõ nhóm bệnh"
        cnt = int(r.case_count or 0)
        buckets[label][dg] = buckets[label].get(dg, 0) + cnt
        bucket_totals[label] += cnt

    output_buckets = []
    for label, _, _ in AGE_MONTH_BUCKETS:
        rows_out = sorted(
            (
                {"disease_group": dg, "case_count": cnt}
                for dg, cnt in buckets[label].items()
            ),
            key=lambda x: x["case_count"],
            reverse=True,
        )
        output_buckets.append({
            "age_bucket": label,
            "total": bucket_totals[label],
            "rows": rows_out,
        })

    return {
        "data_type": data_type,
        "period_from": period_from,
        "period_to": period_to,
        "buckets": output_buckets,
    }


@router.get("/by-month-year")
def report_by_month_year(
    data_type: str = Query("predict_current"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.reports")),
):
    """
    Báo cáo theo tháng-năm: ma trận (year, month) → case_count.
    Mỗi năm trả về 12 dòng cho 12 tháng (kể cả 0 ca) để FE vẽ ổn định.
    """
    rows = db.query(
        MonthlyStatistic.year,
        MonthlyStatistic.month,
        func.sum(MonthlyStatistic.case_count).label("case_count"),
    ).filter(
        MonthlyStatistic.data_type == data_type,
    ).group_by(
        MonthlyStatistic.year,
        MonthlyStatistic.month,
    ).all()

    grouped: dict[int, dict[int, int]] = {}
    for r in rows:
        if r.year is None:
            continue
        grouped.setdefault(int(r.year), {})[int(r.month)] = int(r.case_count or 0)

    out_rows = []
    for year in sorted(grouped.keys()):
        months_map = grouped[year]
        months = [
            {"month": m, "case_count": months_map.get(m, 0)}
            for m in range(1, 13)
        ]
        total = sum(item["case_count"] for item in months)
        out_rows.append({
            "year": year,
            "total": total,
            "months": months,
        })

    return {
        "data_type": data_type,
        "rows": out_rows,
    }


@router.get("/disease-bilingual")
def disease_bilingual(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.reports")),
):
    """
    Map { "Tên tiếng Việt": "English name" } cho FE hiển thị song ngữ khi
    disease_group không sẵn dạng "VN - EN".

    Nguồn: bảng disease_codes. Với mỗi group_name (TENNHOMICD), lấy english_name
    đầu tiên có trong nhóm đó (nếu có).
    """
    rows = db.query(
        DiseaseCode.group_name,
        DiseaseCode.english_name,
    ).filter(
        DiseaseCode.group_name.isnot(None),
        DiseaseCode.english_name.isnot(None),
    ).all()

    mapping: dict[str, str] = {}
    for group_name, english_name in rows:
        vn = (group_name or "").strip()
        en = (english_name or "").strip()
        if not vn or not en:
            continue
        # Lần đầu gặp giữ luôn, lần sau bỏ qua để ổn định.
        mapping.setdefault(vn, en)

    return mapping
