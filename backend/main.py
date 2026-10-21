import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.cameras import router as cameras_router
from backend.api.traffic import router as traffic_router
from backend.api.traffic_worker import router as traffic_worker_router
from backend.services.traffic_worker import traffic_worker


logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    traffic_worker.start()
    try:
        yield
    finally:
        traffic_worker.stop()


app = FastAPI(
    title="UrbanVision API",
    description="Backend API for the UrbanVision smart-city computer vision platform.",
    version="1.0.0",
    lifespan=lifespan,
)


# Allow the UrbanVision Vite frontend to communicate with FastAPI.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(cameras_router)
app.include_router(traffic_router)
app.include_router(traffic_worker_router)


@app.get("/")
def root():
    return {
        "message": "UrbanVision API is running",
        "status": "online",
    }