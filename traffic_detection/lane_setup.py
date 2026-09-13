import cv2
import json

VIDEO_PATH = "datasets/traffic_videos/traffic1.mp4"

# -------------------------
# Load first frame
# -------------------------

cap = cv2.VideoCapture(VIDEO_PATH)

success, frame = cap.read()
print("Frame Shape:", frame.shape)
cap.release()

if not success:
    print("Could not read video.")
    exit()

# -------------------------
# Lane Storage
# -------------------------

lanes = {}
current_points = []
lane_number = 1

# -------------------------
# Mouse Click Function
# -------------------------

def mouse_callback(event, x, y, flags, param):

    global current_points

    if event == cv2.EVENT_LBUTTONDOWN:

        current_points.append([x, y])

        print(f"Point added: ({x}, {y})")

# -------------------------
# Window Setup
# -------------------------

cv2.namedWindow("Lane Setup")
cv2.setMouseCallback(
    "Lane Setup",
    mouse_callback
)

print("\nInstructions")
print("----------------------")
print("Left Click = Add Point")
print("N = Save Current Lane")
print("S = Save All Lanes")
print("Q = Quit")

# -------------------------
# Main Loop
# -------------------------

while True:

    display = frame.copy()

    # Draw current points

    for point in current_points:

        cv2.circle(
            display,
            tuple(point),
            5,
            (0, 255, 0),
            -1
        )

    # Draw completed lanes

    for lane_name, points in lanes.items():

        pts = points

        for i in range(len(pts)):

            cv2.line(
                display,
                tuple(pts[i]),
                tuple(pts[(i + 1) % len(pts)]),
                (255, 0, 0),
                2
            )

        cv2.putText(
            display,
            lane_name,
            tuple(pts[0]),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 0, 0),
            2
        )

    cv2.imshow(
        "Lane Setup",
        display
    )

    key = cv2.waitKey(1) & 0xFF

    # Save current lane

    if key == ord("n"):

        if len(current_points) >= 3:

            lane_name = f"Lane_{lane_number}"

            lanes[lane_name] = current_points.copy()

            print(
                f"Saved {lane_name}"
            )

            lane_number += 1

            current_points.clear()

        else:

            print(
                "Need at least 3 points."
            )

    # Save all lanes
    # Save all lanes

    elif key == ord("s"):

        print("\nLanes currently in memory:")
        print(lanes)

        with open(
            "traffic_detection/lane_config.json",
            "w"
        ) as f:

            json.dump(
                lanes,
                f,
                indent=4
            )

        print(
            "\nLane configuration saved."
        )

        break

    # Quit

    elif key == ord("q"):

        break

cv2.destroyAllWindows()