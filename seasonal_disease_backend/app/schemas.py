from pydantic import BaseModel

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str | None = None
    role: str = "staff"
    position: str | None = None
    permissions: list[str] = []

class UserOut(BaseModel):
    id: int
    username: str
    full_name: str | None
    role: str
    is_active: bool
    permissions: list[str] = []
    birth_date: str | None = None
    gender: str | None = None
    position: str | None = None

    class Config:
        from_attributes = True

class ForecastOut(BaseModel):
    forecast_period: str
    disease_group: str
    previous_cases: int
    predicted_cases: int
    change_percent: float | None
    trend: str
    risk_level: str

    class Config:
        from_attributes = True

class ForecastGroupSummaryOut(BaseModel):
    forecast_period: str
    disease_group: str
    previous_cases: int
    predicted_cases: int
    change_percent: float | None
    trend: str
    risk_level: str
