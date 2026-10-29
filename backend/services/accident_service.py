import csv
import json
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = ROOT / "accident_detection" / "handover_original" / "urban_vision_handover"
PREDICT_SCRIPT = MODULE_ROOT / "src" / "predict_accident.py"
GRU_PATH = MODULE_ROOT / "outputs" / "models" / "accident_gru.pt"
YOLO_PATH = ROOT / "models" / "fab.pt"
VIDEO_DIR = MODULE_ROOT / "videos" / "test"
OUTPUT_DIR = MODULE_ROOT / "outputs" / "predictions"

_RUN_LOCK = threading.Lock()


def get_health():
    required = {
        "prediction_script": PREDICT_SCRIPT,
        "gru_model": GRU_PATH,
        "yolo_model": YOLO_PATH,
        "test_video_directory": VIDEO_DIR,
    }
    checks = {name: path.exists() for name, path in required.items()}
    videos = sorted(path.name for path in VIDEO_DIR.glob("*") if path.is_file() and path.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}) if VIDEO_DIR.is_dir() else []

    return {
        "status": "ready" if all(checks.values()) else "model_or_file_missing",
        "checks": checks,
        "available_test_videos": videos,
        "mode": "prerecorded_video_test",
        "warning": "Experimental alert candidates are not confirmation of a real accident.",
    }


def run_video_test(video_name: str):
    if not video_name or Path(video_name).name != video_name:
        raise HTTPException(status_code=400, detail="Provide a video filename, not a path.")

    video_path = VIDEO_DIR / video_name
    if video_path.suffix.lower() not in {".mp4", ".avi", ".mov", ".mkv"} or not video_path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"message": "Test video not found.", "available_test_videos": get_health()["available_test_videos"]},
        )

    if not all(path.is_file() for path in (PREDICT_SCRIPT, GRU_PATH, YOLO_PATH)):
        raise HTTPException(status_code=503, detail="Accident model or inference script is missing.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem
    summary_path = OUTPUT_DIR / f"{stem}_summary.json"
    predictions_path = OUTPUT_DIR / f"{stem}_predictions.csv"
    confirmation_path = OUTPUT_DIR / f"{stem}_confirmation.csv"
    alert_path = OUTPUT_DIR / f"{stem}_alert_summary.json"

    # The original script uses Path.cwd(). Run it from its module root
    # and use a temporary copy so the handover source stays untouched.
    source = PREDICT_SCRIPT.read_text(encoding="utf-8-sig")
    source = source.replace(
        'YOLO_PATH = ROOT / "models" / "fab.pt"',
        f'YOLO_PATH = Path({str(YOLO_PATH)!r})',
        1,
    )
    source = source.replace(
        'VIDEO_PATH = ROOT / "videos" / "test" / "accidenttest1.mp4"',
        f'VIDEO_PATH = Path({str(video_path)!r})',
        1,
    )

    if 'VIDEO_PATH = ROOT / "videos" / "test" / "accidenttest1.mp4"' in source:
        raise HTTPException(status_code=500, detail="Could not configure the temporary inference script.")

    temporary_script = PREDICT_SCRIPT.parent / f"_api_predict_{uuid.uuid4().hex}.py"

    with _RUN_LOCK:
        try:
            temporary_script.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(temporary_script)],
                cwd=str(MODULE_ROOT),
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="Accident inference exceeded the 10-minute timeout.") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Accident inference failed: {exc}") from exc
        finally:
            temporary_script.unlink(missing_ok=True)

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Accident inference failed.",
                "exit_code": result.returncode,
                "stderr": result.stderr[-5000:],
                "stdout": result.stdout[-2000:],
            },
        )

    required_outputs = (summary_path, predictions_path, alert_path)
    missing = [str(path.name) for path in required_outputs if not path.is_file()]
    if missing:
        raise HTTPException(
            status_code=500,
            detail={"message": "Inference completed but expected outputs are missing.", "missing": missing},
        )

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        alert_summary = json.loads(alert_path.read_text(encoding="utf-8"))
        with predictions_path.open("r", newline="", encoding="utf-8") as file:
            predictions = list(csv.DictReader(file))
        confirmation = []
        if confirmation_path.is_file():
            with confirmation_path.open("r", newline="", encoding="utf-8") as file:
                confirmation = list(csv.DictReader(file))
    except (OSError, json.JSONDecodeError, csv.Error) as exc:
        raise HTTPException(status_code=500, detail=f"Could not read accident results: {exc}") from exc

    return {
        "video": video_name,
        "status": alert_summary.get("status", "UNKNOWN"),
        "experimental": True,
        "summary": summary,
        "alert_summary": alert_summary,
        "predictions": predictions,
        "confirmation_windows": confirmation,
        "console_output": result.stdout[-6000:],
        "warning": "An alert candidate is experimental and must not be treated as a verified real-world accident.",
    }
