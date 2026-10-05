import { useEffect, useRef, useState } from "react";
import "./App.css";

const cameras = ["Camera 01", "Camera 02", "Camera 03", "Camera 04"];

const modules = [
  {
    icon: "🚗",
    title: "Traffic Monitoring",
    description:
      "Vehicle detection, lane density and adaptive signal control.",
    status: "Active",
    active: true,
  },
  {
    icon: "🚨",
    title: "Accident Detection",
    description:
      "AI-powered detection and monitoring of road accidents.",
    status: "Coming Soon",
    active: false,
  },
  {
    icon: "🗑️",
    title: "Waste Detection",
    description:
      "Detection and monitoring of waste in public areas.",
    status: "Coming Soon",
    active: false,
  },
  {
    icon: "🕳️",
    title: "Pothole Detection",
    description:
      "Detection and monitoring of potholes and road conditions.",
    status: "Coming Soon",
    active: false,
  },
];

function App() {
  const [darkMode, setDarkMode] = useState(true);
  const [activePage, setActivePage] = useState("overview");

  const [selectedCamera, setSelectedCamera] = useState("Camera 01");
  const [videoFile, setVideoFile] = useState(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [monitoring, setMonitoring] = useState(false);

  const [laneConfiguring, setLaneConfiguring] = useState(false);
  const [activeLane, setActiveLane] = useState(1);
  const [lanePoints, setLanePoints] = useState({});
  const [lanes, setLanes] = useState([]);

  const fileInputRef = useRef(null);
  const videoRef = useRef(null);

  const handleNavigation = (page) => {
    if (page === "overview" || page === "traffic") {
      setActivePage(page);
    }
  };

  const handleVideoSelect = (event) => {
    const file = event.target.files?.[0];

    if (!file) return;

    if (videoUrl) {
      URL.revokeObjectURL(videoUrl);
    }

    const url = URL.createObjectURL(file);

    setVideoFile(file);
    setVideoUrl(url);
    setMonitoring(false);
    setLaneConfiguring(false);
    setLanePoints({});
    setLanes([]);
  };

  useEffect(() => {
    return () => {
      if (videoUrl) {
        URL.revokeObjectURL(videoUrl);
      }
    };
  }, [videoUrl]);

  const handleVideoClick = (event) => {
    if (!laneConfiguring || !videoRef.current) return;

    const rect = videoRef.current.getBoundingClientRect();

    const x = ((event.clientX - rect.left) / rect.width) * 100;
    const y = ((event.clientY - rect.top) / rect.height) * 100;

    setLanePoints((previous) => ({
      ...previous,
      [activeLane]: [
        ...(previous[activeLane] || []),
        { x, y },
      ],
    }));
  };

  const finishCurrentLane = () => {
    const points = lanePoints[activeLane] || [];

    if (points.length < 3) {
      alert("A lane needs at least 3 points.");
      return;
    }

    setLanes((previous) => {
      const filtered = previous.filter(
        (lane) => lane.id !== activeLane
      );

      return [
        ...filtered,
        {
          id: activeLane,
          points,
        },
      ].sort((a, b) => a.id - b.id);
    });

    setLaneConfiguring(false);
  };

  const startLaneConfiguration = (laneNumber) => {
    if (!videoFile) {
      alert("Select a traffic video first.");
      return;
    }

    setActiveLane(laneNumber);
    setLaneConfiguring(true);

    setLanePoints((previous) => ({
      ...previous,
      [laneNumber]: [],
    }));
  };

  const clearLane = (laneNumber) => {
    setLanePoints((previous) => {
      const updated = { ...previous };
      delete updated[laneNumber];
      return updated;
    });

    setLanes((previous) =>
      previous.filter((lane) => lane.id !== laneNumber)
    );
  };

  const startMonitoring = () => {
    if (!videoFile) {
      alert("Select a traffic video first.");
      return;
    }

    setMonitoring(true);

    if (videoRef.current) {
      videoRef.current.play();
    }
  };

  const stopMonitoring = () => {
    setMonitoring(false);

    if (videoRef.current) {
      videoRef.current.pause();
    }
  };

  const getLanePoints = (laneId) => {
    return lanePoints[laneId] || [];
  };

  const polygonPoints = (points) =>
    points.map((point) => `${point.x},${point.y}`).join(" ");

  return (
    <div className={`app ${darkMode ? "dark-mode" : "light-mode"}`}>
      {/* SIDEBAR */}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">UV</div>

          <div className="brand-text">
            <h1>UrbanVision</h1>
            <p>Smart City Intelligence</p>
          </div>
        </div>

        <nav className="navigation">
          <p className="nav-label">MONITORING</p>

          <button
            className={`nav-item ${
              activePage === "overview" ? "active" : ""
            }`}
            onClick={() => handleNavigation("overview")}
          >
            <span className="nav-icon">⌂</span>
            <span>Overview</span>
          </button>

          <button
            className={`nav-item ${
              activePage === "traffic" ? "active" : ""
            }`}
            onClick={() => handleNavigation("traffic")}
          >
            <span className="nav-icon">🚗</span>
            <span>Traffic</span>
          </button>

          <button className="nav-item disabled-nav">
            <span className="nav-icon">🚨</span>
            <span>Accident</span>
          </button>

          <button className="nav-item disabled-nav">
            <span className="nav-icon">🗑️</span>
            <span>Waste</span>
          </button>

          <button className="nav-item disabled-nav">
            <span className="nav-icon">🕳️</span>
            <span>Pothole</span>
          </button>

          <p className="nav-label bottom-label">SYSTEM</p>

          <button className="nav-item disabled-nav">
            <span className="nav-icon">⚙</span>
            <span>Settings</span>
          </button>
        </nav>
      </aside>

      {/* MAIN */}
      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="breadcrumb">
              URBANVISION /{" "}
              {activePage === "overview" ? "OVERVIEW" : "TRAFFIC"}
            </p>

            <h2>
              {activePage === "overview"
                ? "City Overview"
                : "Traffic Monitoring"}
            </h2>
          </div>

          <div className="topbar-actions">
            <div className="system-status">
              <span className="status-dot"></span>
              SYSTEM ONLINE
            </div>

            <button
              className="theme-toggle"
              onClick={() => setDarkMode(!darkMode)}
            >
              {darkMode ? "☀️" : "🌙"}
            </button>
          </div>
        </header>

        {/* ================= OVERVIEW ================= */}

        {activePage === "overview" && (
          <>
            <section className="welcome">
              <div className="welcome-content">
                <p className="eyebrow">SMART CITY MONITORING</p>

                <h3>Welcome to UrbanVision</h3>

                <p>
                  A unified platform for intelligent monitoring of
                  urban environments using computer vision.
                </p>
              </div>

              <div className="welcome-decoration">
                <div className="pulse-ring"></div>
                <div className="pulse-core"></div>
              </div>
            </section>

            <section className="section">
              <div className="section-heading">
                <div>
                  <h3>Monitoring Systems</h3>
                </div>

                <span className="module-count">1 of 4 active</span>
              </div>

              <div className="module-grid">
                {modules.map((module) => (
                  <div
                    className={`module-card ${
                      module.active ? "module-active" : ""
                    }`}
                    key={module.title}
                  >
                    <div className="module-top">
                      <div className="module-icon">
                        {module.icon}
                      </div>

                      <span
                        className={`module-status ${
                          module.active
                            ? "status-active"
                            : "status-soon"
                        }`}
                      >
                        {module.status}
                      </span>
                    </div>

                    <h4>{module.title}</h4>

                    <p>{module.description}</p>

                    {module.active ? (
                      <button
                        className="open-module"
                        onClick={() =>
                          handleNavigation("traffic")
                        }
                      >
                        Open Module
                        <span>→</span>
                      </button>
                    ) : (
                      <span className="disabled-module">
                        Module in development
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </section>

            <section className="monitor-card">
              <div className="card-header">
                <div>
                  <p className="eyebrow">LIVE MONITORING</p>
                  <h3>City Camera Network</h3>
                </div>

                <span className="live-badge">
                  <span className="status-dot"></span>
                  LIVE
                </span>
              </div>

              <div className="camera-placeholder">
                <div className="camera-grid"></div>

                <div className="camera-content">
                  <div className="camera-icon">◉</div>
                  <h4>Monitoring Feed</h4>
                  <p>
                    Live camera integration will appear here.
                  </p>
                </div>
              </div>
            </section>
          </>
        )}

        {/* ================= TRAFFIC ================= */}

        {activePage === "traffic" && (
          <div className="traffic-page">
            {/* SOURCE BAR */}
            <section className="traffic-source-card">
              <div className="source-title">
                <div>
                  <p className="eyebrow">INPUT SOURCE</p>
                  <h3>Traffic Feed</h3>
                </div>

                <span className="source-status">
                  <span className="status-dot"></span>
                  {videoFile ? "VIDEO LOADED" : "NO SOURCE"}
                </span>
              </div>

              <div className="source-controls">
                <div className="source-control">
                  <label>CAMERA</label>

                  <select
                    value={selectedCamera}
                    onChange={(event) =>
                      setSelectedCamera(event.target.value)
                    }
                  >
                    {cameras.map((camera) => (
                      <option key={camera} value={camera}>
                        {camera}
                      </option>
                    ))}
                  </select>
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept="video/*"
                  onChange={handleVideoSelect}
                  hidden
                />

                <button
                  className="control-button primary-control"
                  onClick={() =>
                    fileInputRef.current?.click()
                  }
                >
                  + Select Video
                </button>

                <div className="source-file">
                  <span>FILE</span>
                  <strong>
                    {videoFile
                      ? videoFile.name
                      : "No footage selected"}
                  </strong>
                </div>
              </div>
            </section>

            {/* MAIN OPERATOR GRID */}
            <section className="operator-grid">
              {/* VIDEO */}
              <div className="video-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">CAMERA FEED</p>
                    <h3>
                      {selectedCamera} — Traffic View
                    </h3>
                  </div>

                  <div
                    className={`monitor-state ${
                      monitoring ? "monitoring" : ""
                    }`}
                  >
                    <span className="status-dot"></span>
                    {monitoring ? "MONITORING" : "READY"}
                  </div>
                </div>

                <div
                  className={`video-stage ${
                    laneConfiguring ? "drawing-mode" : ""
                  }`}
                  onClick={handleVideoClick}
                >
                  {!videoUrl ? (
                    <div className="empty-video">
                      <div className="empty-video-icon">
                        ▶
                      </div>

                      <h4>No Traffic Footage</h4>

                      <p>
                        Select a video source above to begin.
                      </p>

                      <button
                        className="control-button primary-control"
                        onClick={(event) => {
                          event.stopPropagation();
                          fileInputRef.current?.click();
                        }}
                      >
                        Select Video
                      </button>
                    </div>
                  ) : (
                    <video
                      ref={videoRef}
                      src={videoUrl}
                      className="real-video"
                      controls={!laneConfiguring}
                      muted
                      playsInline
                    />
                  )}

                  {videoUrl && (
                    <div className="video-hud">
                      <span>URBANVISION</span>
                      <span>{selectedCamera}</span>
                    </div>
                  )}

                  {laneConfiguring && (
                    <div className="drawing-banner">
                      <strong>
                        DRAWING LANE {activeLane}
                      </strong>
                      <span>
                        Click at least 3 points on the road
                      </span>
                    </div>
                  )}

                  {videoUrl && (
                    <svg className="lane-overlay">
                      {lanes.map((lane) => (
                        <polygon
                          key={lane.id}
                          points={polygonPoints(lane.points)}
                          vectorEffect="non-scaling-stroke"
                          className={`lane-shape lane-shape-${lane.id}`}
                        />
                      ))}

                      {(lanePoints[activeLane] || []).length >=
                        2 &&
                        laneConfiguring && (
                          <polyline
                            points={polygonPoints(
                              getLanePoints(activeLane)
                            )}
                            vectorEffect="non-scaling-stroke"
                            className="lane-drawing-line"
                          />
                        )}
                    </svg>
                  )}

                  {videoUrl &&
                    laneConfiguring &&
                    getLanePoints(activeLane).map(
                      (point, index) => (
                        <div
                          key={index}
                          className="draw-point"
                          style={{
                            left: `${point.x}%`,
                            top: `${point.y}%`,
                          }}
                        >
                          {index + 1}
                        </div>
                      )
                    )}

                  {monitoring && videoUrl && (
                    <>
                      <div className="detection-box detection-one">
                        <span>vehicle 0.92</span>
                      </div>

                      <div className="detection-box detection-two">
                        <span>vehicle 0.87</span>
                      </div>

                      <div className="detection-box detection-three">
                        <span>vehicle 0.81</span>
                      </div>
                    </>
                  )}
                </div>

                <div className="video-footer">
                  <div className="video-metadata">
                    <span>
                      {videoFile
                        ? "LOCAL VIDEO"
                        : "NO VIDEO"}
                    </span>

                    <span>1280 × 720</span>

                    <span>{lanes.length} LANES</span>
                  </div>

                  <button
                    className={`control-button ${
                      monitoring
                        ? "danger-control"
                        : "primary-control"
                    }`}
                    onClick={
                      monitoring
                        ? stopMonitoring
                        : startMonitoring
                    }
                  >
                    {monitoring
                      ? "■ Stop Monitoring"
                      : "▶ Start Monitoring"}
                  </button>
                </div>
              </div>

              {/* RIGHT OPERATIONS PANEL */}
              <aside className="operations-panel">
                {/* TRAFFIC STATUS */}
                <div className="operation-section">
                  <div className="operation-heading">
                    <div>
                      <p className="eyebrow">LIVE ANALYSIS</p>
                      <h3>Traffic Status</h3>
                    </div>

                    <span
                      className={`analysis-badge ${
                        monitoring ? "active" : ""
                      }`}
                    >
                      {monitoring ? "ACTIVE" : "IDLE"}
                    </span>
                  </div>

                  <div className="metric-grid">
                    <div className="metric-box">
                      <span>VEHICLES</span>
                      <strong>
                        {monitoring ? "12" : "—"}
                      </strong>
                    </div>

                    <div className="metric-box">
                      <span>DENSITY</span>
                      <strong>
                        {monitoring ? "42%" : "—"}
                      </strong>
                    </div>
                  </div>

                  <div className="current-lane">
                    <span>CURRENT PRIORITY</span>
                    <strong>
                      {monitoring ? "LANE 2" : "—"}
                    </strong>
                  </div>
                </div>

                {/* LANES */}
                <div className="operation-section lane-section">
                  <div className="operation-heading">
                    <div>
                      <p className="eyebrow">ROAD CONFIGURATION</p>
                      <h3>Lane Setup</h3>
                    </div>

                    <span className="lane-count">
                      {lanes.length}/4
                    </span>
                  </div>

                  <p className="lane-help">
                    Select a lane, then click points on the
                    video to define its boundary.
                  </p>

                  <div className="lane-list">
                    {[1, 2, 3, 4].map((laneNumber) => {
                      const configured = lanes.some(
                        (lane) => lane.id === laneNumber
                      );

                      const drawing =
                        laneConfiguring &&
                        activeLane === laneNumber;

                      return (
                        <div
                          className={`lane-item ${
                            drawing ? "selected" : ""
                          } ${
                            configured ? "configured" : ""
                          }`}
                          key={laneNumber}
                        >
                          <div className="lane-number">
                            {laneNumber}
                          </div>

                          <div className="lane-info">
                            <strong>
                              Lane {laneNumber}
                            </strong>

                            <span>
                              {configured
                                ? "Configured"
                                : drawing
                                  ? "Drawing..."
                                  : "Not configured"}
                            </span>
                          </div>

                          {configured ? (
                            <button
                              className="lane-action"
                              onClick={() =>
                                clearLane(laneNumber)
                              }
                            >
                              Clear
                            </button>
                          ) : (
                            <button
                              className="lane-action"
                              onClick={() =>
                                startLaneConfiguration(
                                  laneNumber
                                )
                              }
                            >
                              Configure
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {laneConfiguring && (
                    <button
                      className="finish-lane-button"
                      onClick={finishCurrentLane}
                    >
                      ✓ Save Lane {activeLane}
                    </button>
                  )}
                </div>
              </aside>
            </section>

            {/* SIGNAL CONTROL */}
            <section className="signal-panel">
              <div className="signal-panel-title">
                <div>
                  <p className="eyebrow">ADAPTIVE SIGNAL CONTROL</p>
                  <h3>Current Traffic Signal</h3>
                </div>

                <span className="automatic-badge">
                  {monitoring ? "AUTOMATIC" : "WAITING"}
                </span>
              </div>

              <div className="signal-dashboard">
                <div className="traffic-light">
                  <div className="light red-light"></div>
                  <div className="light yellow-light"></div>
                  <div className="light green-light active-light"></div>
                </div>

                <div className="signal-value">
                  <span>ACTIVE LANE</span>
                  <strong>
                    {monitoring ? "LANE 2" : "—"}
                  </strong>
                </div>

                <div className="signal-value">
                  <span>SIGNAL STATE</span>
                  <strong className="green-text">
                    {monitoring ? "GREEN" : "—"}
                  </strong>
                </div>

                <div className="signal-value">
                  <span>GREEN TIME</span>
                  <strong>
                    {monitoring ? "06s" : "—"}
                  </strong>
                </div>

                <div className="signal-value">
                  <span>NEXT EVALUATION</span>
                  <strong>
                    {monitoring ? "02s" : "—"}
                  </strong>
                </div>
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;