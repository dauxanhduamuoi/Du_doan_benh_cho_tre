from sqlalchemy import func
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MonthlyStatistic, PatientRecord, User
from app.security import require_any_permission, require_permission
from app.services.data_processing_service import month_to_season_vn

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

# Dashboard chỉ phân tích dữ liệu người dùng import vào /api/import/predict-current.
# Dù tên file là predict_current.xlsx, predict_current_2.xlsx hay tên khác,
# khi import qua API predict-current thì backend lưu data_type cố định là "predict_current".
DASHBOARD_DATA_TYPE = "predict_current"


def make_trend(current_cases: int, previous_cases: int):
    current_cases = int(current_cases or 0)
    previous_cases = int(previous_cases or 0)

    if previous_cases > 0:
        change_percent = (current_cases - previous_cases) / previous_cases * 100
    else:
        change_percent = None

    if previous_cases == 0 and current_cases > 0:
        trend = "Tăng từ 0 ca"
    elif change_percent is None:
        trend = "Không đủ dữ liệu"
    elif change_percent >= 30:
        trend = "Tăng mạnh"
    elif change_percent >= 10:
        trend = "Tăng"
    elif change_percent <= -30:
        trend = "Giảm mạnh"
    elif change_percent <= -10:
        trend = "Giảm"
    else:
        trend = "Ổn định"

    return round(change_percent, 2) if change_percent is not None else None, trend


def previous_period(period: str) -> str:
    year, month = period.split("-")
    year = int(year)
    month = int(month)

    if month == 1:
        return f"{year - 1}-12"

    return f"{year}-{month - 1:02d}"


@router.get("/overview")
def overview(
    data_type: str = Query(DASHBOARD_DATA_TYPE),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.dashboard")),
):
    total_records = db.query(PatientRecord).filter(
        PatientRecord.data_type == data_type
    ).count()

    total_cases = db.query(func.sum(MonthlyStatistic.case_count)).filter(
        MonthlyStatistic.data_type == data_type
    ).scalar() or 0

    periods = db.query(MonthlyStatistic.period).filter(
        MonthlyStatistic.data_type == data_type
    ).distinct().all()

    groups = db.query(MonthlyStatistic.disease_group).filter(
        MonthlyStatistic.data_type == data_type
    ).distinct().all()

    max_month_row = db.query(
        MonthlyStatistic.period,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type
    ).group_by(
        MonthlyStatistic.period
    ).order_by(
        func.sum(MonthlyStatistic.case_count).desc()
    ).first()

    top_group_row = db.query(
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type
    ).group_by(
        MonthlyStatistic.disease_group
    ).order_by(
        func.sum(MonthlyStatistic.case_count).desc()
    ).first()

    return {
        "data_type": data_type,
        "total_records": total_records,
        "total_cases_from_monthly_statistics": int(total_cases),
        "total_periods": len(periods),
        "total_disease_groups": len(groups),
        "max_month": {
            "period": max_month_row.period,
            "case_count": int(max_month_row.case_count),
        } if max_month_row else None,
        "top_disease_group": {
            "disease_group": top_group_row.disease_group,
            "case_count": int(top_group_row.case_count),
        } if top_group_row else None,
    }


@router.get("/monthly-statistics")
def monthly_statistics(
    data_type: str = Query(DASHBOARD_DATA_TYPE),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission(("feature.dashboard", "feature.monthly_disease", "feature.gender_analysis", "feature.disease_trend", "feature.reports"))),
):
    rows = db.query(
        MonthlyStatistic.period,
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type
    ).group_by(
        MonthlyStatistic.period,
        MonthlyStatistic.disease_group
    ).order_by(
        MonthlyStatistic.period
    ).all()

    return [
        {
            "period": r.period,
            "disease_group": r.disease_group,
            "case_count": int(r.case_count),
        }
        for r in rows
    ]


@router.get("/top-disease-groups")
def top_disease_groups(
    data_type: str = Query(DASHBOARD_DATA_TYPE),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission(("feature.dashboard", "feature.reports"))),
):
    rows = db.query(
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type
    ).group_by(
        MonthlyStatistic.disease_group
    ).order_by(
        func.sum(MonthlyStatistic.case_count).desc()
    ).limit(limit).all()

    return [
        {
            "disease_group": r.disease_group,
            "case_count": int(r.case_count),
        }
        for r in rows
    ]


@router.get("/cases-by-month")
def cases_by_month(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.dashboard")),
):
    data_type = DASHBOARD_DATA_TYPE

    rows = db.query(
        MonthlyStatistic.period,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type
    ).group_by(
        MonthlyStatistic.period
    ).order_by(
        MonthlyStatistic.period
    ).all()

    return [
        {
            "period": r.period,
            "case_count": int(r.case_count),
        }
        for r in rows
    ]


@router.get("/cases-by-year")
def cases_by_year(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.dashboard")),
):
    data_type = DASHBOARD_DATA_TYPE

    rows = db.query(
        MonthlyStatistic.year,
        MonthlyStatistic.month,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.year.isnot(None),
        MonthlyStatistic.month.isnot(None),
    ).group_by(
        MonthlyStatistic.year,
        MonthlyStatistic.month
    ).order_by(
        MonthlyStatistic.year,
        MonthlyStatistic.month
    ).all()

    grouped: dict[int, dict] = {}
    for r in rows:
        year = int(r.year)
        month = int(r.month)
        item = grouped.setdefault(year, {"case_count": 0, "months": set()})
        item["case_count"] += int(r.case_count or 0)
        if 1 <= month <= 12:
            item["months"].add(month)

    output = []
    for year in sorted(grouped):
        months = sorted(grouped[year]["months"])
        missing_months = [m for m in range(1, 13) if m not in months]
        output.append({
            "year": year,
            "case_count": grouped[year]["case_count"],
            "month_count": len(months),
            "months": months,
            "missing_months": missing_months,
            "is_complete_year": len(months) == 12,
        })

    return output


@router.get("/top-disease-groups-by-month")
def top_disease_groups_by_month(
    period: str = Query(..., description="Tháng cần xem, ví dụ: 2025-04"),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.monthly_disease")),
):
    data_type = DASHBOARD_DATA_TYPE

    rows = db.query(
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.period == period
    ).group_by(
        MonthlyStatistic.disease_group
    ).order_by(
        func.sum(MonthlyStatistic.case_count).desc()
    ).limit(limit).all()

    return [
        {
            "period": period,
            "disease_group": r.disease_group,
            "case_count": int(r.case_count),
        }
        for r in rows
    ]


@router.get("/disease-percentage-by-month")
def disease_percentage_by_month(
    period: str = Query(..., description="Tháng cần xem, ví dụ: 2025-04"),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.monthly_disease")),
):
    data_type = DASHBOARD_DATA_TYPE

    total_cases = db.query(
        func.sum(MonthlyStatistic.case_count)
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.period == period
    ).scalar() or 0

    rows = db.query(
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.period == period
    ).group_by(
        MonthlyStatistic.disease_group
    ).order_by(
        func.sum(MonthlyStatistic.case_count).desc()
    ).limit(limit).all()

    output = []

    for r in rows:
        case_count = int(r.case_count or 0)
        percentage = (case_count / total_cases * 100) if total_cases > 0 else 0

        output.append({
            "period": period,
            "disease_group": r.disease_group,
            "case_count": case_count,
            "total_cases_in_month": int(total_cases),
            "percentage": round(percentage, 2),
        })

    return output


@router.get("/seasonal-summary")
def seasonal_summary(
    season: str | None = Query(None, description="Có thể truyền Mùa khô hoặc Mùa mưa"),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.seasonal")),
):
    data_type = DASHBOARD_DATA_TYPE

    query = db.query(
        MonthlyStatistic.season,
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type
    )

    if season:
        query = query.filter(MonthlyStatistic.season == season)

    rows = query.group_by(
        MonthlyStatistic.season,
        MonthlyStatistic.disease_group
    ).order_by(
        MonthlyStatistic.season,
        func.sum(MonthlyStatistic.case_count).desc()
    ).all()

    if season:
        rows = rows[:limit]

    return [
        {
            "season": r.season,
            "disease_group": r.disease_group,
            "case_count": int(r.case_count),
        }
        for r in rows
    ]


@router.get("/monthly-comparison")
def monthly_comparison(
    period: str = Query(..., description="Tháng cần so sánh, ví dụ: 2025-04"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.monthly_disease")),
):
    data_type = DASHBOARD_DATA_TYPE
    prev_period = previous_period(period)

    current_rows = db.query(
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("current_cases")
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.period == period
    ).group_by(
        MonthlyStatistic.disease_group
    ).all()

    previous_rows = db.query(
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("previous_cases")
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.period == prev_period
    ).group_by(
        MonthlyStatistic.disease_group
    ).all()

    current_map = {
        r.disease_group: int(r.current_cases or 0)
        for r in current_rows
    }

    previous_map = {
        r.disease_group: int(r.previous_cases or 0)
        for r in previous_rows
    }

    all_groups = set(current_map.keys()) | set(previous_map.keys())

    output = []

    for group in all_groups:
        current_cases = current_map.get(group, 0)
        previous_cases = previous_map.get(group, 0)
        change_percent, trend = make_trend(current_cases, previous_cases)

        output.append({
            "period": period,
            "previous_period": prev_period,
            "disease_group": group,
            "previous_cases": previous_cases,
            "current_cases": current_cases,
            "change_percent": change_percent,
            "trend": trend,
        })

    output = sorted(
        output,
        key=lambda x: abs(x["current_cases"] - x["previous_cases"]),
        reverse=True
    )

    return output[:limit]


# =========================================================
# LỌC THEO KHOẢNG THÁNG TUỔI (thay vì phân nhóm cứng)
# =========================================================
@router.get("/cases-by-age-range")
def cases_by_age_range(
    period: str | None = Query(None, description="Nếu muốn lọc theo tháng, ví dụ: 2025-04"),
    min_month_age: int | None = Query(None, description="Tháng tuổi tối thiểu (bao gồm)"),
    max_month_age: int | None = Query(None, description="Tháng tuổi tối đa (bao gồm)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.age_analysis")),
):
    """
    Đếm số ca theo khoảng tháng tuổi do người dùng tự chọn.
    Nếu không truyền min/max thì trả toàn bộ.
    """
    data_type = DASHBOARD_DATA_TYPE

    query = db.query(
        PatientRecord.month_age,
        func.count(PatientRecord.id).label("case_count")
    ).filter(
        PatientRecord.data_type == data_type,
        PatientRecord.month_age.isnot(None)
    )

    if period:
        query = query.filter(PatientRecord.period == period)

    if min_month_age is not None:
        query = query.filter(PatientRecord.month_age >= min_month_age)

    if max_month_age is not None:
        query = query.filter(PatientRecord.month_age <= max_month_age)

    total = query.with_entities(func.count(PatientRecord.id)).scalar() or 0

    return {
        "period": period if period else "all",
        "min_month_age": min_month_age,
        "max_month_age": max_month_age,
        "total_cases": total,
    }


@router.get("/disease-by-age-range")
def disease_by_age_range(
    period: str | None = Query(None, description="Nếu muốn lọc theo tháng"),
    min_month_age: int | None = Query(None, description="Tháng tuổi tối thiểu (bao gồm)"),
    max_month_age: int | None = Query(None, description="Tháng tuổi tối đa (bao gồm)"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.age_analysis")),
):
    """
    Đếm số ca theo nhóm bệnh, lọc theo khoảng tháng tuổi do người dùng tự chọn.
    """
    data_type = DASHBOARD_DATA_TYPE

    query = db.query(
        PatientRecord.disease_group,
        PatientRecord.period,
        func.count(PatientRecord.id).label("case_count")
    ).filter(
        PatientRecord.data_type == data_type,
        PatientRecord.month_age.isnot(None),
        PatientRecord.period.isnot(None),
    )

    if period:
        query = query.filter(PatientRecord.period == period)

    if min_month_age is not None:
        query = query.filter(PatientRecord.month_age >= min_month_age)

    if max_month_age is not None:
        query = query.filter(PatientRecord.month_age <= max_month_age)

    rows = query.group_by(
        PatientRecord.disease_group,
        PatientRecord.period,
    ).all()

    grouped: dict[str, dict] = {}
    for r in rows:
        disease_group = r.disease_group or "Không rõ nhóm bệnh"
        item = grouped.setdefault(
            disease_group,
            {
                "period": period if period else "all",
                "min_month_age": min_month_age,
                "max_month_age": max_month_age,
                "disease_group": disease_group,
                "case_count": 0,
                "period_distribution": [],
            },
        )
        case_count = int(r.case_count or 0)
        item["case_count"] += case_count
        item["period_distribution"].append({
            "period": r.period,
            "case_count": case_count,
        })

    output = []
    for item in grouped.values():
        item["period_distribution"].sort(key=lambda x: x["period"])
        peak = max(item["period_distribution"], key=lambda x: x["case_count"], default=None)
        item["peak_period"] = peak["period"] if peak else None
        item["peak_period_cases"] = peak["case_count"] if peak else 0
        item["first_period"] = item["period_distribution"][0]["period"] if item["period_distribution"] else None
        item["latest_period"] = item["period_distribution"][-1]["period"] if item["period_distribution"] else None
        output.append(item)

    output.sort(key=lambda x: x["case_count"], reverse=True)
    return output[:limit]


@router.get("/cases-by-gender")
def cases_by_gender(
    period: str | None = Query(None, description="Nếu muốn lọc theo tháng, ví dụ: 2025-04"),
    year: int | None = Query(None, ge=1900, le=3000, description="Nếu muốn lọc theo năm, ví dụ: 2025"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.gender_analysis")),
):
    data_type = DASHBOARD_DATA_TYPE

    query = db.query(
        PatientRecord.gender,
        func.count(PatientRecord.id).label("case_count")
    ).filter(
        PatientRecord.data_type == data_type
    )

    if period:
        query = query.filter(PatientRecord.period == period)
    elif year:
        query = query.filter(PatientRecord.year == year)

    rows = query.group_by(
        PatientRecord.gender
    ).order_by(
        func.count(PatientRecord.id).desc()
    ).all()

    total_cases = sum(int(r.case_count or 0) for r in rows)

    output = []

    for r in rows:
        case_count = int(r.case_count or 0)
        percentage = (case_count / total_cases * 100) if total_cases > 0 else 0

        output.append({
            "period": period if period else (str(year) if year else "all"),
            "gender": r.gender if r.gender else "Không rõ",
            "case_count": case_count,
            "percentage": round(percentage, 2),
        })

    return output


@router.get("/disease-trend")
def disease_trend(
    disease_group: str = Query(..., description="Nhóm bệnh cần xem xu hướng"),
    start_period: str | None = Query(None, description="Từ tháng nào, ví dụ: 2024-01"),
    end_period: str | None = Query(None, description="Đến tháng nào, ví dụ: 2025-12"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.disease_trend")),
):
    """
    Số ca theo tháng của 1 nhóm bệnh cụ thể.
    Dùng để vẽ biểu đồ đường xu hướng.
    """
    data_type = DASHBOARD_DATA_TYPE

    query = db.query(
        MonthlyStatistic.period,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.disease_group == disease_group
    )

    if start_period:
        query = query.filter(MonthlyStatistic.period >= start_period)

    if end_period:
        query = query.filter(MonthlyStatistic.period <= end_period)

    rows = query.group_by(
        MonthlyStatistic.period
    ).order_by(
        MonthlyStatistic.period
    ).all()

    return [
        {
            "period": r.period,
            "disease_group": disease_group,
            "case_count": int(r.case_count),
        }
        for r in rows
    ]


@router.get("/year-over-year")
def year_over_year(
    month: int = Query(..., ge=1, le=12, description="Tháng cần so sánh, ví dụ: 6"),
    disease_group: str | None = Query(None, description="Lọc theo nhóm bệnh, nếu không truyền thì tính tổng"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission(("feature.seasonal", "feature.disease_trend"))),
):
    """
    So sánh số ca của cùng 1 tháng qua các năm.
    Ví dụ: tháng 6/2023 vs 6/2024 vs 6/2025.
    """
    data_type = DASHBOARD_DATA_TYPE

    query = db.query(
        MonthlyStatistic.year,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.month == month
    )

    if disease_group:
        query = query.filter(MonthlyStatistic.disease_group == disease_group)

    rows = query.group_by(
        MonthlyStatistic.year
    ).order_by(
        MonthlyStatistic.year
    ).all()

    return [
        {
            "year": r.year,
            "month": month,
            "disease_group": disease_group if disease_group else "all",
            "case_count": int(r.case_count),
        }
        for r in rows
    ]


@router.get("/seasonal-peak")
def seasonal_peak(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.seasonal")),
):
    """
    Tháng đỉnh điểm (có nhiều ca nhất) của mỗi nhóm bệnh.
    Tính trung bình số ca theo tháng (1-12) qua tất cả các năm,
    rồi lấy tháng có trung bình cao nhất.
    """
    data_type = DASHBOARD_DATA_TYPE

    # Tính trung bình số ca theo (disease_group, month) qua tất cả năm
    rows = db.query(
        MonthlyStatistic.disease_group,
        MonthlyStatistic.month,
        func.avg(MonthlyStatistic.case_count).label("avg_cases")
    ).filter(
        MonthlyStatistic.data_type == data_type
    ).group_by(
        MonthlyStatistic.disease_group,
        MonthlyStatistic.month
    ).all()

    # Tìm tháng có avg cao nhất cho mỗi disease_group
    best = {}

    for r in rows:
        disease_group = r.disease_group
        avg_cases = float(r.avg_cases or 0)

        if disease_group not in best or avg_cases > best[disease_group]["avg_cases"]:
            best[disease_group] = {
                "disease_group": disease_group,
                "peak_month": r.month,
                "avg_cases": avg_cases,
            }

    # Thêm season và sắp xếp theo avg_cases giảm dần

    output = []
    for item in best.values():
        item["season"] = month_to_season_vn(item["peak_month"])
        item["avg_cases"] = round(item["avg_cases"], 1)
        output.append(item)

    output.sort(key=lambda x: x["avg_cases"], reverse=True)

    return output[:limit]


@router.get("/disease-by-gender")
def disease_by_gender(
    period: str | None = Query(None, description="Lọc theo tháng, ví dụ: 2025-04"),
    year: int | None = Query(None, ge=1900, le=3000, description="Lọc theo năm, ví dụ: 2025"),
    disease_group: str | None = Query(None, description="Lọc 1 nhóm bệnh cụ thể"),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.gender_analysis")),
):
    """
    Phân bố nhóm bệnh theo giới tính.
    Trả về số ca nam/nữ và tỷ lệ % cho mỗi nhóm bệnh.
    """
    data_type = DASHBOARD_DATA_TYPE

    query = db.query(
        PatientRecord.disease_group,
        PatientRecord.gender,
        func.count(PatientRecord.id).label("case_count")
    ).filter(
        PatientRecord.data_type == data_type
    )

    if period:
        query = query.filter(PatientRecord.period == period)
    elif year:
        query = query.filter(PatientRecord.year == year)

    if disease_group:
        query = query.filter(PatientRecord.disease_group == disease_group)

    rows = query.group_by(
        PatientRecord.disease_group,
        PatientRecord.gender
    ).all()

    # Gom theo disease_group
    grouped = {}
    for r in rows:
        dg = r.disease_group or "Không rõ nhóm bệnh"
        if dg not in grouped:
            grouped[dg] = {"male": 0, "female": 0, "other": 0}

        gender = (r.gender or "").strip().lower()
        if gender in ("nam", "male", "m"):
            grouped[dg]["male"] += int(r.case_count)
        elif gender in ("nữ", "nu", "female", "f"):
            grouped[dg]["female"] += int(r.case_count)
        else:
            grouped[dg]["other"] += int(r.case_count)

    output = []
    for dg, counts in grouped.items():
        total = counts["male"] + counts["female"] + counts["other"]
        output.append({
            "disease_group": dg,
            "male_cases": counts["male"],
            "female_cases": counts["female"],
            "other_cases": counts["other"],
            "total_cases": total,
            "male_percent": round(counts["male"] / total * 100, 1) if total > 0 else 0,
            "female_percent": round(counts["female"] / total * 100, 1) if total > 0 else 0,
        })

    output.sort(key=lambda x: x["total_cases"], reverse=True)

    return output[:limit]


@router.get("/disease-season-comparison")
def disease_season_comparison(
    disease_group: str | None = Query(None, description="Lọc 1 nhóm bệnh cụ thể"),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.seasonal")),
):
    """
    So sánh số ca mùa khô vs mùa mưa cho mỗi nhóm bệnh.
    Trả về nhóm bệnh nào mùa khô nhiều, nhóm nào mùa mưa nhiều.
    """
    data_type = DASHBOARD_DATA_TYPE

    query = db.query(
        MonthlyStatistic.disease_group,
        MonthlyStatistic.season,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type
    )

    if disease_group:
        query = query.filter(MonthlyStatistic.disease_group == disease_group)

    rows = query.group_by(
        MonthlyStatistic.disease_group,
        MonthlyStatistic.season
    ).all()

    # Gom theo disease_group
    grouped = {}
    for r in rows:
        dg = r.disease_group
        if dg not in grouped:
            grouped[dg] = {"dry": 0, "rainy": 0}

        if r.season == "Mùa khô":
            grouped[dg]["dry"] += int(r.case_count)
        elif r.season == "Mùa mưa":
            grouped[dg]["rainy"] += int(r.case_count)

    output = []
    for dg, counts in grouped.items():
        total = counts["dry"] + counts["rainy"]
        if counts["dry"] > counts["rainy"]:
            dominant = "Mùa khô"
        elif counts["rainy"] > counts["dry"]:
            dominant = "Mùa mưa"
        else:
            dominant = "Ngang nhau"

        output.append({
            "disease_group": dg,
            "dry_season_cases": counts["dry"],
            "rainy_season_cases": counts["rainy"],
            "total_cases": total,
            "dominant_season": dominant,
            "dry_percent": round(counts["dry"] / total * 100, 1) if total > 0 else 0,
            "rainy_percent": round(counts["rainy"] / total * 100, 1) if total > 0 else 0,
        })

    output.sort(key=lambda x: x["total_cases"], reverse=True)

    return output[:limit]


@router.get("/periods")
def get_periods(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission(("feature.dashboard", "feature.monthly_disease", "feature.gender_analysis", "feature.disease_trend", "feature.age_analysis", "feature.seasonal", "feature.reports"))),
):
    """
    Danh sách tất cả tháng có dữ liệu trong predict_current.
    Frontend dùng để render dropdown chọn period.
    """
    data_type = DASHBOARD_DATA_TYPE

    rows = db.query(
        MonthlyStatistic.period,
        MonthlyStatistic.year,
        MonthlyStatistic.month,
        MonthlyStatistic.season
    ).filter(
        MonthlyStatistic.data_type == data_type
    ).group_by(
        MonthlyStatistic.period,
        MonthlyStatistic.year,
        MonthlyStatistic.month,
        MonthlyStatistic.season
    ).order_by(
        MonthlyStatistic.period
    ).all()

    return [
        {
            "period": r.period,
            "year": r.year,
            "month": r.month,
            "season": r.season,
        }
        for r in rows
    ]


@router.get("/disease-groups")
def get_disease_groups(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission(("feature.disease_trend", "feature.gender_analysis", "feature.reports"))),
):
    """
    Danh sách tất cả nhóm bệnh có dữ liệu trong predict_current.
    Frontend dùng cho dropdown/filter chọn nhóm bệnh.
    """
    data_type = DASHBOARD_DATA_TYPE

    rows = db.query(
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("total_cases")
    ).filter(
        MonthlyStatistic.data_type == data_type
    ).group_by(
        MonthlyStatistic.disease_group
    ).order_by(
        func.sum(MonthlyStatistic.case_count).desc()
    ).all()

    return [
        {
            "disease_group": r.disease_group,
            "total_cases": int(r.total_cases),
        }
        for r in rows
    ]


@router.get("/summary-card")
def summary_card(
    period: str = Query(..., description="Tháng cần xem, ví dụ: 2025-04"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("feature.monthly_disease")),
):
    """
    Widget tổng quan cho trang chủ dashboard.
    Trả về: tổng ca tháng này, so sánh tháng trước, xu hướng, top 3 bệnh.
    """
    data_type = DASHBOARD_DATA_TYPE
    prev_period_str = previous_period(period)

    # Tổng ca tháng này
    total_cases = db.query(
        func.sum(MonthlyStatistic.case_count)
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.period == period
    ).scalar() or 0
    total_cases = int(total_cases)

    # Tổng ca tháng trước
    prev_cases = db.query(
        func.sum(MonthlyStatistic.case_count)
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.period == prev_period_str
    ).scalar() or 0
    prev_cases = int(prev_cases)

    # Tính % thay đổi và xu hướng
    change_percent, trend = make_trend(total_cases, prev_cases)

    # Top 3 nhóm bệnh tháng này
    top3 = db.query(
        MonthlyStatistic.disease_group,
        func.sum(MonthlyStatistic.case_count).label("case_count")
    ).filter(
        MonthlyStatistic.data_type == data_type,
        MonthlyStatistic.period == period
    ).group_by(
        MonthlyStatistic.disease_group
    ).order_by(
        func.sum(MonthlyStatistic.case_count).desc()
    ).limit(3).all()

    # Mùa của tháng này
    month_num = int(period.split("-")[1])
    season = month_to_season_vn(month_num)

    return {
        "period": period,
        "previous_period": prev_period_str,
        "total_cases": total_cases,
        "previous_month_cases": prev_cases,
        "change_percent": change_percent,
        "trend": trend,
        "season": season,
        "top_3_diseases": [
            {
                "disease_group": r.disease_group,
                "case_count": int(r.case_count),
            }
            for r in top3
        ],
    }
