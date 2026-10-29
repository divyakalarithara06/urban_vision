
import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import "./App.css";
import LaneOverlay from "./pages/Traffic/LaneOverlay.jsx";
import LaneEditor from "./pages/Traffic/LaneEditor.jsx";

const API = "http://127.0.0.1:8000";
const POLL_INTERVAL = 3000;

const NAV_ITEMS = [
  { id: "overview", icon: "", label: "Overview" },
  { id: "cameras", icon: "", label: "Live cameras" },
  { id: "analytics", icon: "", label: "Traffic analytics" },
  { id: "waste", icon: "", label: "Waste detection" },
  { id: "accidents", icon: "", label: "Accident detection" },
  { id: "potholes", icon: "", label: "Pothole detection" },
  { id: "events", icon: "", label: "Events & alerts" },
  { id: "settings", icon: "", label: "Settings" },
];

function getList(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.value)) return payload.value;
  if (Array.isArray(payload?.cameras)) return payload.cameras;
  if (Array.isArray(payload?.results)) return payload.results;
  return [];
}

function getCameraId(camera) {
  return Number(camera?.id ?? camera?.camera_id);
}

function getCameraName(camera) {
  return camera?.location || camera?.name || `Camera ${getCameraId(camera)}`;
}

function getResultsForCamera(payload, cameraId) {
  if (Array.isArray(payload)) {
    return (
      payload.find(
        (item) =>
          Number(item?.camera_id ?? item?.cameraId ?? item?.id) ===
          Number(cameraId)
      ) || null
    );
  }

  if (!payload || typeof payload !== "object") return null;

  if (
    Number(payload.camera_id ?? payload.cameraId ?? payload.id) ===
    Number(cameraId)
  ) {
    return payload;
  }

  // Handle API format: results["1"], results["3"], etc.
  const keyedResult = payload.results?.[String(cameraId)];
  if (keyedResult && typeof keyedResult === "object") {
    return keyedResult;
  }

  const keyedValue = payload.value?.[String(cameraId)];
  if (keyedValue && typeof keyedValue === "object") {
    return keyedValue;
  }

  if (payload.results && typeof payload.results === "object") {
    return getResultsForCamera(payload.results, cameraId);
  }

  if (payload.value && typeof payload.value === "object") {
    return getResultsForCamera(payload.value, cameraId);
  }

  return null;
}

function getVehicleCount(result) {
  if (!result) return null;

  const keys = [
    "vehicle_count",
    "vehicles_count",
    "vehicleCount",
    "vehicles",
    "detection_count",
    "detections",
    "count",
    "total_detected_vehicles",
  ];

  for (const key of keys) {
    const value = result[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;

    if (Array.isArray(value)) return value.length;
  }

  return null;
}

function getLaneEntries(result) {
  if (!result) return [];

  const lanes =
    result.lanes ??
    result.lane_occupancy ??
    result.lane_density ??
    result.lane_densities ??
    result.occupancy;

  if (Array.isArray(lanes)) {
    return lanes.map((lane, index) => ({
      ...(lane && typeof lane === "object" ? lane : {}),
      name:
        lane?.lane_name ||
        lane?.name ||
        lane?.lane ||
        `Lane ${index + 1}`,
      value:
        typeof lane === "number"
          ? lane
          : lane?.occupancy_percent ??
            lane?.occupancy_percentage ??
            lane?.density_percent ??
            lane?.density ??
            lane?.occupancy ??
            lane?.percentage ??
            lane?.value ??
            0,
    }));
  }

  if (lanes && typeof lanes === "object") {
    return Object.entries(lanes).map(([name, value]) => ({
      ...(value && typeof value === "object" ? value : {}),
      name: name.toLowerCase().includes("lane")
        ? name
        : `Lane ${name}`,
      value:
        typeof value === "number"
          ? value
          : value?.occupancy_percent ??
            value?.occupancy_percentage ??
            value?.density_percent ??
            value?.density ??
            value?.occupancy ??
            value?.percentage ??
            value?.value ??
            0,
    }));
  }

  return [];
}

function getWorkerRunning(worker) {
  if (typeof worker === "boolean") return worker;
  if (!worker || typeof worker !== "object") return null;

  const candidates = [
    worker.running,
    worker.is_running,
    worker.worker_running,
    worker.active,
  ];

  const value = candidates.find((item) => typeof item === "boolean");
  return value ?? null;
}

function getWorkerForCamera(payload, cameraId) {
  if (!payload || typeof payload !== "object") return null;

  if (Array.isArray(payload)) {
    return (
      payload.find(
        (item) =>
          Number(item?.camera_id ?? item?.cameraId ?? item?.id) === cameraId
      ) || null
    );
  }

  const cameraWorkers =
    payload.cameras ??
    payload.workers ??
    payload.camera_status ??
    payload.status_by_camera;

  if (Array.isArray(cameraWorkers)) {
    return getWorkerForCamera(cameraWorkers, cameraId);
  }

  if (cameraWorkers && typeof cameraWorkers === "object") {
    return cameraWorkers[cameraId] ?? null;
  }

  if (payload[cameraId] && typeof payload[cameraId] === "object") {
    return payload[cameraId];
  }

  if (
    Number(payload.camera_id ?? payload.cameraId ?? payload.id) === cameraId
  ) {
    return payload;
  }

  return null;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "*";
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString() : "*";
}

function clampPercentage(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;

  // Accommodate occupancy fractions such as 0.75 as well as 75%.
  const percentage = number >= 0 && number <= 1 ? number * 100 : number;
  return Math.max(0, Math.min(100, percentage));
}

function StatusPill({ active, children }) {
  return (
    <span className={`status-pill ${active ? "status-pill--active" : ""}`}>
      <span className="status-dot" />
      {children}
    </span>
  );
}

function MetricCard({ label, value, caption, icon }) {
  return (
    <article className="metric-card">
      <div className="metric-card__top">
        <span className="metric-card__label">{label}</span>

      </div>
      <div className="metric-card__value">{value}</div>
      <div className="metric-card__caption">{caption}</div>
    </article>
  );
}


function WasteEventHistory() {
  const [events, setEvents] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(null);
  const [monitoring, setMonitoring] = useState(false);
  const [actionMessage, setActionMessage] = useState("");

  useEffect(() => {
    let active = true;

    const refresh = async () => {
      try {
        const [eventsResponse, statusResponse] = await Promise.all([
          fetch(`${API}/waste/events`),
          fetch(`${API}/waste/status`),
        ]);

        if (!eventsResponse.ok) {
          throw new Error(`Events API returned HTTP ${eventsResponse.status}`);
        }
        if (!statusResponse.ok) {
          throw new Error(`Waste status API returned HTTP ${statusResponse.status}`);
        }

        const [eventsData, statusData] = await Promise.all([
          eventsResponse.json(),
          statusResponse.json(),
        ]);

        if (active) {
          setEvents(
            Array.isArray(eventsData)
              ? eventsData
              : Array.isArray(eventsData?.value)
                ? eventsData.value
                : Array.isArray(eventsData?.results)
                  ? eventsData.results
                  : []
          );
          setStatus(statusData);
          setError("");
        }
      } catch (err) {
        if (active) setError(err.message || "Could not load waste monitoring status.");
      } finally {
        if (active) setLoading(false);
      }
    };

    refresh();
    const timer = setInterval(refresh, 3000);

    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  const startMonitoring = async () => {
    setMonitoring(true);
    setActionMessage("");
    try {
      const response = await fetch(`${API}/waste/monitor`, { method: "POST" });
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data.detail || data.message || `Request failed (HTTP ${response.status})`);
      }

      setActionMessage(data.message || "Waste scan started.");
      setStatus((previous) => ({
        ...previous,
        state: "running",
        scan_running: true,
      }));
    } catch (err) {
      setActionMessage(err.message || "Could not start the waste scan.");
    } finally {
      setMonitoring(false);
    }
  };

  const scanRunning = Boolean(status?.scan_running || status?.state === "running");

  return (
    <section style={{ marginBottom: 24 }}>
      <div className="section-heading">
        <div>
          <h2>Events &amp; alerts</h2>
          <p>Detection events and alerts from across UrbanVision modules.</p>
        </div>
        <span className="result-count">{events.length} events</span>
      </div>

      <section
        className="waste-monitoring-panel"
        style={{ marginBottom: 24, padding: 20 }}
      >
        <div className="section-heading">
          <div>
            <h2>Waste monitoring</h2>
            <p>Scheduled checks every 2 hours, independently of 24/7 traffic monitoring.</p>
          </div>
          <span className="result-count">
            {scanRunning ? "Scan running" : status?.state === "error" ? "Scan error" : "Standby"}
          </span>
        </div>

        <p>
          {status?.message || "Waiting for monitoring status..."}
          {status?.cameras_total > 0
            ? ` (${status.cameras_done || 0}/${status.cameras_total} cameras)`
            : ""}
        </p>

        {scanRunning && status?.cameras_total > 0 && (
          <div
            style={{
              height: 7,
              background: "var(--border-color, #e5e7eb)",
              borderRadius: 8,
              overflow: "hidden",
              margin: "12px 0",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${Math.min(100, ((status.cameras_done || 0) / status.cameras_total) * 100)}%`,
                background: "var(--accent-color, #16a34a)",
                transition: "width 0.3s ease",
              }}
            />
          </div>
        )}

        <p style={{ fontSize: 13 }}>
          Next scheduled scan:{" "}
          {status?.next_scan_at
            ? new Date(status.next_scan_at).toLocaleString()
            : "Not scheduled yet"}
        </p>
        <p style={{ fontSize: 13 }}>
          Last completed scan:{" "}
          {status?.last_scan_at
            ? new Date(status.last_scan_at).toLocaleString()
            : "No completed scan yet"}
        </p>

        <button
          type="button"
          onClick={startMonitoring}
          disabled={scanRunning || monitoring}
          style={{
            marginTop: 8,
            padding: "10px 18px",
            border: 0,
            borderRadius: 8,
            fontWeight: 600,
            cursor: scanRunning || monitoring ? "not-allowed" : "pointer",
            opacity: scanRunning || monitoring ? 0.6 : 1,
          }}
        >
          {monitoring ? "Starting..." : scanRunning ? "Waste scan running..." : "Monitor now"}
        </button>

        {actionMessage && <p role="status" style={{ marginTop: 10 }}>{actionMessage}</p>}
        {status?.state === "error" && (
          <p role="alert" style={{ marginTop: 8 }}>
            Latest scan error: {status.message}
          </p>
        )}
      </section>

      {error && (
        <div className="notice-card">
          <strong>Waste monitoring status unavailable</strong>
          <p>{error}. Confirm the backend has restarted with the latest changes.</p>
        </div>
      )}

      {loading ? (
        <div className="empty-state">Loading event history...</div>
      ) : events.length === 0 ? (
        <div className="empty-state">
          <h3>No waste events recorded</h3>
          <p>No new sustained waste alerts have been recorded yet.</p>
        </div>
      ) : (
        <section className="event-list">
          {events.map((event) => (
            <article className="event-row" key={event.id}>
              <div className="event-row__icon">!</div>
              <div className="event-row__content">
                <strong>{event.camera_name || `Camera ${event.camera_id}`}</strong>
                <p>{event.detection_type || "Waste detected"}</p>
                <p>
                  {event.detected_at
                    ? new Date(event.detected_at).toLocaleString()
                    : "Timestamp unavailable"}
                </p>
              </div>
              <div className="event-row__right">
                <span className="event-row__count">
                  Telegram: {String(event.telegram_status || "unknown").replaceAll("_", " ")}
                </span>
              </div>
            </article>
          ))}
        </section>
      )}
    </section>
  );
}


function PotholeEventHistory() {
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [eventsResponse, statusResponse] = await Promise.all([
        fetch(`${API}/potholes/events`),
        fetch(`${API}/potholes/status`),
      ]);
      if (!eventsResponse.ok) throw new Error(`Pothole events API: HTTP ${eventsResponse.status}`);
      if (!statusResponse.ok) throw new Error(`Pothole status API: HTTP ${statusResponse.status}`);
      const [eventData, statusData] = await Promise.all([
        eventsResponse.json(),
        statusResponse.json(),
      ]);
      setEvents(Array.isArray(eventData) ? eventData : []);
      setStatus(statusData);
      setError("");
    } catch (err) {
      setError(err.message || "Could not load pothole status.");
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [refresh]);

  const inspectNow = async () => {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/potholes/monitor`, { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Request failed (HTTP ${response.status})`);
      setMessage(data.message || "Pothole inspection started.");
      await refresh();
    } catch (err) {
      setMessage(err.message || "Could not start pothole inspection.");
    } finally {
      setBusy(false);
    }
  };

  const running = Boolean(status?.scan_running || status?.state === "running");

  return (
    <section className="waste-monitoring-panel" style={{ marginBottom: 24, padding: 20 }}>
      <div className="section-heading">
        <div>
          <h2>Pothole detection</h2>
          <p>Enabled video cameras are inspected every 2 hours. Events are saved separately from waste alerts.</p>
        </div>
        <span className="result-count">{running ? "Inspection running" : status?.state === "error" ? "Inspection error" : "Standby"}</span>
      </div>

      <p>{status?.message || "Waiting for pothole monitoring status..."}</p>
      <p style={{ fontSize: 13 }}>
        Next scheduled inspection: {status?.next_scan_at ? new Date(status.next_scan_at).toLocaleString() : "Not scheduled yet"}
      </p>
      <p style={{ fontSize: 13 }}>
        Last completed inspection: {status?.last_scan_at ? new Date(status.last_scan_at).toLocaleString() : "No completed inspection yet"}
      </p>

      <button
        type="button"
        onClick={inspectNow}
        disabled={running || busy}
        style={{ marginTop: 8, padding: "10px 18px", border: 0, borderRadius: 8, fontWeight: 600, cursor: running || busy ? "not-allowed" : "pointer", opacity: running || busy ? 0.6 : 1 }}
      >
        {busy ? "Starting..." : running ? "Inspection running..." : "Inspect Now"}
      </button>

      {message && <p role="status" style={{ marginTop: 10 }}>{message}</p>}
      {status?.state === "error" && <p role="alert">Latest inspection error: {status.message}</p>}
      {error && <p role="alert">Pothole monitoring status unavailable: {error}</p>}

      <div style={{ marginTop: 20 }}>
        <div className="section-heading">
          <h3>Pothole event history</h3>
          <span className="result-count">{events.length} events</span>
        </div>
        {events.length === 0 ? (
          <div className="empty-state">
            <h3>No pothole events recorded</h3>
            <p>Run an inspection on a camera with pothole detection enabled.</p>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {events.map((event) => (
              <article key={event.id} className="metric-card" style={{ padding: 14 }}>
                <strong>Pothole detected</strong>
                <div>Camera: {event.camera_name} (ID {event.camera_id})</div>
                <div style={{ fontSize: 13, marginTop: 4 }}>
                  {event.detected_at ? new Date(event.detected_at).toLocaleString() : "Time unavailable"}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}



function AccidentDetectionPage() {
  const [videos, setVideos] = useState([]);
  const [video, setVideo] = useState("");
  const [previewKey, setPreviewKey] = useState(Date.now());
  const [liveEvents, setLiveEvents] = useState([]);
  const [eventError, setEventError] = useState("");
  const [newEvent, setNewEvent] = useState(null);
  const knownEventIds = useRef(null);

  useEffect(() => {
    let active = true;
    fetch(`${API}/accidents/health`)
      .then((response) => {
        if (!response.ok) throw new Error(`Accident API returned HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (!active) return;
        const available = Array.isArray(data.available_test_videos)
          ? data.available_test_videos : [];
        setVideos(available);
        setVideo((current) => current || available[0] || "");
      })
      .catch((err) => {
        if (active) setEventError(err.message || "Could not load the accident preview.");
      });
    return () => { active = false; };
  }, []);

  const refreshLiveEvents = useCallback(async () => {
    try {
      const response = await fetch(`${API}/accidents/events`);
      if (!response.ok) throw new Error(`Accident events API returned HTTP ${response.status}`);
      const data = await response.json();
      // Support both a plain JSON array and the API's { value: [...] } shape.
      const all = Array.isArray(data)
        ? data
        : Array.isArray(data?.value)
          ? data.value
          : [];
      const live = all.filter((event) =>
        event.source_type === "live_camera" && event.camera_id != null
      );

      if (knownEventIds.current === null) {
        knownEventIds.current = new Set(live.map((event) => event.id));
        if (live.length) {
          setNewEvent(live[0]);
        }
      } else {
        const unseen = live.filter((event) => !knownEventIds.current.has(event.id));
        if (unseen.length) {
          setNewEvent(unseen[0]);
          unseen.forEach((event) => knownEventIds.current.add(event.id));
        }
      }
      setLiveEvents(live);
      setEventError("");
    } catch (err) {
      setEventError(err.message || "Could not refresh live accident events.");
    }
  }, []);

  useEffect(() => {
    refreshLiveEvents();
    const timer = window.setInterval(refreshLiveEvents, 3000);
    return () => window.clearInterval(timer);
  }, [refreshLiveEvents]);

  return (
    <section className="page-content">
      <div className="page-heading">
        <div>
          <div className="eyebrow">COMPUTER VISION</div>
          <h1>Accident Detection</h1>
          <p>Live accident monitoring is automatic for cameras with Accident detection enabled.</p>
        </div>
      </div>

      {newEvent && (
        <div className="notice-card" role="alert" style={{ marginBottom: 20, borderLeft: "4px solid #d97706" }}>
          <strong>New possible accident detected</strong>
          <p>
            {newEvent.camera_name || `Camera ${newEvent.camera_id}`}
            {" ? "}Trigger at {Number(newEvent.alert_trigger_seconds).toFixed(1)}s
            {" ? "}Probability {(Number(newEvent.peak_probability) * 100).toFixed(1)}%
          </p>
          <p>Experimental candidate; this is not a verified real-world accident.</p>
          <button type="button" className="button button--secondary" onClick={() => setNewEvent(null)}>
            Dismiss notification
          </button>
        </div>
      )}

      <section className="waste-monitoring-panel" style={{ padding: 20, marginBottom: 24 }}>
        <div className="section-heading">
          <div>
            <h2>Live accident events</h2>
            <p>Automatically refreshed from the background accident worker.</p>
          </div>
          <span className="result-count">{liveEvents.length} candidates</span>
        </div>

        {eventError && (
          <div className="notice-card" role="status" style={{ marginBottom: 12 }}>
            <strong>Monitoring update issue</strong>
            <p>{eventError}</p>
          </div>
        )}

        {liveEvents.length === 0 ? (
          <div className="empty-state">Monitoring is active. No live-camera accident candidates have been recorded yet.</div>
        ) : (
          <div className="event-list">
            {liveEvents.slice(0, 8).map((event) => (
              <div className="event-row" key={event.id}>
                <div className="event-row__content">
                  <strong>{event.camera_name || `Camera ${event.camera_id}`}</strong>
                  <p>{String(event.detection_type || "possible_accident").replaceAll("_", " ")}</p>
                  <p>
                    Trigger: {Number(event.alert_trigger_seconds).toFixed(1)}s
                    {" ? "}Probability: {(Number(event.peak_probability) * 100).toFixed(1)}%
                  </p>
                  <p style={{ fontSize: 12 }}>Experimental candidate; verify before treating as a real accident.</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="waste-monitoring-panel" style={{ padding: 20 }}>
        <div className="section-heading">
          <div>
            <h2>Annotated vehicle preview</h2>
            <p>Preview a test clip here; live monitoring runs independently in the background.</p>
          </div>
          <span className="result-count">Test video</span>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 16 }}>
          <label htmlFor="accident-test-video">Video preview</label>
          <select
            id="accident-test-video"
            value={video}
            onChange={(event) => {
              setVideo(event.target.value);
              setPreviewKey(Date.now());
            }}
            disabled={!videos.length}
          >
            {videos.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </div>
        {video ? (
          <div style={{ background: "#101820", borderRadius: 12, overflow: "hidden", textAlign: "center" }}>
            <img
              key={`${video}-${previewKey}`}
              src={`${API}/accidents/preview/${encodeURIComponent(video)}?t=${previewKey}`}
              alt={`Vehicle detection preview for ${video}`}
              style={{ display: "block", width: "100%", maxHeight: 600, objectFit: "contain", margin: "0 auto" }}
            />
          </div>
        ) : (
          <div className="empty-state">Loading available preview videos...</div>
        )}
      </section>
    </section>
  );
}

function DetectionVideoPage({
  title,
  description,
  cameras,
  enabledKey,
  monitorUrl,
  statusUrl,
  eventsUrl,
  actionLabel,
  previewUrl,
}) {
  const [status, setStatus] = useState(null);
  const [events, setEvents] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const enabledCameras = useMemo(
    () => cameras.filter(
      (camera) =>
        camera?.[enabledKey] === true ||
        camera?.[enabledKey] === 1 ||
        camera?.[enabledKey] === "true"
    ),
    [cameras, enabledKey]
  );

  const refresh = useCallback(async () => {
    try {
      const [statusResponse, eventsResponse] = await Promise.all([
        fetch(statusUrl),
        fetch(eventsUrl),
      ]);

      if (!statusResponse.ok) {
        throw new Error(`Status request failed (HTTP ${statusResponse.status})`);
      }
      if (!eventsResponse.ok) {
        throw new Error(`Event request failed (HTTP ${eventsResponse.status})`);
      }

      const [statusData, eventsData] = await Promise.all([
        statusResponse.json(),
        eventsResponse.json(),
      ]);

      setStatus(statusData);
      setEvents(Array.isArray(eventsData) ? eventsData : []);
      setError("");
    } catch (err) {
      setError(err.message || "Unable to refresh detection status.");
    }
  }, [statusUrl, eventsUrl]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [refresh]);

  const running = Boolean(status?.scan_running || status?.state === "running");

  const runInspection = async () => {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(monitorUrl, { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || `Inspection request failed (HTTP ${response.status})`);
      }
      setMessage(data.message || `${actionLabel} started.`);
      await refresh();
    } catch (err) {
      setMessage(err.message || "Could not start inspection.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section className="page-heading">
        <div>
          <div className="eyebrow">VIDEO DETECTION</div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        <button
          type="button"
          onClick={runInspection}
          disabled={busy || running}
        >
          {busy ? "Starting..." : running ? "Inspection running..." : actionLabel}
        </button>
      </section>

      <section className="page-content">
        <div className="metric-grid">
          <article className="metric-card">
            <div className="metric-card__label">Enabled cameras</div>
            <div className="metric-card__value">{enabledCameras.length}</div>
            <div className="metric-card__caption">Configured for this module</div>
          </article>
          <article className="metric-card">
            <div className="metric-card__label">Recorded events</div>
            <div className="metric-card__value">{events.length}</div>
            <div className="metric-card__caption">Most recent events returned by the API</div>
          </article>
        </div>

        {message && <p role="status">{message}</p>}
        {error && <p role="alert">Could not refresh status: {error}</p>}
        {status?.state === "error" && <p role="alert">{status.message}</p>}

        <div className="section-heading" style={{ marginTop: 24 }}>
          <div>
            <h2>{title} videos</h2>
            <p>Play the registered camera videos below. Video playback is separate from the inspection scan.</p>
          </div>
        </div>

        {enabledCameras.length === 0 ? (
          <div className="empty-state">
            <h3>No cameras enabled</h3>
            <p>Open Live Cameras, edit a camera, and enable {title} for it.</p>
          </div>
        ) : (
          <div className="camera-grid">
            {enabledCameras.map((camera) => {
              const id = getCameraId(camera);
              return (
                <article className="camera-card" key={id}>
                  <div className="camera-card__header">
                    <div>
                      <h3>{getCameraName(camera)}</h3>
                      <p>Camera ID {id} ? {camera.source_type || "video"}</p>
                    </div>
                  </div>
                  <div className="video-frame">
                    <img
  key={`${id}-annotated-preview`}
  src={`${API}${previewUrl.replace("{id}", id)}`}
  alt={`Annotated ${title.toLowerCase()} preview for ${getCameraName(camera)}`}
  style={{
    width: "100%",
    display: "block",
  }}
/>
                  </div>
                  <div className="video-footer">
                    <div className="video-footer__info">
                      <strong>{camera.location || camera.name || `Camera ${id}`}</strong>
                      <span>{camera.source || "Registered video source"}</span>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <div className="section-heading" style={{ marginTop: 32 }}>
          <div>
            <h2>Recent {title.toLowerCase()} events</h2>
            <p>Latest saved detections for this module.</p>
          </div>
        </div>

        {events.length === 0 ? (
          <div className="empty-state">
            <h3>No events recorded</h3>
            <p>Run an inspection on an enabled camera to check for detections.</p>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {events.slice(0, 30).map((event) => (
              <article className="metric-card" key={event.id}>
                <strong>{String(event.detection_type || title).replaceAll("_", " ")}</strong>
                <div>{event.camera_name || `Camera ${event.camera_id}`}</div>
                <div className="metric-card__caption">
                  {event.detected_at
                    ? new Date(event.detected_at).toLocaleString()
                    : "Time unavailable"}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </>
  );
}


function App() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("urbanvision-theme") === "dark" ? "dark" : "light";
    } catch {
      return "light";
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem("urbanvision-theme", theme);
    } catch {
      // Theme still works for this session if storage is unavailable.
    }
  }, [theme]);
  const [activePage, setActivePage] = useState("cameras");
  const [cameras, setCameras] = useState([]);
  const [selectedCameraId, setSelectedCameraId] = useState(null);
  const [analysisCameraId, setAnalysisCameraId] = useState(1);

  const trafficEnabledCameras = cameras.filter(
    (camera) => Boolean(camera.traffic_enabled)
  );

  useEffect(() => {
    setAnalysisCameraId((currentId) => {
      const currentIsEnabled = trafficEnabledCameras.some(
        (camera) => getCameraId(camera) === currentId
      );

      if (currentIsEnabled) return currentId;

      return trafficEnabledCameras.length
        ? getCameraId(trafficEnabledCameras[0])
        : null;
    });
  }, [cameras]);
  const [laneEditorOpen, setLaneEditorOpen] = useState(false);
  const [laneConfigStatus, setLaneConfigStatus] = useState(null);
  const [laneConfigError, setLaneConfigError] = useState("");
  const [workerStatus, setWorkerStatus] = useState(null);
  const [trafficResults, setTrafficResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const [backendError, setBackendError] = useState("");
  const [showAddCamera, setShowAddCamera] = useState(false);
  const [newCameraName, setNewCameraName] = useState("");
  const [newCameraLocation, setNewCameraLocation] = useState("");
  const [newCameraSource, setNewCameraSource] = useState("");
  const [newTrafficEnabled, setNewTrafficEnabled] = useState(true);
  const [newAccidentEnabled, setNewAccidentEnabled] = useState(true);
  const [newPotholeEnabled, setNewPotholeEnabled] = useState(true);
  const [newWasteEnabled, setNewWasteEnabled] = useState(true);
  const [cameraSubmitting, setCameraSubmitting] = useState(false);
  const [cameraSubmitError, setCameraSubmitError] = useState("");
  const [cameraSubmitMessage, setCameraSubmitMessage] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [showEditCamera, setShowEditCamera] = useState(false);
  const [editCameraName, setEditCameraName] = useState("");
  const [editCameraLocation, setEditCameraLocation] = useState("");
  const [editTrafficEnabled, setEditTrafficEnabled] = useState(true);
  const [editAccidentEnabled, setEditAccidentEnabled] = useState(true);
  const [editPotholeEnabled, setEditPotholeEnabled] = useState(true);
  const [editWasteEnabled, setEditWasteEnabled] = useState(true);
  const [editCameraSubmitting, setEditCameraSubmitting] = useState(false);
  const [editCameraError, setEditCameraError] = useState("");
  const [editCameraMessage, setEditCameraMessage] = useState("");

  const selectedCamera = useMemo(
    () =>
      cameras.find((camera) => getCameraId(camera) === selectedCameraId) ||
      null,
    [cameras, selectedCameraId]
  );

  useEffect(() => {
    if (selectedCameraId === null || selectedCameraId === undefined) {
      setLaneConfigStatus(null);
      setLaneConfigError("");
      setLaneEditorOpen(false);
      return;
    }

    let cancelled = false;

    async function loadLaneConfiguration() {
      setLaneConfigStatus(null);
      setLaneConfigError("");

      try {
        const response = await fetch(
          `${API}/traffic/cameras/${selectedCameraId}/lanes`
        );

        if (!response.ok) {
          throw new Error(`Could not load lane configuration (HTTP ${response.status})`);
        }

        const payload = await response.json();
        const savedLanes = payload.lanes || {};

        if (!cancelled) {
          setLaneConfigStatus(Object.keys(savedLanes).length > 0);
        }
      } catch (error) {
        if (!cancelled) {
          setLaneConfigStatus(null);
          setLaneConfigError(error.message || "Could not load lane configuration.");
        }
      }
    }

    loadLaneConfiguration();

    return () => {
      cancelled = true;
    };
  }, [selectedCameraId]);
  const fetchData = useCallback(async (initial = false) => {
    if (initial) setLoading(true);

    try {
      const responses = await Promise.all([
        fetch(`${API}/cameras/`),
        fetch(`${API}/traffic/worker/status`),
        fetch(`${API}/traffic/worker/results`),
      ]);

      const failedResponse = responses.find((response) => !response.ok);
      if (failedResponse) {
        throw new Error(`Backend returned HTTP ${failedResponse.status}`);
      }

      const [cameraPayload, workerPayload, resultsPayload] = await Promise.all(
        responses.map((response) => response.json())
      );

      const cameraList = getList(cameraPayload);
      setCameras(cameraList);
      setWorkerStatus(workerPayload);
      setTrafficResults(resultsPayload);
      setBackendError("");
      setLastUpdated(new Date());

      setSelectedCameraId((currentId) => {
        if (
          currentId !== null &&
          cameraList.some((camera) => getCameraId(camera) === currentId)
        ) {
          return currentId;
        }

        return null;
      });
    } catch (error) {
      setBackendError(
        `Could not load live data. Check that the FastAPI backend is running at ${API}. ${error.message}`
      );
    } finally {
      if (initial) setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(true);

    const interval = window.setInterval(
      () => fetchData(false),
      POLL_INTERVAL
    );

    return () => window.clearInterval(interval);
  }, [fetchData]);

  const handleAddCamera = async (event) => {
    event.preventDefault();
    setCameraSubmitError("");
    setCameraSubmitMessage("");

    const name = newCameraName.trim();
    const source = newCameraSource.trim();
    const location = newCameraLocation.trim() || "Unknown location";

    if (!name || !source) {
      setCameraSubmitError("Camera name and video path are required.");
      return;
    }

    setCameraSubmitting(true);

    try {
      const response = await fetch(`${API}/cameras/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          location,
          source,
          source_type: "video",
          traffic_enabled: newTrafficEnabled,
          accident_enabled: newAccidentEnabled,
          pothole_enabled: newPotholeEnabled,
          waste_enabled: newWasteEnabled,
        }),
      });

      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(
          typeof detail === "string"
            ? detail
            : `Camera registration failed (HTTP ${response.status}).`
        );
      }

      await fetchData(false);
      setNewCameraName("");
      setNewCameraLocation("");
      setNewCameraSource("");
      setNewTrafficEnabled(true);
      setNewAccidentEnabled(true);
      setNewPotholeEnabled(true);
      setNewWasteEnabled(true);
      setShowAddCamera(false);
      setCameraSubmitMessage(`Camera "${name}" registered successfully.`);
    } catch (err) {
      setCameraSubmitError(err.message || "Could not register the camera.");
    } finally {
      setCameraSubmitting(false);
    }
  };

  const handleEditCamera = async (event) => {
    event.preventDefault();
    if (!selectedCamera || !selectedCameraId) return;

    setEditCameraError("");
    setEditCameraMessage("");

    const name = editCameraName.trim();
    const location = editCameraLocation.trim() || "Unknown location";

    if (!name) {
      setEditCameraError("Camera name is required.");
      return;
    }

    setEditCameraSubmitting(true);

    try {
      const response = await fetch(`${API}/cameras/${selectedCameraId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          location,
          traffic_enabled: editTrafficEnabled,
          accident_enabled: editAccidentEnabled,
          pothole_enabled: editPotholeEnabled,
          waste_enabled: editWasteEnabled,
        }),
      });

      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(
          typeof detail === "string"
            ? detail
            : `Camera update failed (HTTP ${response.status}).`
        );
      }

      await fetchData(false);
      setShowEditCamera(false);
      setEditCameraMessage("Camera details updated successfully.");
    } catch (error) {
      setEditCameraError(error.message || "Could not update camera details.");
    } finally {
      setEditCameraSubmitting(false);
    }
  };

  const openCamera = (camera) => {
    setSelectedCameraId(getCameraId(camera));
    setActivePage("monitor");
  };

  const goToCameras = () => {
    setActivePage("cameras");
  };

  const currentResult = selectedCameraId
    ? getResultsForCamera(trafficResults, selectedCameraId)
    : null;

  const currentWorker = selectedCameraId
    ? getWorkerForCamera(workerStatus, selectedCameraId)
    : null;

  const vehicleCount = getVehicleCount(currentResult);
  const lanes = getLaneEntries(currentResult);
  const workerRunning = getWorkerRunning(currentWorker);

  const enabledTrafficCameras = cameras.filter(
    (camera) => camera.traffic_enabled === true
  ).length;

  const overviewPage = activePage === "overview";
  const cameraPage = activePage === "cameras";
  const monitorPage = activePage === "monitor";
  const laneEditorPage = activePage === "laneEditor";
  const analyticsPage = activePage === "analytics";
  const wastePage = activePage === "waste";
  const accidentsPage = activePage === "accidents";
    const potholesPage = activePage === "potholes";
  const eventsPage = activePage === "events";
  const settingsPage = activePage === "settings";

  return (
    <div className={`app-shell app-shell--${theme}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__mark">UV</div>
          <div className="brand__text">
            <strong>UrbanVision</strong>
            <span>SMART CITY INTELLIGENCE</span>
          </div>
        </div>

        <div className="sidebar__section-label">WORKSPACE</div>

        <nav className="sidebar__nav" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${
                activePage === item.id ||
                ((monitorPage || laneEditorPage) && item.id === "cameras")
                  ? "nav-item--active"
                  : ""
              }`}
              onClick={() => setActivePage(item.id)}
            >
              {item.icon && <span className="nav-item__icon">{item.icon}</span>}
              <span>{item.label}</span>
              {item.id === "cameras" && (
                <span className="nav-item__count">{cameras.length}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar__bottom">
          <div className="sidebar__footer">
            <span>URBANVISION</span>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="topbar__breadcrumb">
            <span>UrbanVision</span>
            <span className="breadcrumb-chevron">/</span>
            <strong>
              {monitorPage
                ? "Camera monitoring"
                : NAV_ITEMS.find((item) => item.id === activePage)?.label ||
                  "Dashboard"}
            </strong>
          </div>
          <div className="topbar__right">
            <span className="live-indicator">
              <span className="live-indicator__dot" />
              LIVE MONITORING
            </span>
            <div className="topbar__avatar">UV</div>
          </div>
        </header>

        {backendError && (
          <div className="connection-banner" role="alert">
            <strong>Connection issue</strong>
            <span>{backendError}</span>
            <button type="button" onClick={() => fetchData(true)}>
              Retry
            </button>
          </div>
        )}

        <div className="page-content">
          {cameraPage && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">MONITORING CENTER</div>
                  <h1>Live cameras</h1>
                  <p>
                    Select a registered camera to view its video and traffic
                    analysis.
                  </p>
                </div>
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => fetchData(true)}
                >
                  Refresh
                </button>
              </section>

              <section className="add-camera-panel">
                <div className="add-camera-panel__heading">
                  <div>
                    <h2>Add a camera</h2>
                    <p>Register a local video file for monitoring.</p>
                  </div>
                  <button
                    type="button"
                    className="button button--secondary"
                    onClick={() => {
                      setShowAddCamera((current) => !current);
                      setCameraSubmitError("");
                      setCameraSubmitMessage("");
                    }}
                  >
                    {showAddCamera ? "Cancel" : "+ Add Camera"}
                  </button>
                </div>

                {cameraSubmitMessage && (
                  <p className="add-camera-message add-camera-message--success">
                    {cameraSubmitMessage}
                  </p>
                )}

                {cameraSubmitError && (
                  <p className="add-camera-message add-camera-message--error">
                    {cameraSubmitError}
                  </p>
                )}

                {showAddCamera && (
                  <form className="add-camera-form" onSubmit={handleAddCamera}>
                    <label>
                      Camera name *
                      <input
                        type="text"
                        value={newCameraName}
                        onChange={(event) => setNewCameraName(event.target.value)}
                        placeholder="e.g. North Junction"
                        maxLength={100}
                        required
                      />
                    </label>

                    <label>
                      Location
                      <input
                        type="text"
                        value={newCameraLocation}
                        onChange={(event) => setNewCameraLocation(event.target.value)}
                        placeholder="e.g. North Junction, Kochi"
                        maxLength={150}
                      />
                    </label>

                    <fieldset style={{ border: "1px solid var(--border-color, #d1d5db)", borderRadius: 8, padding: 12, margin: "4px 0 12px" }}>
                      <legend>Detection modules</legend>
                      <label><input type="checkbox" checked={newTrafficEnabled} onChange={(e) => setNewTrafficEnabled(e.target.checked)} /> Traffic detection</label>
                      <label><input type="checkbox" checked={newAccidentEnabled} onChange={(e) => setNewAccidentEnabled(e.target.checked)} /> Accident detection</label>
                      <label><input type="checkbox" checked={newPotholeEnabled} onChange={(e) => setNewPotholeEnabled(e.target.checked)} /> Pothole detection</label>
                      <label><input type="checkbox" checked={newWasteEnabled} onChange={(e) => setNewWasteEnabled(e.target.checked)} /> Waste detection</label>
                    </fieldset>

                    <label className="add-camera-form__source">
                      Video path *
                      <input
                        type="text"
                        value={newCameraSource}
                        onChange={(event) => setNewCameraSource(event.target.value)}
                        placeholder="datasets/traffic_videos/my_video.mp4"
                        maxLength={500}
                        required
                      />
                    </label>

                    <p className="add-camera-form__hint">
                      Enter a path to an existing video file relative to the
                      Urban Vision project root, or an absolute local file path.
                      The backend must be able to access the file.
                    </p>

                    <button
                      type="submit"
                      className="button button--primary"
                      disabled={cameraSubmitting}
                    >
                      {cameraSubmitting ? "Registering..." : "Register Camera"}
                    </button>
                  </form>
                )}
              </section>

              <section className="summary-strip">
                <div className="summary-strip__item">
                  
                  <div>
                    <span className="summary-strip__label">
                      Registered cameras
                    </span>
                    <strong>{loading ? "—" : cameras.length}</strong>
                  </div>
                </div>
                <div className="summary-strip__divider" />
                <div className="summary-strip__item">
                  
                  <div>
                    <span className="summary-strip__label">
                      Traffic monitoring enabled
                    </span>
                    <strong>{loading ? "—" : enabledTrafficCameras}</strong>
                  </div>
                </div>
                <div className="summary-strip__divider" />
                <div className="summary-strip__item summary-strip__item--last">
                  
                  <div>
                    <span className="summary-strip__label">
                      Data refresh interval
                    </span>
                    <strong>3 seconds</strong>
                  </div>
                </div>
              </section>

              <section className="section-heading">
                <div>
                  <h2>Registered cameras</h2>
                  <p>Choose a camera to open its dedicated monitoring page.</p>
                </div>
                <span className="result-count">
                  {cameras.length} {cameras.length === 1 ? "camera" : "cameras"}
                </span>
              </section>

              {loading && cameras.length === 0 ? (
                <div className="empty-state">
                  
                  <h3>Loading cameras</h3>
                  <p>Connecting to the UrbanVision backend</p>
                </div>
              ) : cameras.length === 0 ? (
                <div className="empty-state">
                  
                  <h3>No cameras found</h3>
                  <p>
                    Check your backend connection and registered camera records.
                  </p>
                  <button
                    type="button"
                    className="button button--primary"
                    onClick={() => fetchData(true)}
                  >
                    Try again
                  </button>
                </div>
              ) : (
                <section className="camera-grid">
                  {cameras.map((camera) => {
                    const cameraId = getCameraId(camera);
                    const isTrafficEnabled = camera.traffic_enabled === true;
                    const worker = getWorkerForCamera(
                      workerStatus,
                      cameraId
                    );
                    const running = getWorkerRunning(worker);

                    return (
                      <article className="camera-card" key={cameraId}>
                        <div className="camera-card__visual">
                          <div className="camera-card__visual-glow" />
                          <div className="camera-card__camera-icon">*</div>
                          <span className="camera-card__id">
                            CAM {String(cameraId).padStart(2, "0")}
                          </span>
                          <span className="camera-card__visual-label">
                            URBANVISION / TRAFFIC
                          </span>
                        </div>

                        <div className="camera-card__body">
                          <div className="camera-card__title-row">
                            <div>
                              <span className="camera-card__overline">
                                CAMERA {cameraId}
                              </span>
                              <h3>{getCameraName(camera)}</h3>
                            </div>
                            <span className="camera-card__location-icon">
                              *
                            </span>
                          </div>

                          <div className="camera-card__status-row">
                            <StatusPill active={isTrafficEnabled}>
                              {isTrafficEnabled
                                ? "Traffic enabled"
                                : "Traffic disabled"}
                            </StatusPill>
                            {running !== null && (
                              <span className="camera-card__worker-status">
                                {running ? "Worker running" : "Worker stopped"}
                              </span>
                            )}
                          </div>

                          <div className="camera-card__details">
                            <span>Video source</span>
                            <span>
                              {camera.source
                                ? String(camera.source).split(/[\\/]/).pop()
                                : "Source not provided"}
                            </span>
                          </div>

                          <button
                            type="button"
                            className="button button--primary camera-card__button"
                            onClick={() => openCamera(camera)}
                          >
                            Open camera <span>*</span>
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </section>
              )}

              <div className="page-footnote">
                <span className="page-footnote__dot" />
                Camera information refreshes automatically while this page is
                open.
                {lastUpdated && (
                  <span> Last updated {lastUpdated.toLocaleTimeString()}.</span>
                )}
              </div>
            </>
          )}

          {monitorPage && (
            <>
              <section className="monitor-heading">
                <div className="monitor-heading__left">
                  <button
                    type="button"
                    className="back-button"
                    onClick={goToCameras}
                  >
                    <span aria-hidden="true">?</span> Back to cameras
                  </button>
                  <div className="eyebrow">CAMERA MONITORING</div>
                  <h1>{selectedCamera ? getCameraName(selectedCamera) : "Camera"}</h1>
                  <p>
                    Camera ID: {selectedCameraId ?? "*"}{" "}
                    <span className="heading-dot">*</span> Live video and traffic
                    metrics
                  </p>

                  {selectedCamera && (
                    <div className="camera-management-actions">
                      <button
                        type="button"
                        className="button button--secondary"
                        disabled={editCameraSubmitting}
                        onClick={() => {
                          setEditCameraError("");
                          setEditCameraMessage("");
                          setEditCameraName(selectedCamera.name || "");
                          setEditCameraLocation(selectedCamera.location || "");
                          setEditTrafficEnabled(selectedCamera.traffic_enabled ?? true);
                          setEditAccidentEnabled(selectedCamera.accident_enabled ?? true);
                          setEditPotholeEnabled(selectedCamera.pothole_enabled ?? true);
                          setEditWasteEnabled(selectedCamera.waste_enabled ?? true);
                          setShowEditCamera((open) => !open);
                        }}
                      >
                        {showEditCamera ? "Close editor" : "Edit camera details"}
                      </button>
                    </div>
                  )}

                  {editCameraMessage && (
                    <p className="camera-edit-feedback camera-edit-feedback--success" role="status">
                      {editCameraMessage}
                    </p>
                  )}

                  {showEditCamera && selectedCamera && (
                    <form className="camera-edit-form" onSubmit={handleEditCamera}>
                      <label>
                        Camera name
                        <input
                          type="text"
                          value={editCameraName}
                          onChange={(event) => setEditCameraName(event.target.value)}
                          maxLength={120}
                          required
                        />
                      </label>

                      <label>
                        Location / address
                        <input
                          type="text"
                          value={editCameraLocation}
                          onChange={(event) => setEditCameraLocation(event.target.value)}
                          maxLength={255}
                          placeholder="Enter camera location"
                        />
                      </label>

                      <fieldset style={{ border: "1px solid var(--border-color, #d1d5db)", borderRadius: 8, padding: 12, margin: "4px 0 12px" }}>
                        <legend>Detection modules</legend>
                        <label><input type="checkbox" checked={editTrafficEnabled} onChange={(e) => setEditTrafficEnabled(e.target.checked)} /> Traffic detection</label>
                        <label><input type="checkbox" checked={editAccidentEnabled} onChange={(e) => setEditAccidentEnabled(e.target.checked)} /> Accident detection</label>
                        <label><input type="checkbox" checked={editPotholeEnabled} onChange={(e) => setEditPotholeEnabled(e.target.checked)} /> Pothole detection</label>
                        <label><input type="checkbox" checked={editWasteEnabled} onChange={(e) => setEditWasteEnabled(e.target.checked)} /> Waste detection</label>
                      </fieldset>

                      {editCameraError && (
                        <p className="camera-edit-feedback camera-edit-feedback--error" role="alert">
                          {editCameraError}
                        </p>
                      )}

                      <div className="camera-edit-form__actions">
                        <button
                          type="button"
                          className="button button--secondary"
                          disabled={editCameraSubmitting}
                          onClick={() => {
                            setShowEditCamera(false);
                            setEditCameraError("");
                          }}
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          className="button button--primary"
                          disabled={editCameraSubmitting}
                        >
                          {editCameraSubmitting ? "Saving..." : "Save changes"}
                        </button>
                      </div>
                    </form>
                  )}
                </div>
                <div className="monitor-heading__status">
                  <StatusPill active={selectedCamera?.traffic_enabled === true}>
                    {selectedCamera?.traffic_enabled
                      ? "Traffic monitoring enabled"
                      : "Traffic monitoring disabled"}
                  </StatusPill>
                  <div className="lane-config-heading">
                    <span className="lane-config-heading__label">
                      Lane configuration
                    </span>
                    <StatusPill active={laneConfigStatus === true}>
                      {laneConfigStatus === true
                        ? "Configured"
                        : laneConfigStatus === false
                          ? "Not configured"
                          : laneConfigError
                            ? "Unavailable"
                            : "Checking..."}
                    </StatusPill>
                    <button
                      type="button"
                      className="button button--secondary"
                      onClick={() => setActivePage("laneEditor")}
                      disabled={!selectedCamera || !!laneConfigError}
                    >
                      {laneConfigStatus === true ? "Redo lanes" : "Configure lanes"}
                    </button>
                    {laneConfigError && (
                      <span className="lane-config-error">
                        {laneConfigError}
                      </span>
                    )}
                  </div>
                </div>
              </section>

              {!selectedCamera ? (
                <div className="empty-state">
                  
                  <h3>Camera not available</h3>
                  <p>
                    This camera may have been removed from the backend. Return
                    to the selection page to choose another camera.
                  </p>
                  <button
                    type="button"
                    className="button button--primary"
                    onClick={goToCameras}
                  >
                    Back to cameras
                  </button>
                </div>
              ) : (
                <>
                  <section className="monitor-layout">
                    <article className="video-panel">
                      <div className="panel-heading">
                        <div>
                          <span className="panel-kicker">VIDEO FEED</span>
                          <h2>Camera stream</h2>
                        </div>
                        <span className="feed-badge">
                          <span /> FILE PLAYBACK
                        </span>
                      </div>

                      <div className="video-frame">
                        <video
  key={`${selectedCameraId}-raw`}
  src={`${API}/cameras/${selectedCameraId}/video`}
  controls
  autoPlay
  loop
  muted
  playsInline
  preload="metadata"
>
  Your browser does not support video playback.
</video>
                      </div>

                      <div className="video-footer">
                        <div className="video-footer__info">
                          <span className="video-footer__camera-icon">*</span>
                          <div>
                            <strong>{getCameraName(selectedCamera)}</strong>
                            <span>
                              Source:{" "}
                              {selectedCamera.source ||
                                "Configured camera video"}
                            </span>
                          </div>
                        </div>
                        <span className="video-footer__id">
                          ID {selectedCameraId}
                        </span>
                      </div>
                    </article>

                    <aside className="analytics-panel">
                      <div className="panel-heading">
                        <div>
                          <span className="panel-kicker">LIVE ANALYSIS</span>
                          <h2>Traffic overview</h2>
                        </div>
                        <span className="analytics-panel__symbol">*</span>
                      </div>

                      <div className="primary-metric">
                        <div className="primary-metric__icon">*</div>
                        <div className="primary-metric__label">
                          Detected vehicles
                        </div>
                        <div className="primary-metric__value">
                          {formatNumber(vehicleCount)}
                        </div>
                        <div className="primary-metric__caption">
                          {vehicleCount === null
                            ? "Waiting for detection results"
                            : "From the latest available processing result"}
                        </div>
                      </div>

                      <div className="worker-status-card">
                        <div>
                          <span className="worker-status-card__label">
                            Processing worker
                          </span>
                          <strong>
                            {workerRunning === null
                              ? "Status unavailable"
                              : workerRunning
                                ? "Running"
                                : "Stopped"}
                          </strong>
                        </div>
                        <span
                          className={`worker-status-card__indicator ${
                            workerRunning ? "is-running" : ""
                          }`}
                        />
                      </div>

                      <div className="lane-section">
                        <div className="lane-section__heading">
                          <div>
                            <h3>Lane occupancy</h3>
                            <p>Latest available lane metrics</p>
                          </div>
                          <span className="lane-section__count">
                            {lanes.length}
                          </span>
                        </div>

                        {lanes.length === 0 ? (
                          <div className="lane-empty">
                            <span>*</span>
                            <p>No lane occupancy results available yet.</p>
                          </div>
                        ) : (
                          <div className="lane-list">
                            {lanes.map((lane, index) => {
                              const percentage = clampPercentage(lane.value);
                      const signalData =
                        lane.signal_status ??
                        lane.traffic_signal_status ??
                        lane.signal ??
                        lane.traffic_light ??
                        lane.trafficSignal ??
                        null;
                      const signalValue =
                        signalData && typeof signalData === "object"
                          ? signalData.status ?? signalData.state ?? signalData.color
                          : signalData;
                      const signalText = String(signalValue ?? "")
                        .trim()
                        .toLowerCase();
                      const signalColor =
                        signalText === "green" || signalText === "go"
                          ? "green"
                          : signalText === "red" || signalText === "stop"
                            ? "red"
                            : "unknown";
                      const signalLabel =
                        signalColor === "green"
                          ? "GREEN"
                          : signalColor === "red"
                            ? "RED"
                            : "UNKNOWN";
                      const greenTime = Number(lane.green_time ?? 0);
                      const timeRemaining = Number(lane.time_remaining ?? 0);
                      const vehicleShare = Number(lane.vehicle_count_percent ?? 0);

                              return (
                                <div
                                  className="lane-item"
                                  key={`${lane.name}-${index}`}
                                >
                                  <div className="lane-item__top">
                                    <span>{lane.name}</span>
                                    <strong>
                                      {Math.round(percentage)}%
                                    </strong>
                                  </div>
                                  <div className="lane-bar">
                                    <div
                                      className={`lane-bar__fill ${
                                        percentage >= 80
                                          ? "lane-bar__fill--high"
                                          : percentage >= 50
                                            ? "lane-bar__fill--medium"
                                            : ""
                                      }`}
                                      style={{ width: `${percentage}%` }}
                                    />
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>

                      <div className="analytics-panel__footer">
                        
                        <span>
                          Auto-refreshes every 3 seconds
                          {lastUpdated
                            ? `  -  ${lastUpdated.toLocaleTimeString()}`
                            : ""}
                        </span>
                      </div>
                    </aside>
                  </section>

                  <section className="monitor-bottom-grid">
                    <article className="info-panel">
                      <div className="info-panel__icon">*</div>
                      <div>
                        <span className="info-panel__label">
                          Camera location
                        </span>
                        <strong>{getCameraName(selectedCamera)}</strong>
                        <p>Registered camera ID: {selectedCameraId}</p>
                      </div>
                    </article>

                    <article className="info-panel">
                      <div className="info-panel__icon info-panel__icon--blue">
                        *
                      </div>
                      <div>
                        <span className="info-panel__label">
                          Traffic detection
                        </span>
                        <strong>
                          {selectedCamera.traffic_enabled
                            ? "Enabled"
                            : "Disabled"}
                        </strong>
                        <p>
                          {selectedCamera.traffic_enabled
                            ? "This camera is configured for traffic processing."
                            : "Enable traffic processing in the camera configuration."}
                        </p>
                      </div>
                    </article>
                  </section>
<div className="monitor-return-row">
                    <button
                      type="button"
                      className="button button--secondary"
                      onClick={goToCameras}
                    >
                      ? Choose another camera
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {laneEditorPage && (
            <section className="lane-editor-page">
              <div className="page-heading">
                <div>
                  <div className="eyebrow">CAMERA SETTINGS</div>
                  <h1>Lane configuration</h1>
                  <p>
                    {selectedCamera
                      ? `${getCameraName(selectedCamera)} ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¾ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· Camera ID ${selectedCameraId}`
                      : "Choose a camera to configure its lanes."}
                  </p>
                </div>
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => setActivePage("monitor")}
                >
                  Back to camera
                </button>
              </div>

              {selectedCamera ? (
                <LaneEditor
                  key={selectedCameraId}
                  cameraId={selectedCameraId}
                  cameraName={getCameraName(selectedCamera)}
                  onClose={() => setActivePage("monitor")}
                  onSaved={() => {
                    setLaneConfigStatus(true);
                    setLaneConfigError("");
                    setActivePage("monitor");
                  }}
                />
              ) : (
                <div className="empty-state">
                  <h3>No camera selected</h3>
                  <p>Return to Live Cameras and select a camera first.</p>
                  <button
                    type="button"
                    className="button button--primary"
                    onClick={goToCameras}
                  >
                    Back to cameras
                  </button>
                </div>
              )}
            </section>
          )}
          {overviewPage && (
            <>
              <section className="page-heading">
                <div>
                  <h1>Overview</h1>
                  <p>
                    A quick summary of your UrbanVision traffic monitoring
                    system.
                  </p>
                </div>
                <button
                  type="button"
                  className="button button--primary"
                  onClick={() => setActivePage("cameras")}
                >
                  View cameras <span>*</span>
                </button>
              </section>

              <section className="metrics-grid">
                <MetricCard
                  label="Registered cameras"
                  value={loading ? "—" : cameras.length}
                  caption="Cameras registered in the backend"
                />
                <MetricCard
                  label="Traffic enabled"
                  value={loading ? "—" : enabledTrafficCameras}
                  caption="Configured for traffic processing"
                />
                <MetricCard
                  label="Processing worker"
                  value={
                    getWorkerRunning(workerStatus) === null
                      ? "Unknown"
                      : getWorkerRunning(workerStatus)
                        ? "Running"
                        : "Stopped"
                  }
                  caption="Overall worker status"
                />
              </section>

              <section className="section-heading">
                <div>
                  <h2>Go to monitoring</h2>
                  <p>Open the camera selection page to choose a video feed.</p>
                </div>
              </section>

              <div className="overview-action-card">
                <div>
                  <h3>Camera monitoring center</h3>
                  <p>
                    Select a camera first, then view its video and lane
                    occupancy on a dedicated page.
                  </p>
                </div>
                <button
                  type="button"
                  className="button button--primary"
                  onClick={() => setActivePage("cameras")}
                >
                  Select camera
                </button>
              </div>
            </>
          )}

          {analyticsPage && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">TRAFFIC INTELLIGENCE</div>
                  <h1>Traffic analytics</h1>
                  <p>
                    View the latest processing metrics available for each
                    registered camera.
                  </p>
                </div>
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => fetchData(true)}
                >
                  Refresh
                </button>
              </section>

              {/* LANE ANALYSIS VIEW */}
              <section className="lane-analysis-panel">
                <div className="section-heading">
                  <div>
                    <h2>Lane analysis</h2>
                    <p>
                      View the saved lane boundaries over the selected
                      camera video.
                    </p>
                  </div>
                  <label className="lane-camera-select">
                    <span>Camera</span>
                    <select
                      value={analysisCameraId}
                      onChange={(event) =>
                        setAnalysisCameraId(Number(event.target.value))
                      }
                    >
                      {cameras
                        .filter((camera) => Boolean(camera.traffic_enabled))
                        .map((camera) => {
                          const id = getCameraId(camera);
                          return (
                            <option key={id} value={id}>
                              {getCameraName(camera)} (ID {id})
                            </option>
                          );
                        })}
                    </select>
                  </label>
                </div>

                <div className="lane-overlay-container">
                  {analysisCameraId !== null ? (
                    <>
                      <img
                        key={analysisCameraId}
                        src={`${API}/cameras/${analysisCameraId}/traffic-preview`}
                        alt={`Annotated traffic feed for camera ${analysisCameraId}`}
                        style={{ width: "100%", display: "block" }}
                      />
                      <LaneOverlay cameraId={analysisCameraId} />
                    </>
                  ) : (
                    <p className="empty-state">
                      No cameras have traffic detection enabled. Enable traffic detection for a camera to view lane analysis.
                    </p>
                  )}
                </div>

                <p className="lane-analysis-note">
                  Lane markings use the saved configuration for each camera.
                  Confirm alignment against the video before relying on the
                  boundaries for traffic measurements.
                </p>
              </section>
                            <section className="lane-monitoring-panel">
                <div className="section-heading">
                  <div>
                    <div className="eyebrow">LIVE TRAFFIC MONITORING</div>
                    <h2>Lane-by-lane status</h2>
                    <p>Current occupancy readings and signal status for the selected camera.</p>
                  </div>
                </div>

                <div className="lane-monitoring-grid">
                  {(() => {
                    const selectedResult = getResultsForCamera(
                      trafficResults,
                      analysisCameraId
                    );
                    const selectedLanes = getLaneEntries(selectedResult);

                    if (selectedLanes.length === 0) {
                      return (
                        <div className="lane-monitoring-empty">
                          <h3>No lane measurements available</h3>
                          <p>
                            Lane percentages will appear when the traffic
                            processing worker returns measurements for this camera.
                          </p>
                        </div>
                      );
                    }

                    return selectedLanes.map((lane, index) => {
                      const percentage = clampPercentage(lane.value);
                      const signalData =
                        lane.signal_status ??
                        lane.traffic_signal_status ??
                        lane.signal ??
                        lane.traffic_light ??
                        lane.trafficSignal ??
                        null;
                      const signalValue =
                        signalData && typeof signalData === "object"
                          ? signalData.status ?? signalData.state ?? signalData.color
                          : signalData;
                      const signalText = String(signalValue ?? "")
                        .trim()
                        .toLowerCase();
                      const signalColor =
                        signalText === "green" || signalText === "go"
                          ? "green"
                          : signalText === "red" || signalText === "stop"
                            ? "red"
                            : "unknown";
                      const signalLabel =
                        signalColor === "green"
                          ? "GREEN"
                          : signalColor === "red"
                            ? "RED"
                            : "UNKNOWN";
                      const greenTime = Number(lane.green_time ?? 0);
                      const timeRemaining = Number(lane.time_remaining ?? 0);
                      const vehicleShare = Number(lane.vehicle_count_percent ?? 0);

                      return (
                        <article
                          className="lane-monitoring-card"
                          key={`${lane.name}-${index}`}
                        >
                          <div className="lane-monitoring-card__top">
                            <div>
                              <span className="lane-monitoring-card__eyebrow">
                                TRAFFIC LANE
                              </span>
                              <h3>{lane.name}</h3>
                            </div>
                            <strong className="lane-monitoring-card__percent">
                              {Math.round(percentage)}%
                            </strong>
                          </div>

                          <div className="lane-monitoring-bar">
                            <div
                              className={`lane-monitoring-bar__fill ${
                                percentage >= 80
                                  ? "is-high"
                                  : percentage >= 50
                                    ? "is-medium"
                                    : ""
                              }`}
                              style={{ width: `${percentage}%` }}
                            />
                          </div>

                          <div className={`lane-signal-status lane-signal-status--${signalColor}`}>
                            <span
                              className="lane-signal-status__dot"
                              role="img"
                              aria-label={`Traffic signal ${signalLabel.toLowerCase()}`}
                            />
                            <div>
                              <span>Traffic signal</span>
                              <strong>{signalLabel}</strong>
                              {signalColor === "green" && (
                                <small>
                                  {`Green for ${Math.ceil(Math.max(0, timeRemaining))}s remaining`}
                                </small>
                              )}
                              {greenTime > 0 && (
                                <small>{`Assigned green time: ${greenTime}s`}</small>
                              )}
                              <small>{`Vehicle share: ${vehicleShare.toFixed(1)}%`}</small>
                            </div>
                          </div>
                        </article>
                      );
                    });
                  })()}
                </div>

                <p className="lane-monitoring-note">
                  Occupancy uses the latest available backend measurements.
                  Green-light status requires verified traffic-signal logic.
                </p>
              </section>
              </>
          )}

          {wastePage && (
            <DetectionVideoPage
              title="Waste Detection"
              description="Review videos from cameras enabled for waste detection and run a manual inspection."
              cameras={cameras}
              enabledKey="waste_enabled"
              monitorUrl={`${API}/waste/monitor`}
              statusUrl={`${API}/waste/status`}
              eventsUrl={`${API}/waste/events`}
              actionLabel="Monitor Now"
            previewUrl="/cameras/{id}/waste-preview"
            />
          )}

          {accidentsPage && <AccidentDetectionPage />}
            {potholesPage && (
            <DetectionVideoPage
              title="Pothole Detection"
              description="Review videos from cameras enabled for pothole detection and inspect road surfaces."
              cameras={cameras}
              enabledKey="pothole_enabled"
              monitorUrl={`${API}/potholes/monitor`}
              statusUrl={`${API}/potholes/status`}
              eventsUrl={`${API}/potholes/events`}
              actionLabel="Inspect Now"
            previewUrl="/potholes/preview/{id}"
            />
          )}

          {eventsPage && (
            <section className="page-content">
              <WasteEventHistory />
              <PotholeEventHistory />
            </section>
          )}

          {settingsPage && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">CONFIGURATION</div>
                  <h1>Settings</h1>
                  <p>Application appearance and detection module implementation status.</p>
                </div>
                <div className="uv-theme-control">
                  <span>{theme === "dark" ? "Dark mode" : "Light mode"}</span>
                  <button
                    type="button"
                    className={`uv-theme-toggle ${theme === "dark" ? "is-dark" : ""}`}
                    role="switch"
                    aria-checked={theme === "dark"}
                    aria-label="Toggle dark mode"
                    onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
                  >
                    <span className="uv-theme-toggle__dot" />
                  </button>
                </div>
              </section>

              <section className="settings-grid uv-implementation-grid">
                <article className="settings-card">
                  <span className="settings-card__eyebrow">DETECTION MODULES</span>
                  <h3>Implementation status</h3>
                  <div className="module-row">
                    <span>Traffic detection</span>
                    <span className="module-state module-state--ready">Implemented</span>
                  </div>
                  <div className="module-row">
                    <span>Accident detection</span>
                    <span className="module-state module-state--ready">Implemented</span>
                  </div>
                  <div className="module-row">
                    <span>Pothole detection</span>
                    <span className="module-state module-state--ready">Implemented</span>
                  </div>
                  <div className="module-row">
                    <span>Waste detection</span>
                    <span className="module-state module-state--ready">Implemented</span>
                  </div>
                </article>
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;



















