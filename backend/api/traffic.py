import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.dependencies import get_db
from backend.database.models import Camera
from backend.services.traffic_processing import (
    TrafficProcessingError,
    traffic_processor,
)

router = APIRouter(
    prefix="/traffic",
    tags=["Traffic Processing"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LANE_CONFIG_DIR = PROJECT_ROOT / "traffic_detection" / "lane_configs"


class LaneConfigurationRequest(BaseModel):
    lanes: dict[str, list[list[float]]]


def get_camera_or_404(
    camera_id: int,
    db: Session,
):
    camera = (
        db.query(Camera)
        .filter(Camera.id == camera_id)
        .first()
    )

    if camera is None:
        raise HTTPException(
            status_code=404,
            detail=f"Camera with ID {camera_id} was not found.",
        )

    return camera


def get_config_path(camera: Camera) -> Path:
    source_path = Path(camera.source)

    return (
        LANE_CONFIG_DIR
        / f"{source_path.stem}.json"
    )


@router.post("/cameras/{camera_id}/analyze")
def analyze_camera(
    camera_id: int,
    db: Session = Depends(get_db),
):
    """
    Process one frame from a registered camera and return
    vehicle counts and lane occupancy.
    """

    camera = get_camera_or_404(camera_id, db)

    try:
        return traffic_processor.process_camera_frame(camera)

    except TrafficProcessingError as exc:
        message = str(exc)

        if message.startswith(
            "lane_configuration_required:"
        ):
            raise HTTPException(
                status_code=409,
                detail=message,
            ) from exc

        if "model not found" in message.lower():
            raise HTTPException(
                status_code=503,
                detail=message,
            ) from exc

        raise HTTPException(
            status_code=422,
            detail=message,
        ) from exc


@router.get("/cameras/{camera_id}/lanes")
def get_camera_lanes(
    camera_id: int,
    db: Session = Depends(get_db),
):
    """
    Return the saved lane configuration for a registered camera.
    """

    camera = get_camera_or_404(camera_id, db)
    config_path = get_config_path(camera)

    if not config_path.is_file():
        return {
            "camera_id": camera.id,
            "camera_name": camera.name,
            "source": camera.source,
            "config_file": str(config_path),
            "lanes": {},
        }

    try:
        with config_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            lanes = json.load(file)
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read lane configuration: {exc}",
        ) from exc

    if not isinstance(lanes, dict):
        raise HTTPException(
            status_code=500,
            detail="Lane configuration has an invalid format.",
        )

    return {
        "camera_id": camera.id,
        "camera_name": camera.name,
        "source": camera.source,
        "config_file": str(config_path),
        "lanes": lanes,
    }


@router.put("/cameras/{camera_id}/lanes")
def save_camera_lanes(
    camera_id: int,
    lane_data: LaneConfigurationRequest,
    db: Session = Depends(get_db),
):
    """
    Save lane polygons to the existing per-video JSON configuration.
    """

    camera = get_camera_or_404(camera_id, db)
    config_path = get_config_path(camera)

    LANE_CONFIG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not isinstance(lane_data.lanes, dict):
        raise HTTPException(
            status_code=400,
            detail="Lane configuration must be an object.",
        )

    for lane_name, points in lane_data.lanes.items():
        if not isinstance(lane_name, str):
            raise HTTPException(
                status_code=400,
                detail="Lane names must be strings.",
            )

        if not isinstance(points, list) or len(points) < 3:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{lane_name} must contain at least "
                    "3 polygon points."
                ),
            )

        for point in points:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or not all(
                    isinstance(value, (int, float))
                    for value in point
                )
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Invalid point in {lane_name}."
                    ),
                )

    try:
        with config_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                lane_data.lanes,
                file,
                indent=4,
            )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not save lane configuration: {exc}",
        ) from exc

    return {
        "camera_id": camera.id,
        "camera_name": camera.name,
        "source": camera.source,
        "config_file": str(config_path),
        "lanes": lane_data.lanes,
        "status": "saved",
    }