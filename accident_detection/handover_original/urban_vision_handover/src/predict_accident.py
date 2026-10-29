
import csv
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn
from ultralytics import YOLO


# ---------------- CONFIGURATION ----------------

ROOT = Path.cwd()

YOLO_PATH = ROOT / "models" / "fab.pt"
GRU_PATH = ROOT / "outputs" / "models" / "accident_gru.pt"

VIDEO_PATH = ROOT / "videos" / "test" / "accidenttest1.mp4"
OUTPUT_DIR = ROOT / "outputs" / "predictions"

SAMPLE_FPS = 5
WINDOW_STEP = 4
DEFAULT_THRESHOLD = 0.5

FEATURE_NAMES = [
    "vehicle_count",
    "mean_dx",
    "mean_dy",
    "mean_speed",
    "p90_speed",
    "mean_acceleration",
    "moving_vehicle_ratio",
]


# ---------------- GRU MODEL ----------------

class AccidentGRU(nn.Module):
    def __init__(self, input_size=7, hidden_size=32):
        super().__init__()

        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
        )

        self.dropout = nn.Dropout(0.2)
        self.classifier = nn.Linear(hidden_size, 1)

    def forward(self, x):
        _, hidden = self.gru(x)
        return self.classifier(
            self.dropout(hidden[-1])
        ).squeeze(1)


# ---------------- FEATURE EXTRACTION ----------------

def extract_features(video_path, yolo):
    """
    Extract the same robust, resolution-independent features used for training.
    """
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    if not fps or not np.isfinite(fps) or fps <= 0:
        raise RuntimeError(f"Cannot read valid FPS: {video_path}")

    stride = max(1, round(fps / SAMPLE_FPS))
    effective_fps = fps / stride

    times = []
    rows = []
    previous_positions = {}
    previous_speeds = {}
    frames_without_ids = 0
    total_sampled_frames = 0

    results = yolo.track(
        source=str(video_path),
        stream=True,
        persist=False,
        tracker="bytetrack.yaml",
        classes=[0],
        vid_stride=stride,
        verbose=False,
    )

    for sample_index, result in enumerate(results):
        total_sampled_frames += 1
        frame_time = sample_index * stride / fps
        boxes = result.boxes

        if boxes is None or len(boxes) == 0:
            times.append(frame_time)
            rows.append([0.0] * len(FEATURE_NAMES))
            previous_positions = {}
            previous_speeds = {}
            continue

        centers = boxes.xywh[:, :2].cpu().numpy()

        # Do not invent motion from detection order when tracker IDs are absent.
        if boxes.id is not None:
            ids = boxes.id.cpu().numpy().astype(int)
        else:
            ids = np.array([], dtype=int)
            frames_without_ids += 1

        frame_height, frame_width = result.orig_shape
        diagonal = max(float(np.hypot(frame_width, frame_height)), 1.0)
        centers = centers / diagonal

        dx_values = []
        dy_values = []
        speeds = []
        accelerations = []
        current_positions = {}
        current_speeds = {}
        moving_count = 0

        for track_id, center in zip(ids, centers):
            track_id = int(track_id)
            x, y = float(center[0]), float(center[1])
            dx = 0.0
            dy = 0.0
            speed = 0.0

            if track_id in previous_positions:
                old_x, old_y = previous_positions[track_id]
                dx = (x - old_x) * effective_fps
                dy = (y - old_y) * effective_fps
                speed = float(np.hypot(dx, dy))

                if track_id in previous_speeds:
                    accelerations.append(
                        abs(speed - previous_speeds[track_id]) * effective_fps
                    )

            dx_values.append(dx)
            dy_values.append(dy)
            speeds.append(speed)
            current_positions[track_id] = (x, y)
            current_speeds[track_id] = speed

            if speed > 0.005:
                moving_count += 1

        vehicle_count = len(centers)
        frame_features = [
            float(vehicle_count),
            float(np.median(dx_values)) if dx_values else 0.0,
            float(np.median(dy_values)) if dy_values else 0.0,
            float(np.median(speeds)) if speeds else 0.0,
            float(np.percentile(speeds, 90)) if speeds else 0.0,
            float(np.median(accelerations)) if accelerations else 0.0,
            float(moving_count / vehicle_count) if vehicle_count else 0.0,
        ]

        times.append(frame_time)
        rows.append(frame_features)
        previous_positions = current_positions
        previous_speeds = current_speeds

    features = np.asarray(rows, dtype=np.float32)
    times = np.asarray(times, dtype=np.float32)

    if len(features) == 0:
        raise RuntimeError("No frames could be processed.")

    tracking_info = {
        "sampled_frames": total_sampled_frames,
        "frames_without_tracker_ids": frames_without_ids,
        "effective_sampling_fps": round(effective_fps, 3),
    }

    return times, features, tracking_info


# ---------------- FEATURE DIAGNOSTICS ----------------

def print_feature_diagnostics(features, normalized, checkpoint):
    print("\n" + "=" * 65)
    print("FEATURE DIAGNOSTICS")
    print("=" * 65)

    checkpoint_names = checkpoint.get("feature_names")

    print("Feature names in code:", FEATURE_NAMES)
    print("Feature names in checkpoint:", checkpoint_names)

    if checkpoint_names is not None and list(checkpoint_names) != FEATURE_NAMES:
        raise ValueError(
            "Feature order mismatch between the code and checkpoint. "
            "Prediction stopped to prevent an invalid result."
        )

    print("\nRaw feature statistics for this video:")

    for i, name in enumerate(FEATURE_NAMES):
        print(
            f"{name:24s} "
            f"mean={features[:, i].mean():10.3f} "
            f"std={features[:, i].std():10.3f} "
            f"min={features[:, i].min():10.3f} "
            f"max={features[:, i].max():10.3f}"
        )

    print("\nNormalized feature range (training mean/std):")

    for i, name in enumerate(FEATURE_NAMES):
        z_min = float(normalized[:, i].min())
        z_max = float(normalized[:, i].max())

        print(
            f"{name:24s} "
            f"min={z_min:9.2f} "
            f"max={z_max:9.2f}"
        )

        if max(abs(z_min), abs(z_max)) > 5:
            print(
                "  WARNING: Values are far from the training mean "
                "in at least part of this video."
            )

    print(
        "\nNote: large normalized values can indicate a difference "
        "from training data, but do not prove the cause of false "
        "positives."
    )
    print("=" * 65 + "\n")


# ---------------- MAIN PREDICTION ----------------

def main():
    for path in (YOLO_PATH, GRU_PATH, VIDEO_PATH):
        if not path.exists():
            raise FileNotFoundError(
                f"Required file not found: {path}"
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )
    print("Inference device:", device)
    print("Video:", VIDEO_PATH.name)

    # Load the existing trained checkpoint.
    checkpoint = torch.load(
        GRU_PATH,
        map_location=device,
        weights_only=False,
    )

    sequence_length = int(checkpoint["sequence_length"])

    mean = np.asarray(
        checkpoint["feature_mean"], dtype=np.float32
    )
    std = np.asarray(
        checkpoint["feature_std"], dtype=np.float32
    )

    if len(mean) != len(FEATURE_NAMES) or len(std) != len(FEATURE_NAMES):
        raise ValueError(
            "Checkpoint normalization parameters do not match "
            "the seven expected features."
        )

    # Protect against division by zero.
    std[std < 1e-6] = 1.0

    threshold = float(
        checkpoint.get("threshold", DEFAULT_THRESHOLD)
    )

    gru = AccidentGRU(
        input_size=int(checkpoint["input_size"]),
        hidden_size=int(checkpoint["hidden_size"]),
    ).to(device)

    gru.load_state_dict(checkpoint["model_state_dict"])
    gru.eval()

    yolo = YOLO(str(YOLO_PATH))

    print("\nExtracting vehicle movement features...")
    times, features, tracking_info = extract_features(
        VIDEO_PATH, yolo
    )

    # Apply the normalization learned during training.
    normalized = (features - mean) / std

    # Print diagnostic information before inference.
    print_feature_diagnostics(
        features, normalized, checkpoint
    )

    # ---------------- SEQUENCE PREDICTIONS ----------------

    predictions = []

    if len(normalized) < sequence_length:
        print(
            f"Video has {len(normalized)} sampled frames, but "
            f"{sequence_length} are required for one prediction."
        )

    for start in range(
        0,
        len(normalized) - sequence_length + 1,
        WINDOW_STEP,
    ):
        end = start + sequence_length

        sequence = torch.from_numpy(
            normalized[start:end]
        ).unsqueeze(0).to(device)

        with torch.no_grad():
            logit = gru(sequence)
            probability = torch.sigmoid(logit).item()

        predictions.append({
            "start_frame_index": start,
            "end_frame_index": end - 1,
            "start_time_seconds": round(
                float(times[start]), 2
            ),
            "end_time_seconds": round(
                float(times[end - 1]), 2
            ),
            "accident_probability": round(
                probability, 4
            ),
            "prediction": (
                "POSSIBLE ACCIDENT"
                if probability >= threshold
                else "NO ACCIDENT FLAG"
            ),
        })

    # Use the input filename so different videos do not overwrite
    # one another's results.
    video_stem = VIDEO_PATH.stem

    csv_path = OUTPUT_DIR / f"{video_stem}_predictions.csv"
    summary_path = OUTPUT_DIR / f"{video_stem}_summary.json"

    columns = [
        "start_frame_index",
        "end_frame_index",
        "start_time_seconds",
        "end_time_seconds",
        "accident_probability",
        "prediction",
    ]

    with csv_path.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=columns
        )
        writer.writeheader()
        writer.writerows(predictions)

    possible_count = sum(
        p["accident_probability"] >= threshold
        for p in predictions
    )

    summary = {
        "video": str(VIDEO_PATH),
        "sampled_frames": len(features),
        "sequence_length": sequence_length,
        "window_step": WINDOW_STEP,
        "threshold": threshold,
        "windows_evaluated": len(predictions),
        "possible_accident_windows": possible_count,
        "tracking": tracking_info,
        "predictions_csv": str(csv_path),
        "warning": (
            "Experimental predictions only. A high probability "
            "does not confirm an accident. Not validated for "
            "real-world or emergency use."
        ),
    }

    summary_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    # ---------------- RESULTS ----------------

    print("\n--- PREDICTION SUMMARY ---")
    print(json.dumps(summary, indent=2))

    if predictions:
        print("\nWindow predictions:")

        for item in predictions:
            print(
                f"{item['start_time_seconds']:7.2f}s - "
                f"{item['end_time_seconds']:7.2f}s | "
                f"{item['accident_probability']:.1%} | "
                f"{item['prediction']}"
            )

        print(
            f"\nPossible-accident windows: "
            f"{possible_count}/{len(predictions)}"
        )

    print("\nSaved prediction CSV:", csv_path)
    print("Saved summary JSON:", summary_path)
    print("\nFinished.")


    # ---------------- AUTOMATIC CONFIRMATION ----------------
    # Use this video's filename to load its matching prediction CSV.
    confirmation_script = ROOT / "src" / "confirm_accident.py"

    if not confirmation_script.exists():
        raise FileNotFoundError(
            f"Confirmation script not found: {confirmation_script}"
        )

    print("\nStarting accident confirmation...")
    subprocess.run(
        [
            sys.executable,
            str(confirmation_script),
            VIDEO_PATH.stem,
        ],
        check=True,
        cwd=str(ROOT),
    )


if __name__ == "__main__":
    main()
