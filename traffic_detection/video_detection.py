from ultralytics import YOLO

# Load model
model = YOLO("models/yolov8n.pt")

# Run detection on video
results = model.predict(
    source="datasets/traffic_videos/traffic1.mp4",
    save=True,
    conf=0.4

)

print("Video processing complete!")