
import { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";
import LaneOverlay from "./pages/Traffic/LaneOverlay.jsx";
import LaneEditor from "./pages/Traffic/LaneEditor.jsx";

const API = "http://127.0.0.1:8000";
const POLL_INTERVAL = 3000;

const NAV_ITEMS = [
  { id: "overview", icon: "•", label: "Overview" },
  { id: "cameras", icon: "•", label: "Live cameras" },
  { id: "analytics", icon: "•", label: "Traffic analytics" },
  { id: "events", icon: "•", label: "Events & alerts" },
  { id: "settings", icon: "•", label: "Settings" },
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
          Number(item?.camera_id ?? item?.cameraId ?? item?.id) === cameraId
      ) || null
    );
  }

  if (payload && typeof payload === "object") {
    if (payload.results && !Array.isArray(payload.results)) {
      const result = payload.results[cameraId];
      if (result) return result;
    }

    if (payload[cameraId] && typeof payload[cameraId] === "object") {
      return payload[cameraId];
    }

    if (
      Number(payload.camera_id ?? payload.cameraId ?? payload.id) === cameraId
    ) {
      return payload;
    }

    if (Array.isArray(payload.value)) {
      return getResultsForCamera(payload.value, cameraId);
    }

    if (Array.isArray(payload.results)) {
      return getResultsForCamera(payload.results, cameraId);
    }
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
  if (value === null || value === undefined) return "•";
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString() : "•";
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
        <span className="metric-card__icon">{icon}</span>
      </div>
      <div className="metric-card__value">{value}</div>
      <div className="metric-card__caption">{caption}</div>
    </article>
  );
}

function App() {
  const [activePage, setActivePage] = useState("cameras");
  const [cameras, setCameras] = useState([]);
  const [selectedCameraId, setSelectedCameraId] = useState(null);
  const [analysisCameraId, setAnalysisCameraId] = useState(1);
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
  const [cameraSubmitting, setCameraSubmitting] = useState(false);
  const [cameraSubmitError, setCameraSubmitError] = useState("");
  const [cameraSubmitMessage, setCameraSubmitMessage] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [showEditCamera, setShowEditCamera] = useState(false);
  const [editCameraName, setEditCameraName] = useState("");
  const [editCameraLocation, setEditCameraLocation] = useState("");
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
        body: JSON.stringify({ name, location }),
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
  const eventsPage = activePage === "events";
  const settingsPage = activePage === "settings";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__mark">U</div>
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
              <span className="nav-item__icon">{item.icon}</span>
              <span>{item.label}</span>
              {item.id === "cameras" && (
                <span className="nav-item__count">{cameras.length}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar__bottom">
          <div className="system-card">
            <div className="system-card__heading">
              <span className="system-card__indicator" />
              System connection
            </div>
            <p>{backendError ? "Backend unavailable" : "Backend monitoring"}</p>
            <span className="system-card__subtext">
              {backendError ? "Check server status" : "Refreshing every 3 sec"}
            </span>
          </div>

          <div className="sidebar__footer">
            <span>URBANVISION</span>
            <span>Traffic monitoring</span>
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
                  <span>•</span> Refresh
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
                  <span className="summary-strip__icon">•</span>
                  <div>
                    <span className="summary-strip__label">
                      Registered cameras
                    </span>
                    <strong>{loading ? "•" : cameras.length}</strong>
                  </div>
                </div>
                <div className="summary-strip__divider" />
                <div className="summary-strip__item">
                  <span className="summary-strip__icon summary-strip__icon--blue">
                    •
                  </span>
                  <div>
                    <span className="summary-strip__label">
                      Traffic monitoring enabled
                    </span>
                    <strong>{loading ? "•" : enabledTrafficCameras}</strong>
                  </div>
                </div>
                <div className="summary-strip__divider" />
                <div className="summary-strip__item summary-strip__item--last">
                  <span className="summary-strip__icon summary-strip__icon--green">
                    •
                  </span>
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
                  <div className="empty-state__icon">•</div>
                  <h3>Loading cameras</h3>
                  <p>Connecting to the UrbanVision backend•</p>
                </div>
              ) : cameras.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-state__icon">•</div>
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
                          <div className="camera-card__camera-icon">•</div>
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
                              •
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
                            Open camera <span>•</span>
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
                    <span>•</span> Back to cameras
                  </button>
                  <div className="eyebrow">CAMERA MONITORING</div>
                  <h1>{selectedCamera ? getCameraName(selectedCamera) : "Camera"}</h1>
                  <p>
                    Camera ID: {selectedCameraId ?? "•"}{" "}
                    <span className="heading-dot">•</span> Live video and traffic
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
                  <div className="empty-state__icon">•</div>
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
                          key={selectedCameraId}
                          src={`${API}/cameras/${selectedCameraId}/video`}
                          controls
                          autoPlay
                          muted
                          loop
                          playsInline
                          preload="metadata"
                        >
                          Your browser does not support video playback.
                        </video>
                      </div>

                      <div className="video-footer">
                        <div className="video-footer__info">
                          <span className="video-footer__camera-icon">•</span>
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
                        <span className="analytics-panel__symbol">•</span>
                      </div>

                      <div className="primary-metric">
                        <div className="primary-metric__icon">•</div>
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
                            <span>•</span>
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
                        <span className="refresh-icon">•</span>
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
                      <div className="info-panel__icon">•</div>
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
                        •
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
                      • Choose another camera
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
                      ? `${getCameraName(selectedCamera)} · Camera ID ${selectedCameraId}`
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
                  <div className="eyebrow">YOUR CONTROL CENTER</div>
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
                  View cameras <span>•</span>
                </button>
              </section>

              <section className="metrics-grid">
                <MetricCard
                  label="Registered cameras"
                  value={loading ? "•" : cameras.length}
                  caption="Cameras registered in the backend"
                  icon="•"
                />
                <MetricCard
                  label="Traffic enabled"
                  value={loading ? "•" : enabledTrafficCameras}
                  caption="Configured for traffic processing"
                  icon="•"
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
                  icon="•"
                />
              </section>

              <section className="section-heading">
                <div>
                  <h2>Go to monitoring</h2>
                  <p>Open the camera selection page to choose a video feed.</p>
                </div>
              </section>

              <div className="overview-action-card">
                <div className="overview-action-card__icon">•</div>
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
                  Select camera •
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
                  • Refresh
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
                      {cameras.map((camera) => {
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
                  <video
                    key={analysisCameraId}
                    src={`${API}/cameras/${analysisCameraId}/video`}
                    controls
                    autoPlay
                    muted
                    playsInline
                  >
                    Your browser does not support video playback.
                  </video>
                  <LaneOverlay cameraId={analysisCameraId} />
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

          {eventsPage && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">SYSTEM ACTIVITY</div>
                  <h1>Events & alerts</h1>
                  <p>
                    Current camera and processing status from the backend.
                  </p>
                </div>
              </section>

              <div className="notice-card">
                <strong>Live status, not event history</strong>
                <p>
                  This page currently shows camera processing status. A
                  persistent alert history and email or Telegram notification
                  tracking have not been implemented yet.
                </p>
              </div>

              <section className="event-list">
                {cameras.map((camera) => {
                  const id = getCameraId(camera);
                  const result = getResultsForCamera(trafficResults, id);
                  const running = getWorkerRunning(
                    getWorkerForCamera(workerStatus, id)
                  );

                  return (
                    <article className="event-row" key={id}>
                      <div className="event-row__icon">•</div>
                      <div className="event-row__content">
                        <strong>{getCameraName(camera)}</strong>
                        <p>
                          Traffic:{" "}
                          {camera.traffic_enabled ? "enabled" : "disabled"}
                          {"  -  "}
                          Worker:{" "}
                          {running === null
                            ? "status unavailable"
                            : running
                              ? "running"
                              : "stopped"}
                        </p>
                      </div>
                      <div className="event-row__right">
                        <span className="event-row__count">
                          {formatNumber(getVehicleCount(result))} vehicles
                        </span>
                        <button
                          type="button"
                          className="table-action"
                          onClick={() => openCamera(camera)}
                        >
                          Inspect •
                        </button>
                      </div>
                    </article>
                  );
                })}
                {cameras.length === 0 && (
                  <div className="empty-state">
                    No registered camera status is available.
                  </div>
                )}
              </section>
            </>
          )}

          {settingsPage && (
            <>
              <section className="page-heading">
                <div>
                  <div className="eyebrow">CONFIGURATION</div>
                  <h1>Settings</h1>
                  <p>
                    Current application connection and detection module
                    information.
                  </p>
                </div>
              </section>

              <section className="settings-grid">
                <article className="settings-card">
                  <span className="settings-card__eyebrow">
                    BACKEND CONNECTION
                  </span>
                  <h3>FastAPI server</h3>
                  <p>{API}</p>
                  <StatusPill active={!backendError}>
                    {backendError ? "Connection issue" : "Connected"}
                  </StatusPill>
                  <button
                    type="button"
                    className="button button--secondary settings-card__button"
                    onClick={() => fetchData(true)}
                  >
                    Test connection •
                  </button>
                </article>

                <article className="settings-card">
                  <span className="settings-card__eyebrow">
                    DETECTION MODULES
                  </span>
                  <h3>Implementation status</h3>
                  <div className="module-row">
                    <span>Traffic detection</span>
                    <span className="module-state module-state--ready">
                      Configured
                    </span>
                  </div>
                  <div className="module-row">
                    <span>Accident detection</span>
                    <span className="module-state">Not implemented</span>
                  </div>
                  <div className="module-row">
                    <span>Pothole detection</span>
                    <span className="module-state">Not implemented</span>
                  </div>
                  <div className="module-row">
                    <span>Waste detection</span>
                    <span className="module-state">Not implemented</span>
                  </div>
                </article>

                <article className="settings-card">
                  <span className="settings-card__eyebrow">
                    DATA REFRESH
                  </span>
                  <h3>Automatic updates</h3>
                  <p>
                    Camera, worker, and traffic result endpoints are polled
                    every {POLL_INTERVAL / 1000} seconds.
                  </p>
                  <p className="settings-note">
                    Existing lane configuration files are managed by the
                    backend and are not modified by this interface.
                  </p>
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










