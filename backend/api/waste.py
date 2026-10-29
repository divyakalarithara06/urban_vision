from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/waste", tags=["Waste Detection"])

MODEL_DIR = Path(__file__).resolve().parents[1] / "services" / "waste_detection" / "models"
_detector = None
_detector_lock = Lock()


def get_detector():
    global _detector
    if _detector is None:
        with _detector_lock:
            if _detector is None:
                from backend.services.waste_detection.waste_engine import WasteDetector

                road_model = MODEL_DIR / "waste_road_detector_v1.pt"
                pile_model = MODEL_DIR / "waste_pile_detector_v2.pt"

                if not road_model.is_file() or not pile_model.is_file():
                    raise HTTPException(
                        status_code=500,
                        detail="Waste detection model files are missing.",
                    )

                try:
                    _detector = WasteDetector({
                        "road_model": str(road_model),
                        "pile_model": str(pile_model),
                    })
                except Exception as exc:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Could not initialize waste detection models: {exc}",
                    ) from exc
    return _detector


@router.get("/health")
def waste_health():
    return {
        "status": "ready",
        "models": {
            "road": (MODEL_DIR / "waste_road_detector_v1.pt").is_file(),
            "pile": (MODEL_DIR / "waste_pile_detector_v2.pt").is_file(),
        },
    }


@router.post("/detect")
async def detect_waste(request: Request, camera_id: str = "upload"):
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("image/") and "application/octet-stream" not in content_type:
        raise HTTPException(
            status_code=415,
            detail="Send the image as the raw request body with an image/* content type.",
        )

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="The image body is empty.")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image exceeds the 15 MB limit.")

    image_array = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="The request body is not a valid image.")

    detector = get_detector()
    try:
        with _detector_lock:
            result = detector.process_frame(frame, camera_id=camera_id[:100])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Waste detection failed: {exc}") from exc
