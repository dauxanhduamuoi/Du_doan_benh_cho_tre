import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, SessionLocal, engine
from app.routers import auth, admin, import_data, dashboard, forecast, public, reports, weather_ai, areas
from app.services.area_service import ensure_area_schema, seed_default_areas


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_area_schema(engine)
    with SessionLocal() as db:
        seed_default_areas(db)
    yield

app = FastAPI(
    title="Seasonal Disease Forecast API",
    description="Backend cho hệ thống phân tích dữ liệu bệnh nhi theo mùa vụ.",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "message": "Seasonal Disease Forecast API is running.",
        "docs": "/docs"
    }

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(import_data.router)
app.include_router(dashboard.router)
app.include_router(forecast.router)
app.include_router(public.router)
app.include_router(reports.router)
app.include_router(weather_ai.router)
app.include_router(areas.router)
