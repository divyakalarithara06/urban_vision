
import threading
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


# ============================================================
# PATHS AND DETECTION SETTINGS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODEL_PATH = PROJECT_ROOT / "models" / "fab.pt"
LANE_CONFIG_DIR = PROJECT_ROOT / "traffic_detection" / "lane_configs"

CONFIDENCE = 0.45
INFERENCE_SIZE = 1280


# ============================================================
# PROCESSOR
# ============================================================

class TrafficProcessingError(Exception):
    """Expected error while processing a traffic camera."""


class TrafficProcessor:
    def __init__(self):
        self.model = None
        self.captures = {}
        self.lock = threading.Lock()

    def _get_model(self):
        if self.model is None:
            if not MODEL_PATH.is_file():
                raise TrafficProcessingError(
                    f"Traffic model not found: {MODEL_PATH}"
                )

            self.model = YOLO(str(MODEL_PATH))

        return self.model

    def _get_lane_config(self, source_path):
        # Lane setup stores one JSON file per video filename.
        config_path = LANE_CONFIG_DIR / f"{source_path.stem}.json"

        if not config_path.is_file():
            raise TrafficProcessingError(
                "lane_configuration_required: "
                f"No saved lane configuration exists for "
                f"'{source_path.name}'. Configure its lanes first."
            )

        import json

        try:
            with config_path.open("r", encoding="utf-8") as file:
                lanes = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise TrafficProcessingError(
                f"Could not read lane configuration: {exc}"
            ) from exc

        if not isinstance(lanes, dict) or not lanes:
            raise TrafficProcessingError(
                f"Lane configuration is empty or invalid: {config_path}"
            )

        for lane_name, points in lanes.items():
            if (
                not isinstance(lane_name, str)
                or not isinstance(points, list)
                or len(points) < 3
            ):
                raise TrafficProcessingError(
                    f"Invalid polygon for lane {lane_name!r}."
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
                    raise TrafficProcessingError(
                        f"Invalid point in lane {lane_name!r}."
                    )

        return lanes, config_path

    def _get_capture(self, camera_id, source_path):
        source_key = str(source_path.resolve())
        cached = self.captures.get(camera_id)

        if cached is not None and cached[0] == source_key:
            return cached[1]

        # Release an old capture if this camera's source was changed.
        if cached is not None:
            cached[1].release()

        capture = cv2.VideoCapture(source_key)

        if not capture.isOpened():
            capture.release()
            raise TrafficProcessingError(
                f"Could not open video source: {source_path}"
            )

        self.captures[camera_id] = (source_key, capture)
        return capture

    def process_camera_frame(self, camera):
        if not camera.traffic_enabled:
            raise TrafficProcessingError(
                "Traffic detection is disabled for this camera."
            )

        if camera.source_type.lower() != "video":
            raise TrafficProcessingError(
                "This initial processor supports registered video files only."
            )

        source_path = Path(camera.source)

        if not source_path.is_absolute():
            source_path = PROJECT_ROOT / source_path

        source_path = source_path.resolve()

        if not source_path.is_file():
            raise TrafficProcessingError(
                f"Video file not found: {source_path}"
            )

        # Check the lane configuration before running inference.
        lanes, config_path = self._get_lane_config(source_path)

        with self.lock:
            capture = self._get_capture(camera.id, source_path)

            success, frame = capture.read()

            # Loop the video when it reaches the end.
            if not success:
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                success, frame = capture.read()

            if not success:
                capture.release()
                self.captures.pop(camera.id, None)
                raise TrafficProcessingError(
                    f"Could not read a frame from {source_path.name}."
                )

            height, width = frame.shape[:2]
            model = self._get_model()

            results = model.predict(
                source=frame,
                conf=CONFIDENCE,
                imgsz=INFERENCE_SIZE,
                verbose=False,
            )

            result = results[0]
            detections = []

            if result.boxes is not None:
                for box in result.boxes:
                    x1, y1, x2, y2 = (
                        int(round(value))
                        for value in box.xyxy[0].tolist()
                    )

                    detections.append({
                        "bbox": [
                            max(0, min(width, x1)),
                            max(0, min(height, y1)),
                            max(0, min(width, x2)),
                            max(0, min(height, y2)),
                        ],
                        "confidence": round(float(box.conf[0]), 4),
                    })

            lane_results = {}

            for lane_name, points in lanes.items():
                polygon = np.array(points, dtype=np.int32)

                # Prevent malformed/out-of-frame points from crashing OpenCV.
                polygon[:, 0] = np.clip(polygon[:, 0], 0, width - 1)
                polygon[:, 1] = np.clip(polygon[:, 1], 0, height - 1)

                lane_mask = np.zeros((height, width), dtype=np.uint8)
                cv2.fillPoly(lane_mask, [polygon], 1)

                lane_area = int(np.count_nonzero(lane_mask))

                if lane_area == 0:
                    raise TrafficProcessingError(
                        f"{lane_name} has no visible area in this video."
                    )

                occupied_mask = np.zeros(
                    (height, width),
                    dtype=np.uint8,
                )
                lane_vehicle_count = 0

                for detection in detections:
                    x1, y1, x2, y2 = detection["bbox"]

                    if x2 <= x1 or y2 <= y1:
                        continue

                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2

                    # Assign a vehicle to a lane when its center is inside it.
                    if cv2.pointPolygonTest(
                        polygon,
                        (float(center_x), float(center_y)),
                        False,
                    ) < 0:
                        continue

                    lane_vehicle_count += 1

                    # Estimate visible image occupancy using the union of
                    # detected bounding boxes clipped to the lane polygon.
                    box_mask = np.zeros(
                        (height, width),
                        dtype=np.uint8,
                    )
                    box_mask[y1:y2, x1:x2] = 1
                    occupied_mask |= box_mask

                occupied_pixels = int(
                    np.count_nonzero(occupied_mask & lane_mask)
                )

                occupancy_percent = round(
                    min(100.0, occupied_pixels / lane_area * 100.0),
                    2,
                )

                lane_results[lane_name] = {
                    "vehicle_count": lane_vehicle_count,
                    "occupancy_percent": occupancy_percent,
                    "lane_area_pixels": lane_area,
                }

            return {
                "camera_id": camera.id,
                "camera_name": camera.name,
                "source": str(source_path),
                "model": MODEL_PATH.name,
                "confidence_threshold": CONFIDENCE,
                "inference_size": INFERENCE_SIZE,
                "frame_width": width,
                "frame_height": height,
                "detections": detections,
                "frame_timestamp_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "total_detected_vehicles": len(detections),
                "lane_configuration": str(config_path),
                "lanes": lane_results,
                "status": "processed",
            }


traffic_processor = TrafficProcessor()
