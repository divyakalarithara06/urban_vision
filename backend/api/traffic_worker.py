
from fastapi import APIRouter

from backend.services.traffic_worker import traffic_worker

router = APIRouter(
    prefix="/traffic/worker",
    tags=["Traffic Background Worker"],
)


@router.get("/status")
def get_worker_status():
    return {
        "running": traffic_worker.is_running,
    }


@router.get("/results")
def get_all_latest_results():
    return {
        "results": traffic_worker.get_latest_results(),
    }


@router.get("/results/{camera_id}")
def get_camera_latest_result(camera_id: int):
    result = traffic_worker.get_latest_results(camera_id)

    if result is None:
        return {
            "camera_id": camera_id,
            "status": "no_result",
            "message": (
                "No background processing result is available "
                "for this camera yet."
            ),
        }

    return result
