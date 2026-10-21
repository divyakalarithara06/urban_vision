
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database.dependencies import get_db
from backend.database.models import Camera

router = APIRouter(
    prefix="/cameras",
    tags=["Cameras"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CameraCreate(BaseModel):
    name: str
    source: str
    location: str = "Unknown location"
    source_type: str = "video"
    status: str = "offline"

    traffic_enabled: bool = True
    accident_enabled: bool = True
    pothole_enabled: bool = True
    waste_enabled: bool = True


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    source_type: Optional[str] = None
    status: Optional[str] = None

    traffic_enabled: Optional[bool] = None
    accident_enabled: Optional[bool] = None
    pothole_enabled: Optional[bool] = None
    waste_enabled: Optional[bool] = None


@router.get("/")
def get_cameras(db: Session = Depends(get_db)):
    return db.query(Camera).order_by(Camera.id).all()


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_camera(
    camera_data: CameraCreate,
    db: Session = Depends(get_db),
):
    camera = Camera(**camera_data.dict())
    db.add(camera)

    try:
        db.commit()
        db.refresh(camera)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A camera with this name already exists.",
        )

    return camera


@router.get("/{camera_id}/video")
def get_camera_video(
    camera_id: int,
    db: Session = Depends(get_db),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()

    if camera is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found.",
        )

    if (camera.source_type or "").lower() != "video":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This camera does not use a registered video file.",
        )

    source_path = Path(camera.source)

    if not source_path.is_absolute():
        source_path = PROJECT_ROOT / source_path

    source_path = source_path.resolve()

    if not source_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The registered camera video file was not found.",
        )

    video_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".ogg": "video/ogg",
        ".mov": "video/quicktime",
        ".m4v": "video/x-m4v",
    }

    return FileResponse(
        path=str(source_path),
        media_type=video_types.get(
            source_path.suffix.lower(),
            "application/octet-stream",
        ),
        content_disposition_type="inline",
    )


@router.get("/{camera_id}")
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()

    if camera is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found.",
        )

    return camera


@router.patch("/{camera_id}")
def update_camera(
    camera_id: int,
    camera_data: CameraUpdate,
    db: Session = Depends(get_db),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()

    if camera is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found.",
        )

    updates = camera_data.dict(exclude_unset=True)

    for field, value in updates.items():
        setattr(camera, field, value)

    try:
        db.commit()
        db.refresh(camera)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A camera with this name already exists.",
        )

    return camera


@router.delete("/{camera_id}")
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()

    if camera is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera not found.",
        )

    db.delete(camera)
    db.commit()

    return {
        "message": "Camera deleted successfully.",
        "id": camera_id,
    }
