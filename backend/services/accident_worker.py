import logging
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import torch
from sqlalchemy.orm import Session
from torch import nn
from ultralytics import YOLO

from backend.database.connection import SessionLocal
from backend.database.models import Camera, AccidentEvent
from backend.services.telegram_notifier import send_telegram_alert

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = ROOT / "accident_detection" / "handover_original" / "urban_vision_handover"
GRU_PATH = MODULE_ROOT / "outputs" / "models" / "accident_gru.pt"
YOLO_PATH = ROOT / "models" / "fab.pt"

FEATURE_NAMES = [
    "vehicle_count", "mean_dx", "mean_dy", "mean_speed",
    "p90_speed", "mean_acceleration", "moving_vehicle_ratio",
]
SAMPLE_FPS = 5
WINDOW_STEP = 4


class AccidentGRU(nn.Module):
    def __init__(self, input_size=7, hidden_size=32):
        super().__init__()
        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
        )
        self.dropout = nn.Dropout(0.2)
        self.classifier = nn.Linear(hidden_size, 1)

    def forward(self, x):
        _, hidden = self.gru(x)
        return self.classifier(self.dropout(hidden[-1])).squeeze(1)


class AccidentWorker:
    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = {
            "state": "stopped",
            "monitored_cameras": 0,
            "last_error": None,
            "last_processed_at": None,
            "cameras": {},
        }
        self._device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        self._gru = None
        self._mean = None
        self._std = None
        self._threshold = 0.5
        self._sequence_length = 16
        self._states = {}

    def _load_models(self):
        if self._gru is not None:
            return
        if not GRU_PATH.is_file() or not YOLO_PATH.is_file():
            raise FileNotFoundError("Accident YOLO or GRU model is missing.")

        checkpoint = torch.load(
            GRU_PATH, map_location=self._device, weights_only=False
        )
        if int(checkpoint["input_size"]) != len(FEATURE_NAMES):
            raise ValueError("GRU input size does not match accident features.")

        self._sequence_length = int(checkpoint["sequence_length"])
        self._mean = np.asarray(checkpoint["feature_mean"], dtype=np.float32)
        self._std = np.asarray(checkpoint["feature_std"], dtype=np.float32)
        self._std[self._std < 1e-6] = 1.0
        self._threshold = float(checkpoint.get("threshold", 0.5))

        self._gru = AccidentGRU(
            input_size=int(checkpoint["input_size"]),
            hidden_size=int(checkpoint.get("hidden_size", 32)),
        ).to(self._device)
        self._gru.load_state_dict(checkpoint["model_state_dict"])
        self._gru.eval()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="accident-worker", daemon=True
        )
        self._thread.start()
        logger.info("Accident worker started.")

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        for state in self._states.values():
            cap = state.get("capture")
            if cap is not None:
                cap.release()
        self._states.clear()
        with self._lock:
            self._status["state"] = "stopped"
        logger.info("Accident worker stopped.")

    def status(self):
        with self._lock:
            return dict(self._status)

    @staticmethod
    def _camera_source(camera):
        source = camera.source
        if camera.source_type.lower() in {"camera", "webcam", "usb"}:
            try:
                return int(source)
            except (ValueError, TypeError):
                return source
        if camera.source_type.lower() in {"rtsp", "stream", "ip_camera"}:
            return source
        path = Path(source)
        if not path.is_absolute():
            path = ROOT / path
        return str(path)

    def _get_state(self, camera):
        state = self._states.get(camera.id)
        source = self._camera_source(camera)
        if state is not None and state["source"] == source:
            return state

        if state and state.get("capture"):
            state["capture"].release()

        state = {
            "source": source,
            "capture": cv2.VideoCapture(source),
            "source_type": camera.source_type.lower(),
            "model": YOLO(str(YOLO_PATH)),
            "samples": deque(maxlen=self._sequence_length),
            "positions": {},
            "speeds": {},
            "sample_number": 0,
            "window_number": 0,
            "frames_read": 0,
            "latest_probability": None,
            "last_error": None,
            "source_open": False,
            "last_sample_at": 0.0,
            "video_seconds": 0.0,
            "last_alert_at": -999999.0,
            "confirmation_streak": 0,
            "confirmation_start_seconds": None,
            "confirmed_event_active": False,
            "camera_name": camera.name,
        }
        cap = state["capture"]
        fps = cap.get(cv2.CAP_PROP_FPS) if cap.isOpened() else 0
        state["fps"] = fps if fps and np.isfinite(fps) and fps > 0 else 25.0
        state["frame_stride"] = max(1, round(state["fps"] / SAMPLE_FPS))
        self._states[camera.id] = state
        return state

    @staticmethod
    def _extract_frame_features(state, frame):
        result = state["model"].track(
            frame, persist=True, tracker="bytetrack.yaml",
            classes=[0], verbose=False,
        )[0]
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            state["positions"] = {}
            state["speeds"] = {}
            return [0.0] * 7

        if boxes.id is None:
            state["positions"] = {}
            state["speeds"] = {}
            return [float(len(boxes)), 0, 0, 0, 0, 0, 0]

        ids = boxes.id.cpu().numpy().astype(int)
        centers = boxes.xywh[:, :2].cpu().numpy()
        height, width = result.orig_shape
        diagonal = max(float(np.hypot(width, height)), 1.0)
        centers = centers / diagonal

        dxs, dys, speeds, accelerations = [], [], [], []
        positions, current_speeds = {}, {}
        moving = 0
        for track_id, center in zip(ids, centers):
            track_id = int(track_id)
            x, y = float(center[0]), float(center[1])
            dx = dy = speed = 0.0
            if track_id in state["positions"]:
                old_x, old_y = state["positions"][track_id]
                dx = (x - old_x) * SAMPLE_FPS
                dy = (y - old_y) * SAMPLE_FPS
                speed = float(np.hypot(dx, dy))
                if track_id in state["speeds"]:
                    accelerations.append(
                        abs(speed - state["speeds"][track_id]) * SAMPLE_FPS
                    )
            dxs.append(dx)
            dys.append(dy)
            speeds.append(speed)
            positions[track_id] = (x, y)
            current_speeds[track_id] = speed
            if speed > 0.005:
                moving += 1

        count = len(centers)
        state["positions"] = positions
        state["speeds"] = current_speeds
        return [
            float(count),
            float(np.median(dxs)) if dxs else 0.0,
            float(np.median(dys)) if dys else 0.0,
            float(np.median(speeds)) if speeds else 0.0,
            float(np.percentile(speeds, 90)) if speeds else 0.0,
            float(np.median(accelerations)) if accelerations else 0.0,
            float(moving / count) if count else 0.0,
        ]

    def _save_candidate(
        self, camera, state, probability, start_seconds, end_seconds,
        windows_in_event=3,
    ):
        trigger = round(end_seconds, 1)
        db: Session = SessionLocal()
        try:
            # Cooldown avoids repeated alerts for a sustained candidate.
            if end_seconds - state["last_alert_at"] < 30:
                return

            identity = f"camera-{camera.id}"
            exists = (
                db.query(AccidentEvent)
                .filter(
                    AccidentEvent.video_name == identity,
                    AccidentEvent.alert_trigger_seconds == trigger,
                )
                .first()
            )
            if exists:
                return

            event = AccidentEvent(
                camera_id=camera.id,
                camera_name=camera.name,
                source_type="live_camera",
                video_name=identity,
                detection_type="ACCIDENT_DETECTED",
                event_start_seconds=start_seconds,
                alert_trigger_seconds=trigger,
                event_end_seconds=end_seconds,
                peak_probability=round(probability, 4),
                windows_in_event=windows_in_event,
                experimental=True,
            )
            db.add(event)
            db.commit()
            status, detail = send_telegram_alert(
                module="accident",
                camera_name=camera.name,
                camera_id=camera.id,
                detection_type="ACCIDENT_DETECTED",
                details=(
                    f"Model probability: {probability:.3f}; "
                    f"confirmation windows: {windows_in_event}. "
                    "Experimental model alert; verify the incident."
                ),
            )
            logger.info(
                "Accident Telegram status=%s camera=%s%s",
                status,
                camera.name,
                f" detail={detail}" if detail else "",
            )
            state["last_alert_at"] = end_seconds
            logger.warning(
                "Experimental accident candidate: camera=%s probability=%.3f",
                camera.name, probability,
            )
        except Exception:
            db.rollback()
            logger.exception("Could not save accident event for camera %s", camera.name)
        finally:
            db.close()

    def _process_camera(self, camera):
        state = self._get_state(camera)
        cap = state["capture"]
        if not cap.isOpened():
            cap.release()
            state["capture"] = cv2.VideoCapture(state["source"])
            cap = state["capture"]
            if not cap.isOpened():
                state["source_open"] = False
                state["last_error"] = "Could not open camera source"
                return
        state["source_open"] = True
        state["last_error"] = None

        # Keep video sources looping for continuous testing; reconnect streams.
        for _ in range(state["frame_stride"]):
            ok, frame = cap.read()
            if ok:
                state["frames_read"] += 1
            if not ok:
                if state["source_type"] in {"video", "file"}:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    state["positions"] = {}
                    state["speeds"] = {}
                    ok, frame = cap.read()
                if not ok:
                    cap.release()
                    state["capture"] = cv2.VideoCapture(state["source"])
                    return

        features = self._extract_frame_features(state, frame)
        state["samples"].append(features)
        state["sample_number"] += 1
        state["video_seconds"] += 1.0 / SAMPLE_FPS

        if len(state["samples"]) < self._sequence_length:
            return
        if (state["sample_number"] - self._sequence_length) % WINDOW_STEP != 0:
            return

        normalized = (np.asarray(state["samples"], dtype=np.float32) - self._mean) / self._std
        sequence = torch.from_numpy(normalized).unsqueeze(0).to(self._device)
        with torch.no_grad():
            probability = float(torch.sigmoid(self._gru(sequence)).item())
        state["window_number"] += 1
        state["latest_probability"] = round(probability, 4)
        state["last_error"] = None

        # Match confirm_accident.py: require three consecutive windows
        # at or above the checkpoint threshold before recording an event.
        window_start = max(
            0.0,
            state["video_seconds"] - self._sequence_length / SAMPLE_FPS,
        )

        if probability >= self._threshold:
            if state["confirmation_streak"] == 0:
                state["confirmation_start_seconds"] = window_start

            state["confirmation_streak"] += 1

            if (
                state["confirmation_streak"] >= 3
                and not state["confirmed_event_active"]
            ):
                state["confirmed_event_active"] = True
                self._save_candidate(
                    camera,
                    state,
                    probability,
                    state["confirmation_start_seconds"],
                    state["video_seconds"],
                    windows_in_event=state["confirmation_streak"],
                )
                logger.warning(
                    "Accident confirmation rule met: camera=%s "
                    "probability=%.3f consecutive_windows=%s",
                    camera.name, probability, state["confirmation_streak"],
                )
        else:
            state["confirmation_streak"] = 0
            state["confirmation_start_seconds"] = None
            state["confirmed_event_active"] = False

    def _run(self):
        try:
            self._load_models()
            with self._lock:
                self._status["state"] = "running"
                self._status["last_error"] = None
        except Exception as exc:
            logger.exception("Accident worker could not load models.")
            with self._lock:
                self._status["state"] = "error"
                self._status["last_error"] = str(exc)
            return

        while not self._stop.is_set():
            db = SessionLocal()
            try:
                cameras = db.query(Camera).filter(Camera.accident_enabled.is_(True)).all()
                camera_data = [
                    (camera.id, camera.name, camera.source, camera.source_type)
                    for camera in cameras
                ]
            except Exception as exc:
                logger.exception("Accident worker could not read cameras.")
                with self._lock:
                    self._status["last_error"] = str(exc)
                camera_data = []
            finally:
                db.close()

            processed = 0
            for camera_id, name, source, source_type in camera_data:
                if self._stop.is_set():
                    break
                # Detached camera snapshot: the worker doesn't hold DB sessions
                # while running YOLO or GRU inference.
                camera = type("CameraSnapshot", (), {
                    "id": camera_id, "name": name,
                    "source": source, "source_type": source_type,
                })()
                try:
                    self._process_camera(camera)
                    processed += 1
                except Exception as exc:
                    logger.exception("Accident processing failed for camera %s", name)
                    if camera_id in self._states:
                        self._states[camera_id]["last_error"] = str(exc)[:200]
                    with self._lock:
                        self._status["last_error"] = f"Processing failed for {name}: {exc}"

            active_ids = {row[0] for row in camera_data}
            for camera_id in list(self._states):
                if camera_id not in active_ids:
                    cap = self._states.pop(camera_id).get("capture")
                    if cap:
                        cap.release()

            camera_telemetry = {}
            for camera_id, name, source, source_type in camera_data:
                state = self._states.get(camera_id, {})
                camera_telemetry[str(camera_id)] = {
                    "camera_id": camera_id,
                    "camera_name": name,
                    "source_type": source_type,
                    "source_open": state.get("source_open", False),
                    "frames_read": state.get("frames_read", 0),
                    "sampled_frames": state.get("sample_number", 0),
                    "windows_evaluated": state.get("window_number", 0),
                    "latest_probability": state.get("latest_probability"),
                    "threshold": self._threshold,
                    "last_error": state.get("last_error"),
                }

            with self._lock:
                self._status.update({
                    "cameras": camera_telemetry,
                    "monitored_cameras": len(camera_data),
                    "processed_cameras": processed,
                    "last_processed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "last_error": self._status.get("last_error"),
                })
            self._stop.wait(0.05)


accident_worker = AccidentWorker()
