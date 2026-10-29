import { useEffect, useRef, useState } from "react";
import "./LaneEditor.css";

const API = "http://127.0.0.1:8000";

const COLORS = ["#38bdf8", "#34d399", "#fbbf24", "#c084fc", "#fb7185"];

export default function LaneEditor({ cameraId, cameraName, onClose, onSaved }) {
  const videoRef = useRef(null);
  const stageRef = useRef(null);
  const [lanes, setLanes] = useState({});
  const [draft, setDraft] = useState([]);
  const [laneName, setLaneName] = useState("Lane_1");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [videoSize, setVideoSize] = useState(null);

  const dimensions = videoSize;

  useEffect(() => {
    let cancelled = false;

    async function loadLanes() {
      setLoading(true);
      setError("");
      try {
        const response = await fetch(`${API}/traffic/cameras/${cameraId}/lanes`);
        if (!response.ok) throw new Error("Could not load saved lane configuration.");
        const payload = await response.json();
        if (!cancelled) {
          setLanes(payload.lanes || {});
          setLaneName(nextLaneName(payload.lanes || {}));
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadLanes();
    return () => { cancelled = true; };
  }, [cameraId]);

  function nextLaneName(existing) {
    let index = 1;
    while (existing[`Lane_${index}`]) index += 1;
    return `Lane_${index}`;
  }

  function handleVideoMetadata() {
    const video = videoRef.current;
    if (video?.videoWidth && video?.videoHeight) {
      setVideoSize({ width: video.videoWidth, height: video.videoHeight });
    }
  }

  function addPoint(event) {
    if (!dimensions || !stageRef.current) return;
    const rect = stageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    const x = Math.max(0, Math.min(dimensions.width,
      ((event.clientX - rect.left) / rect.width) * dimensions.width));
    const y = Math.max(0, Math.min(dimensions.height,
      ((event.clientY - rect.top) / rect.height) * dimensions.height));

    setDraft((current) => [...current, [
      Number(x.toFixed(2)), Number(y.toFixed(2))
    ]]);
    setMessage("");
  }

  function finishLane() {
    if (draft.length < 3) {
      setError("A lane needs at least three points.");
      return;
    }
    const name = laneName.trim();
    if (!name) {
      setError("Enter a lane name.");
      return;
    }
    if (lanes[name]) {
      setError(`${name} already exists. Choose another name to avoid replacing it accidentally.`);
      return;
    }

    setLanes((current) => ({ ...current, [name]: draft }));
    setDraft([]);
    setLaneName(nextLaneName({ ...lanes, [name]: true }));
    setError("");
    setMessage(`${name} added. Save changes to store it.`);
  }

  function removeLane(name) {
    setLanes((current) => {
      const updated = { ...current };
      delete updated[name];
      return updated;
    });
    setMessage(`${name} removed from the pending changes. Save to confirm.`);
  }

  async function saveLanes() {
    setSaving(true);
    setError("");
    setMessage("");

    try {
      if (draft.length > 0) {
        throw new Error("Finish or clear the lane currently being drawn before saving.");
      }
      if (Object.values(lanes).some((points) => !Array.isArray(points) || points.length < 3)) {
        throw new Error("Every lane must have at least three points.");
      }

      const response = await fetch(`${API}/traffic/cameras/${cameraId}/lanes`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lanes }),
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || "Could not save lane configuration.");
      }

      setMessage("Lane configuration saved successfully.");
      if (onSaved) onSaved(cameraId, lanes);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const allLanes = Object.entries(lanes);

  return (
    <section className="lane-editor">
      <header className="lane-editor__header">
        <div>
          <span className="lane-editor__eyebrow">LANE CONFIGURATION</span>
          <h2>{cameraName || `Camera ${cameraId}`}</h2>
          <p>Click the video to mark lane corners in order. Use at least three points per lane.</p>
        </div>
        <button type="button" className="lane-editor__button lane-editor__button--quiet" onClick={onClose}>
          Cancel
        </button>
      </header>

      {error && <div className="lane-editor__notice lane-editor__notice--error">{error}</div>}
      {message && <div className="lane-editor__notice">{message}</div>}

      {loading ? (
        <div className="lane-editor__loading">Loading saved configuration…</div>
      ) : (
        <>
          <div className="lane-editor__workspace">
            <div className="lane-editor__video-column">
              <div className="lane-editor__stage" ref={stageRef} onClick={addPoint}>
                <video
                  ref={videoRef}
                  key={cameraId}
                  src={`${API}/cameras/${cameraId}/video`}
                  controls
                  muted
                  playsInline
                  onLoadedMetadata={handleVideoMetadata}
                />
                {dimensions && (
                <svg
                  className="lane-editor__svg"
                  viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
                  preserveAspectRatio="none"
                >
                  {allLanes.map(([name, points], index) => {
                    const color = COLORS[index % COLORS.length];
                    const center = points.reduce(
                      (sum, point) => ({ x: sum.x + point[0] / points.length, y: sum.y + point[1] / points.length }),
                      { x: 0, y: 0 }
                    );
                    return (
                      <g key={name}>
                        <polygon
                          points={points.map(([x, y]) => `${x},${y}`).join(" ")}
                          fill={color}
                          fillOpacity="0.15"
                          stroke={color}
                          strokeWidth="4"
                          vectorEffect="non-scaling-stroke"
                        />
                        {points.map(([x, y], pointIndex) => (
                          <circle key={pointIndex} cx={x} cy={y} r="6" fill={color} />
                        ))}
                        <text x={center.x} y={center.y} fill="white" fontSize="24" textAnchor="middle">
                          {name.replace("_", " ")}
                        </text>
                      </g>
                    );
                  })}
                  {draft.length > 0 && (
                    <g>
                      <polyline
                        points={draft.map(([x, y]) => `${x},${y}`).join(" ")}
                        fill="none"
                        stroke="#ffffff"
                        strokeWidth="3"
                        strokeDasharray="7 5"
                        vectorEffect="non-scaling-stroke"
                      />
                      {draft.map(([x, y], index) => (
                        <circle key={index} cx={x} cy={y} r="6" fill="#ffffff" />
                      ))}
                    </g>
                  )}
                </svg>
                )}
              </div>
              <p className="lane-editor__hint">
                Pause the video if needed, then click each lane corner clockwise. Existing lanes remain visible while you edit.
              </p>
              {videoSize && (
                <p className="lane-editor__hint">
                  Video resolution: {videoSize.width} × {videoSize.height}
                </p>
              )}
            </div>

            <aside className="lane-editor__sidebar">
              <h3>Draw a lane</h3>
              <label className="lane-editor__label">
                Lane name
                <input value={laneName} onChange={(event) => setLaneName(event.target.value)} />
              </label>
              <p className="lane-editor__point-count">{draft.length} point(s) marked</p>
              <div className="lane-editor__actions">
                <button type="button" className="lane-editor__button" onClick={() => setDraft((current) => current.slice(0, -1))} disabled={!draft.length}>
                  Undo point
                </button>
                <button type="button" className="lane-editor__button" onClick={() => setDraft([])} disabled={!draft.length}>
                  Clear current
                </button>
                <button type="button" className="lane-editor__button lane-editor__button--primary" onClick={finishLane} disabled={draft.length < 3}>
                  Finish lane
                </button>
              </div>

              <h3>Saved / pending lanes ({allLanes.length})</h3>
              {allLanes.length === 0 ? (
                <p className="lane-editor__empty">No lanes loaded. Draw your first lane.</p>
              ) : (
                <ul className="lane-editor__list">
                  {allLanes.map(([name, points], index) => (
                    <li key={name}>
                      <span>
                        <i style={{ background: COLORS[index % COLORS.length] }} />
                        <span>{name}<small>{points.length} points</small></span>
                      </span>
                      <button type="button" onClick={() => removeLane(name)}>Remove</button>
                    </li>
                  ))}
                </ul>
              )}

              <button
                type="button"
                className="lane-editor__button lane-editor__button--primary lane-editor__save"
                onClick={saveLanes}
                disabled={saving || loading}
              >
                {saving ? "Saving…" : "Save configuration"}
              </button>
              <p className="lane-editor__hint">
                Saving updates only this camera’s lane JSON file.
              </p>
            </aside>
          </div>
        </>
      )}
    </section>
  );
}



