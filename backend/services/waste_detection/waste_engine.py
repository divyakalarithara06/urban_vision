"""
waste_engine.py - UrbanVision waste detection engine
=====================================================

One class, no GUI, no popups. Give it a video frame (a numpy BGR image, the
same thing OpenCV returns), and it gives back a plain Python dict that can be
sent as JSON to a backend / dashboard.

Usage
-----
    from waste_engine import WasteDetector

    detector = WasteDetector()                    # loads the two models once
    result = detector.process_frame(frame, camera_id="cam-12")

    if result["new_alerts"]:                      # fires ONCE per waste episode
        send_to_municipality(result)

How it works (details in README.md)
-----------------------------------
1. Road model   (models/best_8.pt)       -> Container, waste_spilled, waste_Overload
2. Pile model   (models/best_pile_v2.pt) -> class 1 = waste_pile
3. Confidence filter per waste type.
4. Persistence rule: a waste type must be present for `alert_after` frames in
   a row before it counts as an alert (stops one noisy frame raising an alarm).
5. An alert is "new" only on the frame it starts. It stays "active" until the
   waste disappears.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

# --------------------------------------------------------------------------
# Settings. Override any of them: WasteDetector({"alert_after": 15}).
# --------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "road_model": "models/waste_road_detector_v1.pt",        # Container / waste_spilled / waste_Overload
    "pile_model": "models/waste_pile_detector_v2.pt",  # class 1 = waste pile
    "imgsz": 640,                            # YOLO input size
    "road_floor_conf": 0.25,                 # lowest confidence the road model reports
    "road_iou": 0.4,                         # overlap limit for removing duplicate boxes
    "min_conf": {                            # extra, stricter bar per road class
        "waste_spilled": 0.30,
        "waste_Overload": 0.35,
    },
    "pile_class_id": 1,                      # which class of the pile model is "waste pile"
    "pile_conf": 0.35,                       # confidence bar for the pile model
    "frame_stride": 2,                       # run the models on every Nth frame
    "alert_after": 8,                        # frames in a row before an alert starts
    "miss_tolerance": 0,                     # missed frames allowed before the count resets
}

# The three things that can raise an alert. "Container" (a normal bin) never does.
WASTE_TYPES = ("waste_spilled", "waste_Overload", "waste_pile")


def _boxes(result) -> Iterator[Tuple[List[float], int, float]]:
    """Turn one YOLO result into (box, class_id, confidence) tuples."""
    b = result.boxes
    xyxy = b.xyxy.cpu().numpy()
    cls = b.cls.cpu().numpy()
    conf = b.conf.cpu().numpy()
    for i in range(len(cls)):
        yield [float(v) for v in xyxy[i]], int(cls[i]), float(conf[i])


def _det(kind: str, conf: float, box: List[float], source: str, is_waste: bool) -> Dict[str, Any]:
    return {
        "type": kind,
        "confidence": round(conf, 4),
        "bbox": [round(v, 1) for v in box],   # [x1, y1, x2, y2] in pixels
        "source": source,                      # "road" or "pile" model
        "is_waste": is_waste,                  # False for a normal bin
    }


class WasteDetector:
    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 road_model: Any = None, pile_model: Any = None):
        """
        config      : any settings to override (see DEFAULT_CONFIG)
        road_model / pile_model : optional ready-made model objects
                      (used by the tests; normally leave as None)
        """
        cfg = dict(config or {})
        min_conf = dict(DEFAULT_CONFIG["min_conf"])
        min_conf.update(cfg.pop("min_conf", {}))
        self.cfg: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.cfg.update(cfg)
        self.cfg["min_conf"] = min_conf

        if road_model is None or pile_model is None:
            from ultralytics import YOLO  # imported only when real models are needed
        self.road = road_model if road_model is not None else YOLO(self.cfg["road_model"])
        self.pile = pile_model if pile_model is not None else YOLO(self.cfg["pile_model"])

        self._cams: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    def _state(self, camera_id: str) -> Dict[str, Any]:
        st = self._cams.get(camera_id)
        if st is None:
            st = {
                "n": 0,                                   # frames seen
                "dets": [],                               # last detections
                "found": set(),                           # waste types in last detections
                "streak": {t: 0 for t in WASTE_TYPES},    # consecutive frames present
                "miss": {t: 0 for t in WASTE_TYPES},      # consecutive frames missing
                "active": set(),                          # alerts currently on
            }
            self._cams[camera_id] = st
        return st

    def reset(self, camera_id: Optional[str] = None) -> None:
        """Forget the counters of one camera (or all cameras)."""
        if camera_id is None:
            self._cams.clear()
        else:
            self._cams.pop(camera_id, None)

    # ------------------------------------------------------------------
    def detect(self, frame) -> List[Dict[str, Any]]:
        """Run both models on one frame. No memory between frames."""
        c = self.cfg
        dets: List[Dict[str, Any]] = []

        # 1) road model: bins, spilled waste, overflowing bins
        r = self.road.predict(frame, imgsz=c["imgsz"], conf=c["road_floor_conf"],
                              iou=c["road_iou"], agnostic_nms=True, verbose=False)[0]
        for box, cls, conf in _boxes(r):
            name = self.road.names[cls]
            if name == "Container":                       # a normal bin is not an alert
                dets.append(_det("Container", conf, box, "road", False))
                continue
            if conf < c["min_conf"].get(name, c["road_floor_conf"]):
                continue                                  # too weak, ignore
            dets.append(_det(name, conf, box, "road", True))

        # 2) pile model: heaps of waste (only the class we identified as "pile")
        p = self.pile.predict(frame, imgsz=c["imgsz"], conf=c["pile_conf"], verbose=False)[0]
        for box, cls, conf in _boxes(p):
            if cls != c["pile_class_id"]:
                continue
            dets.append(_det("waste_pile", conf, box, "pile", True))

        return dets

    # ------------------------------------------------------------------
    def process_frame(self, frame, camera_id: str = "cam0") -> Dict[str, Any]:
        """
        Call this once per frame, in order, for each camera.

        Returns a JSON-friendly dict:
          camera_id         which camera
          frame_index       0, 1, 2 ... for this camera
          timestamp         UTC time of the call
          detections        list of boxes (type, confidence, bbox, source, is_waste)
          detections_fresh  True if the models ran on this frame (False = reused boxes)
          waste_present     waste types seen in the latest detections
          alerts_active     waste types that have lasted >= alert_after frames
          new_alerts        waste types whose alert started on THIS frame
        """
        c = self.cfg
        st = self._state(camera_id)

        fresh = st["n"] % max(1, int(c["frame_stride"])) == 0
        if fresh:
            st["dets"] = self.detect(frame)
            st["found"] = {d["type"] for d in st["dets"] if d["is_waste"]}

        active: List[str] = []
        new_alerts: List[str] = []
        for t in WASTE_TYPES:
            if t in st["found"]:
                st["streak"][t] += 1
                st["miss"][t] = 0
            else:
                st["miss"][t] += 1
                if st["miss"][t] > c["miss_tolerance"]:
                    st["streak"][t] = 0

            if st["streak"][t] >= c["alert_after"]:
                active.append(t)
                if t not in st["active"]:
                    st["active"].add(t)
                    new_alerts.append(t)
            elif st["streak"][t] == 0:
                st["active"].discard(t)

        result = {
            "camera_id": camera_id,
            "frame_index": st["n"],
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "detections": st["dets"],
            "detections_fresh": fresh,
            "waste_present": sorted(st["found"]),
            "alerts_active": active,
            "new_alerts": new_alerts,
        }
        st["n"] += 1
        return result

