from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func

from backend.database.connection import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    location = Column(String(150), nullable=False, default="Unknown location")

    source_type = Column(String(20), nullable=False, default="video")
    source = Column(String(500), nullable=False)

    status = Column(String(20), nullable=False, default="offline")

    traffic_enabled = Column(Boolean, nullable=False, default=True)
    accident_enabled = Column(Boolean, nullable=False, default=True)
    pothole_enabled = Column(Boolean, nullable=False, default=True)
    waste_enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class WasteEvent(Base):
    __tablename__ = "waste_events"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    camera_name = Column(String(100), nullable=False)
    detection_type = Column(String(100), nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    telegram_status = Column(String(30), nullable=False, default="not_configured")
    telegram_detail = Column(Text, nullable=True)


class PotholeEvent(Base):
    __tablename__ = "pothole_events"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    camera_name = Column(String(100), nullable=False)
    detection_type = Column(String(100), nullable=False, default="pothole_detected")
    detected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)



class AccidentEvent(Base):
    __tablename__ = "accident_events"
    __table_args__ = (
        UniqueConstraint(
            "video_name",
            "alert_trigger_seconds",
            name="uq_accident_video_trigger",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(
        Integer,
        ForeignKey("cameras.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    camera_name = Column(String(100), nullable=False, default="Test video")
    source_type = Column(String(30), nullable=False, default="test_video")
    video_name = Column(String(255), nullable=False)
    detection_type = Column(
        String(100), nullable=False, default="possible_accident"
    )
    detected_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    event_start_seconds = Column(Float, nullable=True)
    alert_trigger_seconds = Column(Float, nullable=False)
    event_end_seconds = Column(Float, nullable=True)
    peak_probability = Column(Float, nullable=True)
    windows_in_event = Column(Integer, nullable=True)
    experimental = Column(Boolean, nullable=False, default=True)
