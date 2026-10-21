from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

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
