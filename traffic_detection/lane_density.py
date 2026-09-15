from ultralytics import YOLO
import cv2
import numpy as np
import json
import time


# ============================================================
# SETTINGS
# ============================================================

VIDEO_PATH = "datasets/traffic_videos/traffic1.mp4"
MODEL_PATH = "models/best.pt"
LANE_CONFIG_PATH = "traffic_detection/lane_config.json"

CONFIDENCE = 0.45

# Initial green signal
INITIAL_GREEN_TIME = 5

# Pause before evaluating traffic
EVALUATION_PAUSE = 2


# ============================================================
# LOAD LANE CONFIGURATION
# ============================================================

with open(LANE_CONFIG_PATH, "r") as f:
    lanes = json.load(f)


# Convert lane points to NumPy arrays
lane_polygons = {}

for lane_name, points in lanes.items():
    lane_polygons[lane_name] = np.array(points, dtype=np.int32)


# ============================================================
# LOAD MODEL
# ============================================================

model = YOLO(MODEL_PATH)

print("Model loaded:")
print(model.names)


# ============================================================
# OPEN VIDEO
# ============================================================

cap = cv2.VideoCapture(VIDEO_PATH)

if not cap.isOpened():
    print("Could not open video.")
    exit()

print("Video opened successfully.")


# ============================================================
# ANALYZE FRAME
# ============================================================

def analyze_frame(frame):

    results = model.predict(
        frame,
        conf=CONFIDENCE,
        verbose=False
    )

    lane_counts = {
        lane_name: 0
        for lane_name in lane_polygons
    }

    detections = []

    for result in results:

        if result.boxes is None:
            continue

        for box in result.boxes:

            cls = int(box.cls[0])

            # Our trained model has only one class:
            # 0 = vehicle
            if cls != 0:
                continue

            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()

            # Vehicle center
            center_x = int((x1 + x2) / 2)
            center_y = int((y1 + y2) / 2)

            detections.append(
                (x1, y1, x2, y2, center_x, center_y)
            )

            # Check which lane contains the vehicle center
            for lane_name, polygon in lane_polygons.items():

                inside = cv2.pointPolygonTest(
                    polygon,
                    (center_x, center_y),
                    False
                )

                if inside >= 0:
                    lane_counts[lane_name] += 1
                    break

    return lane_counts, detections


# ============================================================
# CALCULATE FIXED GREEN TIMES
# ============================================================

def calculate_green_times(lane_counts):

    total_vehicles = sum(lane_counts.values())

    percentages = {}
    green_times = {}

    for lane, count in lane_counts.items():

        if total_vehicles > 0:
            percentage = (count / total_vehicles) * 100
        else:
            percentage = 0

        percentages[lane] = percentage

        # ----------------------------------------------------
        # FIXED TIMING RULES
        # ----------------------------------------------------

        if percentage > 60:
            green_times[lane] = 8

        elif percentage > 40:
            green_times[lane] = 6

        elif percentage > 20:
            green_times[lane] = 4

        else:
            green_times[lane] = 2

    return total_vehicles, percentages, green_times


# ============================================================
# DRAW DISPLAY
# ============================================================

def draw_display(
    frame,
    lane_counts,
    percentages=None,
    green_times=None,
    green_lane=None,
    time_remaining=None,
    status=""
):

    display = frame.copy()

    # --------------------------------------------------------
    # Draw lane polygons
    # --------------------------------------------------------

    for lane_name, polygon in lane_polygons.items():

        # Highlight current green lane
        if lane_name == green_lane:
            polygon_color = (0, 255, 0)
            thickness = 4
        else:
            polygon_color = (255, 0, 0)
            thickness = 2

        cv2.polylines(
            display,
            [polygon],
            True,
            polygon_color,
            thickness
        )

        # Lane label position
        x, y = polygon[0]

        cv2.putText(
            display,
            lane_name,
            (x, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            polygon_color,
            2
        )

    # --------------------------------------------------------
    # Draw vehicle detections
    # --------------------------------------------------------

    results = model.predict(
        frame,
        conf=CONFIDENCE,
        verbose=False
    )

    for result in results:

        if result.boxes is None:
            continue

        for box in result.boxes:

            cls = int(box.cls[0])

            if cls != 0:
                continue

            x1, y1, x2, y2 = map(
                int,
                box.xyxy[0].cpu().numpy()
            )

            center_x = int((x1 + x2) / 2)
            center_y = int((y1 + y2) / 2)

            cv2.rectangle(
                display,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            cv2.circle(
                display,
                (center_x, center_y),
                4,
                (0, 0, 255),
                -1
            )

    # --------------------------------------------------------
    # Status text
    # --------------------------------------------------------

    cv2.putText(
        display,
        status,
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 255),
        2
    )

    # --------------------------------------------------------
    # Current green signal
    # --------------------------------------------------------

    if green_lane is not None:

        text = f"{green_lane} GREEN"

        if time_remaining is not None:
            text += f" | {time_remaining:.1f}s"

        cv2.putText(
            display,
            text,
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2
        )

    # --------------------------------------------------------
    # Lane information
    # --------------------------------------------------------

    y_position = 110

    for lane_name in lane_polygons:

        count = lane_counts.get(lane_name, 0)

        if percentages is not None:
            percentage = percentages.get(lane_name, 0)

            green_time = green_times.get(
                lane_name,
                0
            ) if green_times else 0

            text = (
                f"{lane_name}: "
                f"{count} vehicles | "
                f"{percentage:.1f}% | "
                f"{green_time:.1f}s"
            )

        else:

            text = (
                f"{lane_name}: "
                f"{count} vehicles"
            )

        cv2.putText(
            display,
            text,
            (20, y_position),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2
        )

        y_position += 30

    return display


# ============================================================
# READ FIRST FRAME
# ============================================================

success, frame = cap.read()

if not success:
    print("Could not read video.")
    cap.release()
    exit()


# ============================================================
# INITIAL GREEN
# ============================================================

print()
print("Initial green: Lane_1")
print(f"Initial green time: {INITIAL_GREEN_TIME} seconds")


initial_start = time.time()

while True:

    elapsed = time.time() - initial_start
    remaining = INITIAL_GREEN_TIME - elapsed

    if remaining <= 0:
        break

    # Analyze frame only for displaying detections
    lane_counts, _ = analyze_frame(frame)

    display = draw_display(
        frame,
        lane_counts,
        green_lane="Lane_1",
        time_remaining=remaining,
        status="INITIAL GREEN"
    )

    cv2.imshow(
        "UrbanVision Traffic Signal",
        display
    )

    key = cv2.waitKey(30) & 0xFF

    if key == ord("q"):
        cap.release()
        cv2.destroyAllWindows()
        exit()


# ============================================================
# MAIN TRAFFIC SIGNAL CYCLE
# ============================================================

while True:

    # --------------------------------------------------------
    # PAUSE VIDEO BEFORE EVALUATION
    # --------------------------------------------------------

    print()
    print("-----------------------------")
    print("VIDEO PAUSED")
    print("Waiting 2 seconds before evaluation...")
    print("-----------------------------")

    pause_start = time.time()

    while time.time() - pause_start < EVALUATION_PAUSE:

        # Keep showing the SAME frame
        lane_counts, _ = analyze_frame(frame)

        display = draw_display(
            frame,
            lane_counts,
            status="PAUSED - EVALUATING NEXT CYCLE"
        )

        cv2.imshow(
            "UrbanVision Traffic Signal",
            display
        )

        key = cv2.waitKey(30) & 0xFF

        if key == ord("q"):
            cap.release()
            cv2.destroyAllWindows()
            exit()


    # --------------------------------------------------------
    # ANALYZE TRAFFIC
    # --------------------------------------------------------

    print()
    print("-----------------------------")
    print("ANALYZING TRAFFIC")
    print("-----------------------------")

    lane_counts, _ = analyze_frame(frame)

    total_vehicles, percentages, green_times = calculate_green_times(
        lane_counts
    )

    print()
    print(f"Total vehicles: {total_vehicles}")

    for lane in lane_polygons:

        print(
            f"{lane}: "
            f"{lane_counts[lane]} vehicles | "
            f"{percentages[lane]:.1f}% | "
            f"{green_times[lane]:.1f}s"
        )


    # --------------------------------------------------------
    # SORT LANES BY TRAFFIC PERCENTAGE
    # --------------------------------------------------------

    signal_order = sorted(
        lane_polygons.keys(),
        key=lambda lane: percentages[lane],
        reverse=True
    )

    print()
    print("Signal order:")

    for lane in signal_order:

        print(
            f"{lane} -> "
            f"{green_times[lane]:.1f} seconds"
        )


    # --------------------------------------------------------
    # RUN EACH LANE
    # --------------------------------------------------------

    for lane in signal_order:

        green_time = green_times[lane]

        print()
        print(
            f"{lane} GREEN for "
            f"{green_time:.1f} seconds"
        )

        green_start = time.time()

        while True:

            elapsed = time.time() - green_start
            remaining = green_time - elapsed

            if remaining <= 0:
                break


            # ------------------------------------------------
            # READ NEXT VIDEO FRAME
            # ------------------------------------------------

            success, frame = cap.read()

            if not success:
                print()
                print("Video ended.")

                cap.release()
                cv2.destroyAllWindows()
                exit()


            # ------------------------------------------------
            # Analyze current frame for display
            # ------------------------------------------------

            current_counts, _ = analyze_frame(frame)


            # ------------------------------------------------
            # DISPLAY
            # ------------------------------------------------

            display = draw_display(
                frame,
                current_counts,
                percentages=percentages,
                green_times=green_times,
                green_lane=lane,
                time_remaining=remaining,
                status="ADAPTIVE TRAFFIC SIGNAL"
            )

            cv2.imshow(
                "UrbanVision Traffic Signal",
                display
            )

            key = cv2.waitKey(30) & 0xFF

            if key == ord("q"):

                cap.release()
                cv2.destroyAllWindows()
                exit()


# ============================================================
# CLEANUP
# ============================================================

cap.release()
cv2.destroyAllWindows()