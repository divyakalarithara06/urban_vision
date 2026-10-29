
from pathlib import Path
import time
import cv2
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database.dependencies import get_db
from backend.database.models import Camera
from backend.api.waste import get_detector, _detector_lock

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




@router.get("/{camera_id}/traffic-preview")
def get_traffic_preview(camera_id: int, db: Session = Depends(get_db)):
    """Stream annotated traffic video while YOLO processes the newest frame asynchronously."""
    import threading

    from backend.services.traffic_processing import (
        traffic_processor,
        MODEL_PATH,
        CONFIDENCE,
    )

    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    if not camera.traffic_enabled:
        raise HTTPException(status_code=403, detail="Traffic detection is disabled.")
    if (camera.source_type or "").lower() != "video":
        raise HTTPException(status_code=400, detail="A registered video is required.")

    video_path = Path(camera.source)
    if not video_path.is_absolute():
        video_path = PROJECT_ROOT / video_path
    video_path = video_path.resolve()

    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Traffic video file not found.")
    if not MODEL_PATH.is_file():
        raise HTTPException(status_code=503, detail=f"Traffic model not found: {MODEL_PATH}")

    def generate():
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            cap.release()
            return

        source_fps = cap.get(cv2.CAP_PROP_FPS)
        frame_delay = 1.0 / min(max(source_fps if source_fps > 0 else 25.0, 1.0), 30.0)

        state_lock = threading.Lock()
        stop_event = threading.Event()
        state = {"frame": None, "sequence": 0, "boxes": [], "error": None}

        def infer_latest_frames():
            last_sequence = -1
            try:
                model = traffic_processor._get_model()
                while not stop_event.is_set():
                    with state_lock:
                        sequence = state["sequence"]
                        frame = state["frame"]
                    if frame is None or sequence == last_sequence:
                        stop_event.wait(0.005)
                        continue

                    last_sequence = sequence
                    with traffic_processor.lock:
                        prediction = model.predict(
                            source=frame,
                            conf=CONFIDENCE,
                            imgsz=640,
                            verbose=False,
                        )[0]

                    boxes = []
                    if prediction.boxes is not None:
                        names = prediction.names
                        for box in prediction.boxes:
                            coords = [int(round(v)) for v in box.xyxy[0].tolist()]
                            confidence = float(box.conf[0])
                            class_id = int(box.cls[0])
                            label = (
                                names.get(class_id, str(class_id))
                                if isinstance(names, dict)
                                else names[class_id]
                            )
                            boxes.append((*coords, confidence, str(label)))

                    with state_lock:
                        state["boxes"] = boxes
            except Exception as exc:
                state["error"] = exc
                print(f"Traffic inference error for camera {camera_id}: {exc}")

        inference_thread = threading.Thread(
            target=infer_latest_frames,
            name=f"traffic-preview-inference-{camera_id}",
            daemon=True,
        )
        inference_thread.start()

        try:
            while not stop_event.is_set():
                started = time.perf_counter()
                ok, frame = cap.read()

                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                    if not ok:
                        break

                with state_lock:
                    state["sequence"] += 1
                    state["frame"] = frame.copy()
                    boxes = list(state["boxes"])

                height, width = frame.shape[:2]
                for x1, y1, x2, y2, confidence, label in boxes:
                    x1 = max(0, min(width - 1, x1))
                    x2 = max(0, min(width - 1, x2))
                    y1 = max(0, min(height - 1, y1))
                    y2 = max(0, min(height - 1, y2))
                    if x2 <= x1 or y2 <= y1:
                        continue

                    color = (50, 220, 80)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    caption = f"{label} {confidence:.0%}"
                    (text_w, text_h), baseline = cv2.getTextSize(
                        caption, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2
                    )
                    top = max(0, y1 - text_h - baseline - 6)
                    cv2.rectangle(
                        frame, (x1, top),
                        (min(width - 1, x1 + text_w + 8), y1),
                        color, -1,
                    )
                    cv2.putText(
                        frame, caption,
                        (x1 + 4, max(text_h, y1 - baseline - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (0, 0, 0), 2, cv2.LINE_AA,
                    )

                encoded_ok, encoded = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
                )
                if encoded_ok:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + encoded.tobytes()
                        + b"\r\n"
                    )

                remaining = frame_delay - (time.perf_counter() - started)
                if remaining > 0:
                    stop_event.wait(remaining)
        finally:
            stop_event.set()
            cap.release()
            inference_thread.join(timeout=2)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store"},
    )


@router.get("/{camera_id}/waste-preview")
def get_waste_preview(camera_id: int, db: Session = Depends(get_db)):
    import threading

    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    if not camera.waste_enabled:
        raise HTTPException(status_code=403, detail="Waste detection is disabled.")
    if (camera.source_type or "").lower() != "video":
        raise HTTPException(status_code=400, detail="A video camera is required.")

    video_path = Path(camera.source)
    if not video_path.is_absolute():
        video_path = PROJECT_ROOT / video_path
    video_path = video_path.resolve()
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found.")

    def generate():
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            cap.release()
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        delay = 1.0 / min(max(fps, 1.0), 25.0)
        key = f"dashboard-preview-{camera_id}"
        stop_event = threading.Event()
        state_lock = threading.Lock()
        state = {
            "frame": None,
            "sequence": 0,
            "generation": 0,
            "detections": [],
        }
        detector_holder = {"detector": None}

        def inference_loop():
            detector = None
            last_sequence = -1
            last_generation = -1
            try:
                detector = get_detector()
                detector_holder["detector"] = detector
                with _detector_lock:
                    detector.reset(key)

                while not stop_event.is_set():
                    with state_lock:
                        sequence = state["sequence"]
                        generation = state["generation"]
                        frame = state["frame"]
                    if frame is None or sequence == last_sequence:
                        stop_event.wait(0.002)
                        continue

                    if generation != last_generation:
                        with _detector_lock:
                            detector.reset(key)
                        last_generation = generation

                    last_sequence = sequence
                    try:
                        with _detector_lock:
                            result = detector.process_frame(frame, camera_id=key)
                        detections = result.get("detections", [])
                        with state_lock:
                            if state["generation"] == generation:
                                state["detections"] = detections
                    except Exception as exc:
                        print(f"[WastePreview] Inference failed for camera {camera_id}: {exc}")
                        stop_event.wait(0.05)
            except Exception as exc:
                print(f"[WastePreview] Camera {camera_id} inference setup failed: {exc}")
            finally:
                if detector is not None:
                    try:
                        with _detector_lock:
                            detector.reset(key)
                    except Exception as exc:
                        print(f"[WastePreview] Reset failed for camera {camera_id}: {exc}")

        worker = threading.Thread(
            target=inference_loop,
            name=f"waste-preview-{camera_id}",
            daemon=True,
        )
        worker.start()

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

                h, w = frame.shape[:2]
                for d in detections:
                    bbox = d.get("bbox")
                    if not bbox or len(bbox) != 4:
                        continue
                    x1, y1, x2, y2 = [int(v) for v in bbox]
                    x1, x2 = max(0, min(x1, w - 1)), max(0, min(x2, w - 1))
                    y1, y2 = max(0, min(y1, h - 1)), max(0, min(y2, h - 1))
                    color = (0, 0, 255) if d.get("is_waste") else (0, 200, 255)
                    label = f"{d.get('type', 'object')} {float(d.get('confidence', 0)):.0%}"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(
                        frame, label, (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA
                    )

                ok, encoded = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
                )
                if ok:
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                        + encoded.tobytes() + b"\r\n"
                    )

                remaining = delay - (time.perf_counter() - frame_started)
                if remaining > 0:
                    stop_event.wait(remaining)
        except GeneratorExit:
            raise
        except Exception as exc:
            print(f"[WastePreview] Camera {camera_id} failed: {exc}")
        finally:
            stop_event.set()
            cap.release()
            worker.join(timeout=3)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store"},
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



