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

model_path = PROJECT_ROOT / "models" / "best_2000.pt"
video_path = PROJECT_ROOT / "datasets" / "traffic_videos" / "traffic3.mp4"

# --------------------------------------------------
# Settings
# --------------------------------------------------

CONFIDENCE = 0.60
INFERENCE_SIZE = 1280

# --------------------------------------------------
# Check files
# --------------------------------------------------

if not model_path.exists():
    print("ERROR: best_2000.pt not found!")
    exit()

if not video_path.exists():
    print("ERROR: traffic1.mp4 not found!")
    exit()

# --------------------------------------------------
# Load model
# --------------------------------------------------

model = YOLO(str(model_path))

# --------------------------------------------------
# Open video
# --------------------------------------------------

cap = cv2.VideoCapture(str(video_path))

if not cap.isOpened():
    print("ERROR: Could not open video.")
    exit()

width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = cap.get(cv2.CAP_PROP_FPS)

print()
print("Model:", model_path)
print("Video:", video_path)
print("Resolution:", width, "x", height)
print("FPS:", fps)
print("Confidence:", CONFIDENCE)
print("Inference size:", INFERENCE_SIZE)
print()
print("Press Q to stop.")

# --------------------------------------------------
# Process video
# --------------------------------------------------

while True:

    ret, frame = cap.read()

    if not ret:
        break

    results = model.predict(
        source=frame,
        conf=CONFIDENCE,
        imgsz=INFERENCE_SIZE,
        verbose=False
    )

    result = results[0]

    vehicle_count = len(result.boxes)

    annotated_frame = result.plot()

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
        "UrbanVision - 0.6 Confidence Test",
        annotated_frame
    )

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# --------------------------------------------------
# Cleanup
# --------------------------------------------------

cap.release()
cv2.destroyAllWindows()

print("Test completed.")