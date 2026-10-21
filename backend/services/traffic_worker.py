
import logging
import threading
import time
from datetime import datetime, timezone

from backend.database.connection import SessionLocal
from backend.database.models import Camera
from backend.services.traffic_processing import (
    TrafficProcessingError,
    traffic_processor,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
INITIAL_GREEN_TIME = 5


class TrafficWorker:
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest_results = {}
        self._running = False

        # Independent, persistent signal schedule for each camera.
        self._signal_schedules = {}

    @property
    def is_running(self):
        with self._lock:
            return self._running

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._stop_event.clear()
            self._running = True
            self._thread = threading.Thread(
                target=self._run,
                name="urbanvision-traffic-worker",
                daemon=True,
            )
            self._thread.start()

        logger.info("Traffic background worker started.")

    def stop(self):
        self._stop_event.set()

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=30)

        with self._lock:
            if thread is None or not thread.is_alive():
                self._running = False
                self._thread = None

        logger.info("Traffic background worker stop requested.")

    def get_latest_results(self, camera_id=None):
        with self._lock:
            if camera_id is not None:
                result = self._latest_results.get(camera_id)
                return result.copy() if result is not None else None

            return {
                key: value.copy()
                for key, value in self._latest_results.items()
            }

    def _store_result(self, camera_id, result):
        with self._lock:
            self._latest_results[camera_id] = result

    @staticmethod
    def _calculate_green_times(lanes):
        """Use the recovered vehicle-share thresholds."""
        total_vehicles = sum(
            max(0, int(data.get("vehicle_count", 0)))
            for data in lanes.values()
        )

        percentages = {}
        green_times = {}

        for lane_name, data in lanes.items():
            count = max(0, int(data.get("vehicle_count", 0)))

            percentage = (
                count / total_vehicles * 100.0
                if total_vehicles > 0
                else 0.0
            )

            percentages[lane_name] = round(percentage, 2)

            if percentage > 60:
                green_times[lane_name] = 8
            elif percentage > 40:
                green_times[lane_name] = 6
            elif percentage > 20:
                green_times[lane_name] = 4
            else:
                green_times[lane_name] = 2

        return total_vehicles, percentages, green_times

    def _update_signal_schedule(self, camera_id, lanes, now):
        """
        Advance the persistent schedule without blocking video processing.

        The first phase is Lane_1 for five seconds when Lane_1 exists.
        Subsequent phases follow the recovered vehicle-share priority.
        """
        if not lanes:
            self._signal_schedules.pop(camera_id, None)
            return {
                "active_green_lane": None,
                "time_remaining": 0,
                "total_detected_vehicles": 0,
                "signal_order": [],
            }

        total, percentages, green_times = (
            self._calculate_green_times(lanes)
        )

        schedule = self._signal_schedules.get(camera_id)

        if schedule is None:
            lane_names = list(lanes.keys())
            initial_lane = next(
                (
                    name for name in lane_names
                    if name.lower() == "lane_1"
                    or name.lower() == "lane 1"
                ),
                lane_names[0],
            )

            schedule = {
                "phase": "initial",
                "active_lane": initial_lane,
                "phase_started_at": now,
                "phase_duration": INITIAL_GREEN_TIME,
                "signal_order": [],
                "order_index": 0,
            }
            self._signal_schedules[camera_id] = schedule

        # Re-evaluate the lane order at the end of each active phase.
        while True:
            elapsed = now - schedule["phase_started_at"]
            remaining = schedule["phase_duration"] - elapsed

            if remaining > 0:
                break

            if schedule["phase"] == "initial":
                schedule["phase"] = "adaptive"
                schedule["signal_order"] = sorted(
                    lanes.keys(),
                    key=lambda name: percentages.get(name, 0),
                    reverse=True,
                )
                schedule["order_index"] = 0

            else:
                schedule["order_index"] += 1

                if schedule["order_index"] >= len(
                    schedule["signal_order"]
                ):
                    schedule["signal_order"] = sorted(
                        lanes.keys(),
                        key=lambda name: percentages.get(name, 0),
                        reverse=True,
                    )
                    schedule["order_index"] = 0

            order = schedule["signal_order"]
            if not order:
                break

            index = schedule["order_index"]
            next_lane = order[index]

            schedule["active_lane"] = next_lane
            schedule["phase_started_at"] = (
                schedule["phase_started_at"]
                + schedule["phase_duration"]
            )
            schedule["phase_duration"] = green_times.get(
                next_lane, 2
            )

            # Prevent an excessive catch-up loop if processing was paused.
            if now - schedule["phase_started_at"] > 120:
                schedule["phase_started_at"] = now

        remaining = max(
            0.0,
            schedule["phase_duration"]
            - (now - schedule["phase_started_at"]),
        )

        active_lane = schedule["active_lane"]

        for lane_name, data in lanes.items():
            data["vehicle_count_percent"] = percentages.get(
                lane_name, 0.0
            )
            data["green_time"] = green_times.get(lane_name, 2)
            data["signal_status"] = (
                "GREEN" if lane_name == active_lane else "RED"
            )
            data["time_remaining"] = (
                round(remaining, 1)
                if lane_name == active_lane
                else 0
            )

        return {
            "active_green_lane": active_lane,
            "time_remaining": round(remaining, 1),
            "total_detected_vehicles": total,
            "signal_order": schedule["signal_order"][:],
        }

    def _run(self):
        cycle_number = 0

        try:
            while not self._stop_event.is_set():
                cycle_number += 1
                cycle_started = time.perf_counter()

                try:
                    self._process_enabled_cameras()
                except Exception:
                    logger.exception(
                        "Unexpected error in traffic worker cycle %s.",
                        cycle_number,
                    )

                cycle_elapsed = time.perf_counter() - cycle_started

                logger.info(
                    "Traffic worker cycle %s completed in %.2f seconds.",
                    cycle_number,
                    cycle_elapsed,
                )

                wait_seconds = max(
                    0.0,
                    POLL_INTERVAL_SECONDS - cycle_elapsed,
                )
                self._stop_event.wait(wait_seconds)
        finally:
            with self._lock:
                self._running = False
            logger.info("Traffic background worker stopped.")

    def _process_enabled_cameras(self):
        db = SessionLocal()

        try:
            cameras = (
                db.query(Camera)
                .filter(Camera.traffic_enabled.is_(True))
                .order_by(Camera.id)
                .all()
            )

            camera_records = [
                {
                    "id": camera.id,
                    "name": camera.name,
                    "source": camera.source,
                    "source_type": camera.source_type,
                    "traffic_enabled": camera.traffic_enabled,
                }
                for camera in cameras
            ]
        finally:
            db.close()

        enabled_ids = {record["id"] for record in camera_records}

        # Remove schedules for cameras that are no longer enabled.
        for camera_id in list(self._signal_schedules):
            if camera_id not in enabled_ids:
                self._signal_schedules.pop(camera_id, None)

        logger.info(
            "Traffic worker found %s enabled camera(s).",
            len(camera_records),
        )

        for record in camera_records:
            if self._stop_event.is_set():
                break

            camera_id = record["id"]
            camera_started = time.perf_counter()
            camera_snapshot = type("CameraSnapshot", (), record)()

            try:
                result = traffic_processor.process_camera_frame(
                    camera_snapshot
                )

                lanes = result.get("lanes", {})
                signal_info = self._update_signal_schedule(
                    camera_id,
                    lanes,
                    time.monotonic(),
                )

                result["signal"] = signal_info
                result["signal_mode"] = "adaptive_simulation"
                result["worker_updated_at_utc"] = (
                    datetime.now(timezone.utc).isoformat()
                )

                self._store_result(camera_id, result)

                logger.info(
                    "Camera %s (%s) processed in %.2f seconds; "
                    "green_lane=%s; status=%s.",
                    camera_id,
                    record["name"],
                    time.perf_counter() - camera_started,
                    signal_info.get("active_green_lane"),
                    result.get("status", "processed"),
                )

            except TrafficProcessingError as exc:
                self._store_result(
                    camera_id,
                    {
                        "camera_id": camera_id,
                        "camera_name": record["name"],
                        "status": "error",
                        "error": str(exc),
                        "worker_updated_at_utc": (
                            datetime.now(timezone.utc).isoformat()
                        ),
                    },
                )

                logger.warning(
                    "Camera %s (%s) failed after %.2f seconds: %s",
                    camera_id,
                    record["name"],
                    time.perf_counter() - camera_started,
                    exc,
                )

            except Exception as exc:
                logger.exception(
                    "Unexpected processing error for camera %s.",
                    camera_id,
                )
                self._store_result(
                    camera_id,
                    {
                        "camera_id": camera_id,
                        "camera_name": record["name"],
                        "status": "error",
                        "error": f"Unexpected processing error: {exc}",
                        "worker_updated_at_utc": (
                            datetime.now(timezone.utc).isoformat()
                        ),
                    },
                )

                logger.warning(
                    "Camera %s (%s) failed after %.2f seconds.",
                    camera_id,
                    record["name"],
                    time.perf_counter() - camera_started,
                )


traffic_worker = TrafficWorker()
