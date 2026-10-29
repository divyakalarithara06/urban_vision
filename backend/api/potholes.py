from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database.dependencies import get_db
from backend.database.models import PotholeEvent
from backend.services.pothole_worker import pothole_worker

router = APIRouter(prefix="/potholes", tags=["Pothole Detection"])


@router.get("/health")
def pothole_health():
    from backend.services.pothole_worker import MODEL_PATH
    return {
        "status": "ready" if MODEL_PATH.is_file() else "model_missing",
        "model_exists": MODEL_PATH.is_file(),
        "model": str(MODEL_PATH),
    }


@router.get("/events")
def get_pothole_events(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    events = (
        db.query(PotholeEvent)
        .order_by(PotholeEvent.detected_at.desc(), PotholeEvent.id.desc())
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
        }
        for event in events
    ]


@router.get("/status")
def get_pothole_status():
    status = pothole_worker.get_status()
    next_scan = status.get("next_scan_at")
    if isinstance(next_scan, (int, float)):
        status["next_scan_at"] = datetime.fromtimestamp(
            next_scan, tz=timezone.utc
        ).isoformat()
    return status


@router.post("/monitor")
def monitor_potholes_now():
    result = pothole_worker.trigger_scan()
    if not result.get("accepted"):
        message = result.get("message", "Could not start pothole inspection")
        if "already running" in message.lower():
            raise HTTPException(status_code=409, detail=message)
        raise HTTPException(status_code=503, detail=message)
    return result


@router.get("/preview/{camera_id}")
def pothole_preview(camera_id: int):
    import time
    import threading
    import cv2
    from pathlib import Path
    from fastapi.responses import StreamingResponse
    from backend.database.models import Camera
    from backend.services.pothole_worker import (
        _SessionLocal, ROOT, pothole_worker, CONFIDENCE_THRESHOLD
    )

    if _SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database is not configured")

    db = _SessionLocal()
    try:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        if not camera.pothole_enabled:
            raise HTTPException(status_code=400, detail="Pothole detection is disabled for this camera")
        source = camera.source
    finally:
        db.close()

    if not source:
        raise HTTPException(status_code=404, detail="Camera has no video source")

    video_path = Path(source)
    if not video_path.is_absolute():
        video_path = ROOT / video_path
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

    def generate():
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            cap.release()
            return

        stop_event = threading.Event()
        state_lock = threading.Lock()
        state = {
            "frame": None,
            "sequence": 0,
            "generation": 0,
            "detections": [],
        }

        def inference_loop():
            model = None
            last_sequence = -1
            last_generation = -1
            try:
                model = pothole_worker._get_model()
                while not stop_event.is_set():
                    with state_lock:
                        sequence = state["sequence"]
                        generation = state["generation"]
                        frame = state["frame"]

                    if frame is None or sequence == last_sequence:
                        stop_event.wait(0.002)
                        continue

                    # Preserve the existing reduced inference frequency.
                    if generation == last_generation and sequence - last_sequence < 3:
                        stop_event.wait(0.002)
                        continue

                    last_sequence = sequence
                    last_generation = generation
                    try:
                        with pothole_worker._model_lock:
                            result = model.predict(
                                frame, conf=CONFIDENCE_THRESHOLD, verbose=False
                            )[0]

                        detections = []
                        boxes = result.boxes
                        if boxes is not None:
                            names = result.names
                            for box in boxes:
                                coords = box.xyxy[0].cpu().tolist()
                                confidence = float(box.conf[0].item())
                                class_id = int(box.cls[0].item())
                                label = (
                                    names.get(class_id, str(class_id))
                                    if isinstance(names, dict)
                                    else names[class_id]
                                )
                                detections.append((coords, confidence, label))

                        with state_lock:
                            if state["generation"] == generation:
                                state["detections"] = detections
                    except Exception as exc:
                        print(f"[PotholePreview] Inference failed for camera {camera_id}: {exc}")
                        stop_event.wait(0.05)
            except Exception as exc:
                print(f"[PotholePreview] Camera {camera_id} model setup failed: {exc}")

        worker = threading.Thread(
            target=inference_loop,
            name=f"pothole-preview-{camera_id}",
            daemon=True,
        )
        worker.start()
        target_frame_time = 1 / 25

        try:
            while True:
                frame_started = time.perf_counter()
                ok, frame = cap.read()
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                    if not ok:
                        break
                    with state_lock:
                        state["generation"] += 1
                        state["detections"] = []

                with state_lock:
                    state["frame"] = frame.copy()
                    state["sequence"] += 1
                    detections = list(state["detections"])

                annotated = frame.copy()
                for coords, confidence, label in detections:
                    x1, y1, x2, y2 = [int(value) for value in coords]
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 100, 0), 2)
                    cv2.putText(
                        annotated, f"{label} {confidence:.0%}",
                        (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (255, 100, 0), 2, cv2.LINE_AA
                    )

                ok, encoded = cv2.imencode(
                    ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80]
                )
                if ok:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + encoded.tobytes()
                        + b"\r\n"
                    )

                remaining = target_frame_time - (time.perf_counter() - frame_started)
                if remaining > 0:
                    stop_event.wait(remaining)
        except GeneratorExit:
            raise
        except Exception as exc:
            print(f"[PotholePreview] Camera {camera_id} failed: {exc}")
        finally:
            stop_event.set()
            cap.release()
            worker.join(timeout=3)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store"},
    )
