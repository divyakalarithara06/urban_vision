from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database.dependencies import get_db
from backend.database.models import WasteEvent
from backend.services.waste_worker import waste_worker

router = APIRouter(prefix="/waste", tags=["Waste Detection"])


@router.get("/events")
def get_waste_events(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    events = (
        db.query(WasteEvent)
        .order_by(WasteEvent.detected_at.desc(), WasteEvent.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": event.id,
            "camera_id": event.camera_id,
            "camera_name": event.camera_name,
            "detection_type": event.detection_type,
            "detected_at": event.detected_at.isoformat() if event.detected_at else None,
            "telegram_status": event.telegram_status,
            "telegram_detail": event.telegram_detail,
        }
        for event in events
    ]


@router.get("/status")
def get_waste_status():
    status = waste_worker.get_status()
    next_scan = status.get("next_scan_at")
    if isinstance(next_scan, (int, float)):
        status["next_scan_at"] = datetime.fromtimestamp(
            next_scan, tz=timezone.utc
        ).isoformat()
    return status


@router.post("/monitor")
def monitor_waste_now():
    result = waste_worker.trigger_scan()
    if not result.get("accepted"):
        message = result.get("message", "Could not start waste scan")
        if "already running" in message.lower():
            raise HTTPException(status_code=409, detail=message)
        raise HTTPException(status_code=503, detail=message)
    return result
