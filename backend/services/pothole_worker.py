import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cv2
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Camera, PotholeEvent
from backend.services.telegram_notifier import send_telegram_alert

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "backend" / "services" / "pothole_detection" / "models" / "pothole_detector.pt"
DATABASE_URL = os.getenv("DATABASE_URL")
INTERVAL_SECONDS = 2 * 60 * 60
SAMPLE_FRACTIONS = (0.15, 0.50, 0.85)
CONFIDENCE_THRESHOLD = 0.35

_engine = create_engine(DATABASE_URL) if DATABASE_URL else None
_SessionLocal = sessionmaker(bind=_engine) if _engine else None


class PotholeWorker:
    def __init__(self):
        self._lock = threading.Lock()
        self._model_lock = threading.Lock()
        self._stop = threading.Event()
        self._scheduler_thread = None
        self._scan_thread = None
        self._scan_running = False
        self._model = None
        self._status = {
            "state": "idle",
            "message": "Waiting for the first pothole scan",
            "started_at": None,
            "finished_at": None,
            "last_scan_at": None,
            "next_scan_at": None,
            "cameras_total": 0,
            "cameras_done": 0,
            "events_created": 0,
        }

    def start(self):
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        if _engine is None:
            self._status.update({
                "state": "error",
                "message": "DATABASE_URL is not configured",
            })
            return
        PotholeEvent.__table__.create(bind=_engine, checkfirst=True)
        self._stop.clear()
        self._scheduler_thread = threading.Thread(
            target=self._schedule_loop, name="pothole-scheduler", daemon=True
        )
        self._scheduler_thread.start()
        self.trigger_scan()

    def stop(self):
        self._stop.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=3)

    def trigger_scan(self):
        with self._lock:
            if self._scan_running:
                return {"accepted": False, "message": "A pothole scan is already running"}
            if _SessionLocal is None:
                return {"accepted": False, "message": "DATABASE_URL is not configured"}
            self._scan_running = True
            self._status.update({
                "state": "running",
                "message": "Scanning enabled pothole cameras",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "cameras_total": 0,
                "cameras_done": 0,
                "events_created": 0,
            })
            self._scan_thread = threading.Thread(
                target=self._run_scan, name="pothole-scan", daemon=True
            )
            self._scan_thread.start()
            return {"accepted": True, "message": "Pothole inspection started"}

    def get_status(self):
        with self._lock:
            result = dict(self._status)
            result["scan_running"] = self._scan_running
            result["interval_seconds"] = INTERVAL_SECONDS
            return result

    def _schedule_loop(self):
        next_run = time.monotonic() + INTERVAL_SECONDS
        with self._lock:
            self._status["next_scan_at"] = (
                datetime.now(timezone.utc).timestamp() + INTERVAL_SECONDS
            )
        while not self._stop.wait(2):
            if time.monotonic() >= next_run:
                self.trigger_scan()
                next_run = time.monotonic() + INTERVAL_SECONDS
                with self._lock:
                    self._status["next_scan_at"] = (
                        datetime.now(timezone.utc).timestamp() + INTERVAL_SECONDS
                    )

    def _get_model(self):
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    if not MODEL_PATH.is_file():
                        raise FileNotFoundError(f"Pothole model not found: {MODEL_PATH}")
                    from ultralytics import YOLO
                    self._model = YOLO(str(MODEL_PATH))
                    print(f"[PotholeWorker] Model loaded: {self._model.names}")
        return self._model

    def _run_scan(self):
        db = _SessionLocal()
        created = 0
        try:
            cameras = db.query(Camera).filter(
                Camera.pothole_enabled.is_(True),
                Camera.source_type == "video",
            ).order_by(Camera.id).all()
            camera_data = [(c.id, c.name, c.source) for c in cameras if c.source]

            with self._lock:
                self._status["cameras_total"] = len(camera_data)
                self._status["message"] = (
                    f"Inspecting {len(camera_data)} enabled video camera(s)"
                )

            model = self._get_model()

            for camera_id, camera_name, source in camera_data:
                if self._stop.is_set():
                    break

                video_path = Path(source)
                if not video_path.is_absolute():
                    video_path = ROOT / video_path

                cap = cv2.VideoCapture(str(video_path))
                detected_points = 0
                total_boxes = 0
                max_confidence = 0.0

                try:
                    if not cap.isOpened():
                        print(f"[PotholeWorker] Cannot open camera {camera_id} video: {video_path}")
                        continue

                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                    if total_frames <= 0:
                        continue

                    for fraction in SAMPLE_FRACTIONS:
                        cap.set(
                            cv2.CAP_PROP_POS_FRAMES,
                            min(int(total_frames * fraction), total_frames - 1),
                        )
                        ok, frame = cap.read()
                        if not ok:
                            continue

                        with self._model_lock:
                            result = model.predict(
                                frame,
                                conf=CONFIDENCE_THRESHOLD,
                                verbose=False,
                            )[0]

                        boxes = result.boxes
                        if boxes is not None and len(boxes) > 0:
                            detected_points += 1
                            total_boxes += len(boxes)
                            max_confidence = max(
                                max_confidence,
                                max(float(boxes.conf.max().item()), 0.0),
                            )
                finally:
                    cap.release()

                # Require detections at two of the three sampled video positions.
                if detected_points >= 2:
                    cutoff = datetime.now(timezone.utc) - timedelta(
                        seconds=INTERVAL_SECONDS
                    )
                    recent = db.query(PotholeEvent.id).filter(
                        PotholeEvent.camera_id == camera_id,
                        PotholeEvent.detected_at >= cutoff,
                    ).first()

                    if not recent:
                        event = PotholeEvent(
                            camera_id=camera_id,
                            camera_name=camera_name,
                            detection_type="pothole_detected",
                        )
                        db.add(event)
                        db.commit()
                        created += 1
                        status, detail = send_telegram_alert(
                            module="pothole",
                            camera_name=camera_name,
                            camera_id=camera_id,
                            detection_type="pothole_detected",
                            details=(
                                f"Sampled positions with detections: {detected_points}/3; "
                                f"maximum confidence: {max_confidence:.2f}"
                            ),
                        )
                        print(
                            f"[PotholeWorker] Telegram status={status}"
                            + (f"; detail={detail}" if detail else "")
                        )
                        print(
                            f"[PotholeWorker] Event created: camera={camera_id}, "
                            f"sampled_points={detected_points}/3, boxes={total_boxes}, "
                            f"max_confidence={max_confidence:.2f}"
                        )
                    else:
                        print(f"[PotholeWorker] Repeat event suppressed for camera {camera_id}")

                with self._lock:
                    self._status["cameras_done"] += 1
                    self._status["events_created"] = created
                    self._status["message"] = (
                        f"Inspected {self._status['cameras_done']} of "
                        f"{self._status['cameras_total']} camera(s)"
                    )

            finished = datetime.now(timezone.utc).isoformat()
            with self._lock:
                self._status.update({
                    "state": "idle",
                    "message": "Pothole inspection completed",
                    "finished_at": finished,
                    "last_scan_at": finished,
                    "events_created": created,
                })
            print(f"[PotholeWorker] Scan completed; events created: {created}")

        except Exception as exc:
            db.rollback()
            print(f"[PotholeWorker] Scan failed: {exc}")
            with self._lock:
                self._status.update({
                    "state": "error",
                    "message": str(exc),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "events_created": created,
                })
        finally:
            db.close()
            with self._lock:
                self._scan_running = False


pothole_worker = PotholeWorker()
