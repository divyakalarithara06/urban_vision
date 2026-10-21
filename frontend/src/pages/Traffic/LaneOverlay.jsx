import { useEffect, useState } from "react";
import "./LaneOverlay.css";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const LANE_COLORS = ["#38bdf8", "#34d399", "#fbbf24", "#c084fc", "#fb7185"];

export default function LaneOverlay({ cameraId }) {
  const [lanes, setLanes] = useState(null);
  const [dimensions, setDimensions] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const video = document.querySelector(".lane-overlay-container video");

    setLanes(null);
    setDimensions(null);
    setError("");

    const updateDimensions = () => {
      if (video?.videoWidth > 0 && video?.videoHeight > 0 && !cancelled) {
        setDimensions({
          width: video.videoWidth,
          height: video.videoHeight,
        });
      }
    };

    video?.addEventListener("loadedmetadata", updateDimensions);
    updateDimensions();

    if (!cameraId) {
      setError("Select a camera to view its lane boundaries.");
      return () => {
        cancelled = true;
        video?.removeEventListener("loadedmetadata", updateDimensions);
      };
    }

    fetch(`${API}/traffic/cameras/${cameraId}/lanes`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Could not load saved lanes (HTTP ${response.status}).`);
        }
        return response.json();
      })
      .then((payload) => {
        if (cancelled) return;
        if (!payload || typeof payload.lanes !== "object" || payload.lanes === null) {
          throw new Error("The backend returned an invalid lane configuration.");
        }
        setLanes(payload.lanes);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Could not load lane boundaries.");
      });

    return () => {
      cancelled = true;
      video?.removeEventListener("loadedmetadata", updateDimensions);
    };
  }, [cameraId]);

  if (error) return <div className="lane-overlay-message">{error}</div>;
  if (!lanes || !dimensions) {
    return <div className="lane-overlay-message">Loading saved lane boundaries…</div>;
  }

  const entries = Object.entries(lanes);

  if (entries.length === 0) {
    return <div className="lane-overlay-message">No lanes saved for this camera yet.</div>;
  }

  return (
    <svg
      className="lane-overlay-svg"
      viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
      preserveAspectRatio="none"
      aria-label="Saved traffic lane boundaries"
    >
      {entries.map(([name, points], index) => {
        if (!Array.isArray(points) || points.length < 3) return null;

        const pointString = points.map(([x, y]) => `${x},${y}`).join(" ");
        const center = points.reduce(
          (sum, [x, y]) => ({
            x: sum.x + x / points.length,
            y: sum.y + y / points.length,
          }),
          { x: 0, y: 0 }
        );
        const color = LANE_COLORS[index % LANE_COLORS.length];

        return (
          <g key={name}>
            <polygon
              points={pointString}
              fill={color}
              fillOpacity="0.12"
              stroke={color}
              strokeWidth="4"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
            <g transform={`translate(${center.x}, ${center.y})`}>
              <rect
                x="-42"
                y="-17"
                width="84"
                height="34"
                rx="8"
                fill="#0f172a"
                fillOpacity="0.92"
              />
              <text
                textAnchor="middle"
                dominantBaseline="central"
                fill="#ffffff"
                fontSize="22"
                fontWeight="700"
              >
                {name.replace("_", " ")}
              </text>
            </g>
          </g>
        );
      })}
    </svg>
  );
}
