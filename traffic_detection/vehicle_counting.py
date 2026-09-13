from ultralytics import YOLO
import cv2

# Load YOLO model
model = YOLO("models/yolov8n.pt")

# Open video
cap = cv2.VideoCapture("datasets/traffic_videos/traffic1.mp4")

# Store counted vehicle IDs
counted_ids = set()

# Vehicle counters
car_count = 0
bus_count = 0
truck_count = 0
motorcycle_count = 0

while cap.isOpened():

    success, frame = cap.read()

    if not success:
        break

    # Run tracking
    results = model.track(
        frame,
        persist=True,
        tracker="bytetrack.yaml",
        verbose=False
    )

    for result in results:

        if result.boxes.id is None:
            continue

        boxes = result.boxes

        for box, track_id in zip(boxes, boxes.id):

            track_id = int(track_id)

            class_id = int(box.cls[0])
            class_name = model.names[class_id]

            # Count each vehicle only once
            if track_id not in counted_ids:

                counted_ids.add(track_id)

                if class_name == "car":
                    car_count += 1

                elif class_name == "bus":
                    bus_count += 1

                elif class_name == "truck":
                    truck_count += 1

                elif class_name == "motorcycle":
                    motorcycle_count += 1

# Release video
cap.release()

# Final results
total_vehicles = (
    car_count +
    bus_count +
    truck_count +
    motorcycle_count
)

print("\nVehicle Count Summary")
print("---------------------")
print("Cars:", car_count)
print("Buses:", bus_count)
print("Trucks:", truck_count)
print("Motorcycles:", motorcycle_count)
print("Total Vehicles:", total_vehicles)