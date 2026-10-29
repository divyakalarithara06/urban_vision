from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database.dependencies import get_db
from backend.database.models import AccidentEvent
from backend.services.accident_service import get_health, run_video_test

router = APIRouter(prefix="/accidents", tags=["Accident Detection"])


class AccidentVideoTestRequest(BaseModel):
    video_name: str = Field(
        min_length=1,
        max_length=255,
        description="Filename of a video in the configured accident test-video directory.",
        examples=["accidenttest1.mp4"],
    )


@router.get("/health")
def accident_health():
    return get_health()


@router.post("/test")
def test_accident_video(
    request: AccidentVideoTestRequest,
    db: Session = Depends(get_db),
):
    result = run_video_test(request.video_name)

    # Only persist candidate events when the model flags an accident.
    if result.get("status") == "ACCIDENT_DETECTED":
        candidates = result.get("alert_summary", {}).get("events") or []
        if isinstance(candidates, dict):
            candidates = [candidates]

        saved_count = 0
        try:
            for candidate in candidates:
                trigger_time = float(candidate["alert_trigger_seconds"])
                event = (
                    db.query(AccidentEvent)
                    .filter(
                        AccidentEvent.video_name == request.video_name,
                        AccidentEvent.alert_trigger_seconds == trigger_time,
                    )
                    .first()
                )

                # Re-running the same test does not duplicate the same candidate.
                if event is None:
                    event = AccidentEvent(
                        camera_id=None,
                        camera_name="Test video",
                        source_type="test_video",
                        video_name=request.video_name,
                        detection_type="possible_accident",
                        event_start_seconds=candidate.get("event_start_seconds"),
                        alert_trigger_seconds=trigger_time,
                        event_end_seconds=candidate.get("event_end_seconds"),
                        peak_probability=candidate.get("peak_probability"),
                        windows_in_event=candidate.get("windows_in_event"),
                        experimental=True,
                    )
                    db.add(event)
                    saved_count += 1

            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=503,
                detail=(
                    "Inference completed, but accident events could not be saved. "
                    "Check that the accident_events database migration has been applied."
                ),
            ) from exc

        result["saved_events"] = saved_count
    else:
        result["saved_events"] = 0

    return result


@router.get("/events")
def get_accident_events(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    events = (
        db.query(AccidentEvent)
        .order_by(AccidentEvent.detected_at.desc(), AccidentEvent.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": event.id,
            "camera_id": event.camera_id,
            "camera_name": event.camera_name,
            "source_type": event.source_type,
            "video_name": event.video_name,
            "detection_type": event.detection_type,
            "detected_at": (
                event.detected_at.isoformat() if event.detected_at else None
            ),
            "event_start_seconds": event.event_start_seconds,
            "alert_trigger_seconds": event.alert_trigger_seconds,
            "event_end_seconds": event.event_end_seconds,
            "peak_probability": event.peak_probability,
            "windows_in_event": event.windows_in_event,
            "experimental": event.experimental,
        }
        for event in events
    ]


# Annotated prerecorded-video preview. The GRU analysis remains a separate step.
_PREVIEW_MODEL = None
_PREVIEW_MODEL_LOCK = __import__("threading").Lock()


@router.get("/preview/{video_name}")
def accident_video_preview(video_name: str):
    import threading
    import time
    import cv2
    from pathlib import Path
    from fastapi.responses import StreamingResponse
    from ultralytics import YOLO
    from backend.services.accident_service import VIDEO_DIR, YOLO_PATH

    if not video_name or Path(video_name).name != video_name:
        raise HTTPException(status_code=400, detail="Provide a video filename, not a path.")

    video_path = VIDEO_DIR / video_name
    if video_path.suffix.lower() not in {".mp4", ".avi", ".mov", ".mkv"} or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Test video not found.")

    if not YOLO_PATH.is_file():
        raise HTTPException(status_code=503, detail="Vehicle detection model is missing.")

    def generate():
        global _PREVIEW_MODEL
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            cap.release()
            return

        stop_inference = threading.Event()
        state_lock = threading.Lock()
        shared = {
            "frame": None,
            "frame_number": -1,
            "boxes": [],
            "error": None,
        }

        try:
            if _PREVIEW_MODEL is None:
                with _PREVIEW_MODEL_LOCK:
                    if _PREVIEW_MODEL is None:
                        _PREVIEW_MODEL = YOLO(str(YOLO_PATH))

            source_fps = cap.get(cv2.CAP_PROP_FPS)
            playback_fps = min(
                max(source_fps if source_fps > 0 else 25.0, 1.0), 30.0
            )
            frame_delay = 1.0 / playback_fps

            def inference_loop():
                last_inferred_number = -3

                while not stop_inference.is_set():
                    with state_lock:
                        current_number = shared["frame_number"]
                        frame_to_process = (
                            shared["frame"].copy()
                            if shared["frame"] is not None
                            and current_number - last_inferred_number >= 3
                            else None
                        )

                    if frame_to_process is None:
                        stop_inference.wait(0.005)
                        continue

                    try:
                        with _PREVIEW_MODEL_LOCK:
                            result = _PREVIEW_MODEL.predict(
                                frame_to_process, conf=0.25, verbose=False
                            )[0]

                        boxes = []
                        if result.boxes is not None:
                            names = result.names
                            for box in result.boxes:
                                coords = [
                                    int(v) for v in box.xyxy[0].cpu().tolist()
                                ]
                                confidence = float(box.conf[0].item())
                                class_id = int(box.cls[0].item())
                                label = (
                                    names.get(class_id, str(class_id))
                                    if isinstance(names, dict)
                                    else names[class_id]
                                )
                                boxes.append((coords, confidence, label))

                        with state_lock:
                            shared["boxes"] = boxes
                            shared["error"] = None
                        last_inferred_number = current_number

                    except Exception as exc:
                        with state_lock:
                            shared["error"] = str(exc)[:120]
                        last_inferred_number = current_number

            inference_thread = threading.Thread(
                target=inference_loop,
                name="accident-preview-inference",
                daemon=True,
            )
            inference_thread.start()

            frame_number = 0
            while not stop_inference.is_set():
                started = time.perf_counter()
                ok, frame = cap.read()

                # Loop the selected sample video for continuous preview.
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                    if not ok:
                        break

                with state_lock:
                    shared["frame"] = frame.copy()
                    shared["frame_number"] = frame_number
                    cached_boxes = list(shared["boxes"])
                    inference_error = shared["error"]

                annotated = frame.copy()
                for coords, confidence, label in cached_boxes:
                    x1, y1, x2, y2 = coords
                    cv2.rectangle(
                        annotated, (x1, y1), (x2, y2), (0, 220, 100), 2
                    )
                    cv2.putText(
                        annotated,
                        f"{label} {confidence:.0%}",
                        (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 220, 100),
                        2,
                        cv2.LINE_AA,
                    )

                cv2.putText(
                    annotated,
                    "VEHICLE DETECTION PREVIEW - EXPERIMENTAL",
                    (16, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 220, 100),
                    2,
                    cv2.LINE_AA,
                )

                if inference_error:
                    cv2.putText(
                        annotated,
                        "Detection inference error",
                        (16, 58),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 0, 255),
                        2,
                        cv2.LINE_AA,
                    )

                ok, encoded = cv2.imencode(
                    ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80]
                )
                if ok:
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                        + encoded.tobytes()
                        + b"\r\n"
                    )

                frame_number += 1
                remaining = frame_delay - (time.perf_counter() - started)
                if remaining > 0:
                    time.sleep(remaining)

        finally:
            stop_inference.set()
            cap.release()

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store"},
    )

@router.get("/monitor/status")
def accident_monitor_status():
    from backend.services.accident_worker import accident_worker
    return accident_worker.status()