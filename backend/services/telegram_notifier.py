import logging
import os
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)


def send_telegram_alert(
    module: str,
    camera_name: str,
    camera_id: int,
    detection_type: str,
    details: str = "",
) -> tuple[str, str | None]:
    """Send one alert. Return (status, detail); never raise delivery errors."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return "not_configured", "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"

    message = (
        f"UrbanVision {module.upper()} ALERT\n"
        f"Detection: {detection_type}\n"
        f"Camera: {camera_name} (ID {camera_id})\n"
        f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    if details:
        message += f"\nDetails: {details}"

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("ok"):
            logger.info("Telegram alert sent: module=%s camera_id=%s", module, camera_id)
            return "sent", None
        return "failed", str(payload)[:500]
    except Exception as exc:
        logger.warning(
            "Telegram alert failed: module=%s camera_id=%s error=%s",
            module, camera_id, exc,
        )
        return "failed", str(exc)[:500]
