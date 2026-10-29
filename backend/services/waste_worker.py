import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cv2
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Camera, WasteEvent
from backend.api.waste import get_detector, _detector_lock
from backend.services.telegram_notifier import send_telegram_alert

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("DATABASE_URL")
INTERVAL_SECONDS = 2 * 60 * 60
FRAMES_PER_SEGMENT = 24
SEGMENT_FRACTIONS = (0.15, 0.50, 0.85)

_engine = create_engine(DATABASE_URL) if DATABASE_URL else None
_SessionLocal = sessionmaker(bind=_engine) if _engine else None


class WasteWorker:
    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._scheduler_thread = None
        self._scan_thread = None
        self._scan_running = False
        self._scan_id = 0
        self._status = {
            "state": "idle",
            "message": "Waiting for the first waste scan",
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
        if _engine is not None:
            WasteEvent.__table__.create(bind=_engine, checkfirst=True)
        self._stop.clear()
        self._scheduler_thread = threading.Thread(
            target=self._schedule_loop, name="waste-scheduler", daemon=True
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
                return {"accepted": False, "message": "A waste scan is already running"}
            if _SessionLocal is None:
                return {"accepted": False, "message": "DATABASE_URL is not configured"}
            self._scan_running = True
            self._scan_id += 1
            scan_id = self._scan_id
            self._status.update({
                "state": "running",
                "message": "Scanning enabled waste cameras",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "cameras_total": 0,
                "cameras_done": 0,
                "events_created": 0,
            })
            self._scan_thread = threading.Thread(
                target=self._run_scan, args=(scan_id,),
                name="waste-scan", daemon=True
            )
            self._scan_thread.start()
            return {"accepted": True, "message": "Waste scan started", "scan_id": scan_id}

    def get_status(self):
        with self._lock:
            result = dict(self._status)
            result["scan_running"] = self._scan_running
            result["interval_seconds"] = INTERVAL_SECONDS
            return result

    def _schedule_loop(self):
        next_run = time.monotonic() + INTERVAL_SECONDS
        while not self._stop.wait(1):
            if time.monotonic() >= next_run:
                result = self.trigger_scan()
                next_run = time.monotonic() + INTERVAL_SECONDS
                with self._lock:
                    self._status["next_scan_at"] = datetime.now(
                        timezone.utc
                    ).timestamp() + INTERVAL_SECONDS
            if not self._status.get("next_scan_at"):
                with self._lock:
                    self._status["next_scan_at"] = (
                        datetime.now(timezone.utc).timestamp() + INTERVAL_SECONDS
                    )

    def _run_scan(self, scan_id):
        db = _SessionLocal()
        created = 0
        try:
            cameras = db.query(Camera).filter(
                Camera.waste_enabled.is_(True),
                Camera.source_type == "video",
            ).all()
            camera_data = [
                (c.id, c.name, c.source)
                for c in cameras
                if c.source
            ]
            with self._lock:
                self._status["cameras_total"] = len(camera_data)
                self._status["message"] = (
                    f"Scanning {len(camera_data)} enabled video camera(s)"
                )

            detector = get_detector()
            for camera_id, camera_name, source in camera_data:
                if self._stop.is_set():
                    break
                video_path = Path(source)
                if not video_path.is_absolute():
                    video_path = ROOT / video_path
                cap = cv2.VideoCapture(str(video_path))
                try:
                    if not cap.isOpened():
                        print(f"[WasteWorker] Cannot open video for camera {camera_id}: {video_path}")
                        continue

                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                    if total_frames <= 0:
                        continue

                    # Inspect short consecutive clips at representative positions.
                    # A unique engine key per clip prevents alert streaks leaking
                    # between scans or unrelated clips.
                    camera_event_types = set()
                    for segment_index, fraction in enumerate(SEGMENT_FRACTIONS):
                        start_frame = min(
                            int(total_frames * fraction),
                            max(0, total_frames - FRAMES_PER_SEGMENT - 1),
                        )
                        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                        engine_camera_key = (
                            f"{camera_id}-scan{scan_id}-segment{segment_index}"
                        )
                        for _ in range(FRAMES_PER_SEGMENT):
                            ok, frame = cap.read()
                            if not ok:
                                break
                            with _detector_lock:
                                result = detector.process_frame(
                                    frame, camera_id=engine_camera_key
                                )
                            # The detector may return an alert as a dictionary
                            # or as a plain string, depending on model output.
                            if not isinstance(result, dict):
                                print(
                                    f"[WasteWorker] Unexpected detector result type: "
                                    f"{type(result).__name__}"
                                )
                                continue

                            alerts = result.get("new_alerts", []) or []
                            if isinstance(alerts, (str, dict)):
                                alerts = [alerts]

                            for alert in alerts:
                                if isinstance(alert, dict):
                                    detection_type = (
                                        alert.get("detection_type")
                                        or alert.get("class_name")
                                        or alert.get("class")
                                        or alert.get("label")
                                        or "waste_detected"
                                    )
                                else:
                                    detection_type = str(alert).strip() or "waste_detected"

                                camera_event_types.add(str(detection_type))
                finally:
                    cap.release()

                # Suppress repeat alerts for the same camera and detection
                # within the two-hour deduplication window, including manual scans.
                for detection_type in sorted(camera_event_types):
                    cutoff = datetime.now(timezone.utc) - timedelta(
                        seconds=INTERVAL_SECONDS
                    )
                    recent_event = db.query(WasteEvent.id).filter(
                        WasteEvent.camera_id == camera_id,
                        WasteEvent.detection_type == detection_type,
                        WasteEvent.detected_at >= cutoff,
                    ).first()

                    if recent_event:
                        print(
                            f"[WasteWorker] Suppressed repeat alert: "
                            f"camera={camera_id}, detection={detection_type}"
                        )
                        continue

                    event = WasteEvent(
                        camera_id=camera_id,
                        camera_name=camera_name,
                        detection_type=detection_type,
                        telegram_status="not_configured",
                    )
                    db.add(event)
                    db.commit()
                    db.refresh(event)
                    created += 1
                    self._send_telegram(event, camera_id, camera_name, detection_type, db)

                with self._lock:
                    self._status["cameras_done"] += 1
                    self._status["events_created"] = created
                    self._status["message"] = (
                        f"Scanned {self._status['cameras_done']} of "
                        f"{self._status['cameras_total']} camera(s)"
                    )

            finished = datetime.now(timezone.utc).isoformat()
            with self._lock:
                self._status.update({
                    "state": "idle",
                    "message": "Waste scan completed",
                    "finished_at": finished,
                    "last_scan_at": finished,
                    "events_created": created,
                })
            print(f"[WasteWorker] Scan {scan_id} completed; events created: {created}")
        except Exception as exc:
            db.rollback()
            print(f"[WasteWorker] Scan {scan_id} failed: {exc}")
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

    @staticmethod
    def _send_telegram(event, camera_id, camera_name, detection_type, db):
        status, detail = send_telegram_alert(
            module="waste",
            camera_name=camera_name,
            camera_id=camera_id,
            detection_type=detection_type,
        )
        event.telegram_status = status
        event.telegram_detail = detail
        db.commit()



waste_worker = WasteWorker()
