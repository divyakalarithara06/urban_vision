CREATE TABLE IF NOT EXISTS accident_events (
    id SERIAL PRIMARY KEY,
    camera_id INTEGER NULL REFERENCES cameras(id) ON DELETE SET NULL,
    camera_name VARCHAR(100) NOT NULL DEFAULT 'Test video',
    source_type VARCHAR(30) NOT NULL DEFAULT 'test_video',
    video_name VARCHAR(255) NOT NULL,
    detection_type VARCHAR(100) NOT NULL DEFAULT 'possible_accident',
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_start_seconds DOUBLE PRECISION NULL,
    alert_trigger_seconds DOUBLE PRECISION NOT NULL,
    event_end_seconds DOUBLE PRECISION NULL,
    peak_probability DOUBLE PRECISION NULL,
    windows_in_event INTEGER NULL,
    experimental BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_accident_video_trigger
        UNIQUE (video_name, alert_trigger_seconds)
);

CREATE INDEX IF NOT EXISTS ix_accident_events_camera_id
    ON accident_events(camera_id);

CREATE INDEX IF NOT EXISTS ix_accident_events_detected_at
    ON accident_events(detected_at);
