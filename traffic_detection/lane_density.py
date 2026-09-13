from ultralytics import YOLO
import cv2
import numpy as np
import json
import time

# -------------------------
# Load lane configuration
# -------------------------
with open("traffic_detection/lane_config.json", "r") as f:
    LANES = json.load(f)

# -------------------------
# Load YOLO model
# -------------------------
model = YOLO("models/yolov8n.pt")

# -------------------------
# Open video
# -------------------------
cap = cv2.VideoCapture(
    "datasets/traffic_videos/traffic1.mp4"
)

if not cap.isOpened():
    print("Could not open video.")
    exit()

FPS = int(cap.get(cv2.CAP_PROP_FPS))

if FPS == 0:
    FPS = 30

ANALYSIS_SECONDS = 3
FRAMES_TO_ANALYZE = FPS * ANALYSIS_SECONDS

# -------------------------
# Density function
# -------------------------
def get_density(count):

    if count <= 3:
        return "Low"

    elif count <= 8:
        return "Medium"

    else:
        return "High"


# -------------------------
# Analyze collected frames
# -------------------------
def analyze_frames(frames):

    lane_totals = {
        lane: 0
        for lane in LANES
    }

    for frame in frames:

        frame_counts = {
            lane: 0
            for lane in LANES
        }

        results = model(
            frame,
            verbose=False
        )

        for result in results:

            if result.boxes is None:
                continue

            for box in result.boxes:

                class_id = int(box.cls[0])
                class_name = model.names[class_id]

                if class_name not in [
                    "car",
                    "truck",
                    "bus",
                    "motorcycle"
                ]:
                    continue

                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[0]
                )

                center_x = (x1 + x2) // 2
                center_y = (y1 + y2) // 2

                for lane, polygon_points in LANES.items():

                    polygon = np.array(
                        polygon_points,
                        dtype=np.int32
                    )

                    inside = cv2.pointPolygonTest(
                        polygon,
                        (center_x, center_y),
                        False
                    )

                    if inside >= 0:
                        frame_counts[lane] += 1
                        break

        for lane in LANES:
            lane_totals[lane] += frame_counts[lane]

    lane_counts = {}

    for lane in LANES:

        lane_counts[lane] = round(
            lane_totals[lane] / len(frames)
        )

    return lane_counts


# -------------------------
# Initial signal state
# -------------------------
current_green = "Lane_1"
green_time = 20

signal_start_time = time.time()

analysis_frames = []
analysis_done = False

print("\nInitial Green:", current_green)

# -------------------------
# Main loop
# -------------------------
while cap.isOpened():

    success, frame = cap.read()

    if not success:
        print("\nVideo ended.")
        break

    elapsed = time.time() - signal_start_time
    remaining = green_time - elapsed

    # -----------------------------------
    # Collect last 3 seconds of frames
    # before signal change
    # -----------------------------------
    if remaining <= ANALYSIS_SECONDS:

        if len(analysis_frames) < FRAMES_TO_ANALYZE:
            analysis_frames.append(frame)

    # -----------------------------------
    # Time to change signal
    # -----------------------------------
    if elapsed >= green_time and not analysis_done:

        if len(analysis_frames) > 0:

            print("\n======================")
            print("Current Green:", current_green)

            lane_counts = analyze_frames(
                analysis_frames
            )

            print("\nLane Counts")
            print("-------------------")

            for lane, count in lane_counts.items():
                print(f"{lane}: {count}")

            print("\nLane Densities")
            print("-------------------")

            for lane, count in lane_counts.items():

                print(
                    f"{lane}: "
                    f"{get_density(count)}"
                )

            candidate_lanes = {

                lane: count

                for lane, count
                in lane_counts.items()

                if lane != current_green
            }

            next_green = max(
                candidate_lanes,
                key=candidate_lanes.get
            )

            density = get_density(
                lane_counts[next_green]
            )

            if density == "Low":
                green_time = 20

            elif density == "Medium":
                green_time = 40

            else:
                green_time = 60

            print("\nSignal Decision")
            print("-------------------")
            print("Current Green:",
                  current_green)

            print("Next Green:",
                  next_green)

            print("Green Time:",
                  green_time,
                  "seconds")

            current_green = next_green

        signal_start_time = time.time()
        analysis_frames = []
        analysis_done = False

    # -------------------------
    # Draw information
    # -------------------------
    cv2.putText(
        frame,
        f"GREEN: {current_green}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 0),
        2
    )

    cv2.putText(
        frame,
        f"Time Left: {int(max(0, remaining))}s",
        (20, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 255),
        2
    )

    # Draw lane polygons

    for lane, points in LANES.items():

        polygon = np.array(
            points,
            np.int32
        )

        cv2.polylines(
            frame,
            [polygon],
            True,
            (255, 0, 0),
            2
        )

    cv2.imshow(
        "UrbanVision Smart Traffic Control",
        frame
    )

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        fps = 30
    delay = int(1000 / fps)
    if cv2.waitKey(delay) & 0xFF == ord('q'):
        break

# -------------------------
# Cleanup
# -------------------------
cap.release()
cv2.destroyAllWindows()

print("\nSimulation finished.")