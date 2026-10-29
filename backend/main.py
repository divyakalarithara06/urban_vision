import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.cameras import router as cameras_router
from backend.api.traffic import router as traffic_router
from backend.api.traffic_worker import router as traffic_worker_router
from backend.api.waste import router as waste_router
from backend.api.waste_events import router as waste_events_router
from backend.api.potholes import router as potholes_router
from backend.api.accidents import router as accidents_router
from backend.services.waste_worker import waste_worker
from backend.services.pothole_worker import pothole_worker
from backend.services.traffic_worker import traffic_worker
from backend.services.accident_worker import accident_worker


logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    traffic_worker.start()
    waste_worker.start()
    pothole_worker.start()
    accident_worker.start()
    try:
        yield
    finally:
        waste_worker.stop()
        pothole_worker.stop()
        accident_worker.stop()
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
        "http://localhost:5174",
    "http://127.0.0.1:5174",
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(cameras_router)
app.include_router(traffic_router)
app.include_router(traffic_worker_router)
app.include_router(waste_router)
app.include_router(waste_events_router)
app.include_router(potholes_router)
app.include_router(accidents_router)


@app.get("/")
def root():
    return {
        "message": "UrbanVision API is running",
        "status": "online",
    }

