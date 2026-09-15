from ultralytics import YOLO
import cv2
from pathlib import Path

# --------------------------------------------------
# Find the UrbanVision project folder
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------
# File paths
# --------------------------------------------------

model_path = PROJECT_ROOT / "models" / "best.pt"
video_path = PROJECT_ROOT / "datasets" / "traffic_videos" / "traffic1.mp4"

print("Model:", model_path)
print("Video:", video_path)

# Check files before loading
if not model_path.exists():
    print("ERROR: best.pt not found!")
    exit()

if not video_path.exists():
    print("ERROR: traffic1.mp4 not found!")
    exit()

# --------------------------------------------------
# Load fine-tuned UrbanVision model
# --------------------------------------------------

model = YOLO(str(model_path))

# --------------------------------------------------
# Open CCTV video
# --------------------------------------------------

cap = cv2.VideoCapture(str(video_path))

if not cap.isOpened():
    print("ERROR: Could not open video.")
    exit()

# --------------------------------------------------
# Video information
# --------------------------------------------------

width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = cap.get(cv2.CAP_PROP_FPS)

print()
print("Video opened successfully!")
print("Resolution:", width, "x", height)
print("FPS:", fps)
print()

# --------------------------------------------------
# Process video
# --------------------------------------------------

while True:

    ret, frame = cap.read()

    if not ret:
        break

    # Run fine-tuned model
    results = model.predict(
        source=frame,
        conf=0.45,
        verbose=False
    )

    result = results[0]

    # Count vehicles in this frame
    vehicle_count = len(result.boxes)

    # Draw bounding boxes
    annotated_frame = result.plot()

    # Display vehicle count
    cv2.putText(
        annotated_frame,
        f"Vehicles: {vehicle_count}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 0),
        2
    )

    cv2.imshow(
        "UrbanVision - Fine-Tuned Vehicle Detection",
        annotated_frame
    )

    # Press Q to stop
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# --------------------------------------------------
# Cleanup
# --------------------------------------------------

cap.release()
cv2.destroyAllWindows()

print("Test completed.")