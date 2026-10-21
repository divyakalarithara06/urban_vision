from ultralytics import YOLO
import cv2
import time


# ============================================================
# SETTINGS
# ============================================================

MODEL_PATH = "models/fab.pt"
VIDEO_PATH = "datasets/traffic_videos/traffic2.mp4"

CONFIDENCE = 0.45
INFERENCE_SIZE = 1280

TEST_FRAMES = 100


# ============================================================
# LOAD MODEL
# ============================================================

print("Loading model...")

model = YOLO(MODEL_PATH)

print("Model loaded.")


# ============================================================
# OPEN VIDEO
# ============================================================

cap = cv2.VideoCapture(VIDEO_PATH)

if not cap.isOpened():
    print("Could not open video.")
    exit()

print("Video opened.")


# ============================================================
# FPS TEST
# ============================================================

processed = 0

start_time = time.time()

while processed < TEST_FRAMES:

    success, frame = cap.read()

    if not success:
        break

    model.predict(
        frame,
        conf=CONFIDENCE,
        imgsz=INFERENCE_SIZE,
        verbose=False
    )

    processed += 1

    if processed % 10 == 0:
        print(
            f"Processed {processed}/{TEST_FRAMES} frames"
        )


end_time = time.time()

cap.release()


# ============================================================
# RESULTS
# ============================================================

elapsed = end_time - start_time

fps = processed / elapsed if elapsed > 0 else 0

print()
print("==============================")
print("YOLO PERFORMANCE TEST")
print("==============================")

print(f"Frames processed : {processed}")
print(f"Time taken       : {elapsed:.2f} seconds")
print(f"YOLO FPS         : {fps:.2f}")

print("==============================")

if fps >= 24:
    print("Excellent: can keep up with 24 FPS video.")

elif fps >= 12:
    print("Good: suitable for near-real-time traffic monitoring.")

elif fps >= 8:
    print("Usable: frame skipping will be needed.")

else:
    print("Slow: we should optimize inference.")