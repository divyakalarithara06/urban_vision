import csv
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
PREDICTION_DIR = ROOT / "outputs" / "predictions"

THRESHOLD = 0.5
REQUIRED_CONSECUTIVE_WINDOWS = 3


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        raise ValueError(
            "Usage: python src/confirm_accident.py <video_stem>"
        )

    video_stem = Path(sys.argv[1]).stem
    input_csv = PREDICTION_DIR / f"{video_stem}_predictions.csv"
    output_csv = PREDICTION_DIR / f"{video_stem}_confirmation.csv"
    output_json = PREDICTION_DIR / f"{video_stem}_alert_summary.json"

    if not input_csv.exists():
        raise FileNotFoundError(
            f"Prediction CSV not found: {input_csv}\n"
            "Run src/predict_accident.py first."
        )

    with input_csv.open("r", newline="", encoding="utf-8") as file:
        predictions = list(csv.DictReader(file))

    if not predictions:
        raise RuntimeError(f"No prediction windows found in {input_csv}")

    streak = 0
    streak_start_seconds = None
    active_event = None
    events = []
    next_event_number = 0

    for row in predictions:
        probability = float(row["accident_probability"])
        above_threshold = probability >= THRESHOLD

        if above_threshold:
            if streak == 0:
                streak_start_seconds = float(row["start_time_seconds"])
            streak += 1
        else:
            streak = 0
            streak_start_seconds = None
            active_event = None

        alert_candidate = streak >= REQUIRED_CONSECUTIVE_WINDOWS

        if alert_candidate:
            if active_event is None:
                next_event_number += 1
                active_event = f"{video_stem}_event_{next_event_number}"
                event = {
                    "event_id": active_event,
                    "event_start_seconds": streak_start_seconds,
                    "alert_trigger_seconds": float(row["start_time_seconds"]),
                    "event_end_seconds": float(row["end_time_seconds"]),
                    "peak_probability": probability,
                    "windows_in_event": streak,
                    "status": "ACCIDENT_DETECTED",
                }
                events.append(event)

                print("\n" + "=" * 55)
                print("ACCIDENT DETECTED - ALERT CANDIDATE")
                print("Event ID:", active_event)
                print(f"Event began at: {streak_start_seconds:.2f} seconds")
                print(
                    "Alert triggered at: "
                    f"{float(row['start_time_seconds']):.2f} seconds"
                )
                print(f"Probability at trigger: {probability:.1%}")
                print("=" * 55)
            else:
                event = next(
                    item for item in events if item["event_id"] == active_event
                )
                event["event_end_seconds"] = float(row["end_time_seconds"])
                event["peak_probability"] = max(
                    event["peak_probability"], probability
                )
                event["windows_in_event"] += 1

        row["above_threshold"] = str(above_threshold)
        row["confirmation_status"] = (
            "ACCIDENT_DETECTED"
            if alert_candidate
            else "WAITING_FOR_CONFIRMATION"
            if above_threshold
            else "NO_ALERT"
        )
        row["event_id"] = active_event if alert_candidate else ""

    columns = list(predictions[0].keys())
    with output_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(predictions)

    overall_status = "ACCIDENT_DETECTED" if events else "NO_ACCIDENT_DETECTED"
    summary = {
        "video": video_stem,
        "status": overall_status,
        "threshold": THRESHOLD,
        "required_consecutive_windows": REQUIRED_CONSECUTIVE_WINDOWS,
        "alert_candidate_count": len(events),
        "events": events,
        "warning": (
            "ACCIDENT_DETECTED means the model confirmation rule was met; "
            "it is not proof of a real collision. Validate before emergency use."
        ),
    }

    output_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n--- FINAL CONFIRMATION RESULT ---")
    print("Video:", video_stem)
    print("Status:", overall_status)
    print("Alert candidates:", len(events))
    print("\nConfirmation CSV:", output_csv)
    print("Alert summary JSON:", output_json)


if __name__ == "__main__":
    main()
