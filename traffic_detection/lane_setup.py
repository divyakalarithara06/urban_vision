
import argparse
import json
import re
from pathlib import Path

import cv2
import numpy as np


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "traffic_detection" / "lane_configs"
LEGACY_CONFIG_PATH = PROJECT_ROOT / "traffic_detection" / "lane_config.json"

WINDOW_NAME = "Lane Setup"


# ============================================================
# SELECT VIDEO
# ============================================================

parser = argparse.ArgumentParser(description="Configure lanes for a video.")
parser.add_argument(
    "--video",
    default="datasets/traffic_videos/traffic1.mp4",
    help="Video path, relative to the project root or absolute.",
)
args = parser.parse_args()

video_path = Path(args.video)

if not video_path.is_absolute():
    video_path = PROJECT_ROOT / video_path

video_path = video_path.resolve()

if not video_path.is_file():
    raise SystemExit(f"Video file not found: {video_path}")

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Each video gets its own configuration.
config_path = CONFIG_DIR / f"{video_path.stem}.json"


# ============================================================
# LOAD OR MIGRATE EXISTING CONFIGURATION
# ============================================================

if not config_path.exists():
    # Preserve and migrate the existing traffic1 lane setup.
    if (
        video_path.stem == "traffic1"
        and LEGACY_CONFIG_PATH.is_file()
    ):
        try:
            with LEGACY_CONFIG_PATH.open("r", encoding="utf-8") as file:
                legacy_lanes = json.load(file)

            if isinstance(legacy_lanes, dict):
                with config_path.open("w", encoding="utf-8") as file:
                    json.dump(legacy_lanes, file, indent=4)

                print(
                    "Migrated the existing traffic1 lane configuration."
                )
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(
                f"Could not migrate the existing lane configuration: {exc}"
            )

if config_path.exists():
    try:
        with config_path.open("r", encoding="utf-8") as file:
            lanes = json.load(file)

        if not isinstance(lanes, dict):
            raise ValueError("Expected a JSON object containing lane polygons.")

        for lane_name, points in lanes.items():
            if (
                not isinstance(lane_name, str)
                or not isinstance(points, list)
                or len(points) < 3
                or any(
                    not isinstance(point, list)
                    or len(point) != 2
                    or any(
                        not isinstance(value, (int, float))
                        for value in point
                    )
                    for point in points
                )
            ):
                raise ValueError(f"Invalid polygon for {lane_name!r}.")

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(
            f"Cannot load lane configuration {config_path}: {exc}"
        )
else:
    lanes = {}
    print("No saved lane configuration exists for this video.")
    print("Configure the lanes and save them to create one.")

# Continue numbering after existing lanes.
lane_numbers = [
    int(match.group(1))
    for name in lanes
    if (match := re.fullmatch(r"Lane_(\d+)", name))
]
lane_number = max(lane_numbers, default=0) + 1


# ============================================================
# OPEN VIDEO AND READ FIRST FRAME
# ============================================================

cap = cv2.VideoCapture(str(video_path))

if not cap.isOpened():
    raise SystemExit(f"Could not open video: {video_path}")

success, frame = cap.read()
cap.release()

if not success:
    raise SystemExit(f"Could not read a frame from: {video_path}")

print("\nVideo:", video_path)
print("Resolution:", frame.shape[1], "x", frame.shape[0])
print("Configuration:", config_path)
print("Existing lanes:", len(lanes))
print("")


# ============================================================
# LANE DRAWING
# ============================================================

current_points = []


def mouse_callback(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        current_points.append([x, y])
        print(f"Point added: ({x}, {y})")


cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
cv2.resizeWindow(WINDOW_NAME, 1024, 576)
cv2.setMouseCallback(WINDOW_NAME, mouse_callback)

print("===================================")
print("LANE SETUP")
print("===================================")
print("Click points to draw a lane polygon.")
print("Press N = save the current lane")
print("Press S = save all lanes to this video's JSON")
print("Press Q = quit without saving")
print("===================================")


# ============================================================
# DISPLAY AND CONTROLS
# ============================================================

while True:
    display = frame.copy()

    # Draw previously saved lanes.
    for saved_lane, points in lanes.items():
        polygon = np.array(points, dtype=np.int32)

        cv2.polylines(
            display,
            [polygon],
            True,
            (255, 0, 0),
            2,
        )

        x, y = points[0]
        cv2.putText(
            display,
            saved_lane,
            (x, max(y - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 0, 0),
            2,
        )

    # Draw points for the lane currently being created.
    for point in current_points:
        cv2.circle(
            display,
            tuple(point),
            5,
            (0, 0, 255),
            -1,
        )

    if len(current_points) >= 2:
        polygon = np.array(current_points, dtype=np.int32)
        cv2.polylines(
            display,
            [polygon],
            False,
            (0, 255, 255),
            2,
        )

    cv2.imshow(WINDOW_NAME, display)
    key = cv2.waitKey(1) & 0xFF

    if key == ord("n"):
        if len(current_points) >= 3:
            lane_name = f"Lane_{lane_number}"
            lanes[lane_name] = current_points.copy()

            print(f"{lane_name} added: {current_points}")

            current_points.clear()
            lane_number += 1
        else:
            print("A lane needs at least 3 points.")

    elif key == ord("s"):
        if not lanes:
            print("No lanes to save. Draw at least one lane first.")
            continue

        try:
            with config_path.open("w", encoding="utf-8") as file:
                json.dump(lanes, file, indent=4)

            print(f"Saved {len(lanes)} lanes to:")
            print(config_path)
        except OSError as exc:
            print(f"Could not save lane configuration: {exc}")
            continue

        break

    elif key == ord("q"):
        print("Exited without saving.")
        break


# ============================================================
# CLEANUP
# ============================================================

cv2.destroyAllWindows()
