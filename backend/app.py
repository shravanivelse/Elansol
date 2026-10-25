"""
Vehicle analytics backend (Flask).

1. Reads the traffic video frame-by-frame with OpenCV.
2. Detects vehicles with a pre-trained YOLO model.
3. Tracks them (ByteTrack) so every vehicle keeps a unique ID.
4. Detects when a vehicle crosses the horizontal center line and crops its box.
5. Finds the dominant color of the crop and logs (ID, color, timestamp) to PostgreSQL
   (falls back to events.log if the database is not reachable).
6. Streams the processed frames as MJPEG at /video_feed.
7. Serves the saved logs as JSON at /api/logs and /api/summary.
"""
import os
import threading
import time
from datetime import datetime

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2
import numpy as np
import psycopg2
from flask import Flask, Response, jsonify
from psycopg2.extras import RealDictCursor
from ultralytics import YOLO

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO_PATH = os.getenv("VIDEO_PATH", os.path.join(HERE, "..", "traffic.mp4"))
VIDEO_SOURCE = os.getenv("VIDEO_SOURCE")
LOG_FILE = os.path.join(HERE, "events.log")
DSN = os.getenv("PG_DSN", "host=localhost port=5432 dbname=vehicles user=sv password=sv_password")

# COCO class ids used by the pre-trained YOLO model
VEHICLES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
JPEG_QUALITY = 98
YOLO_IMAGE_SIZE = 960

app = Flask(__name__)

latest_jpeg = None          # newest processed frame, shared with /video_feed
frame_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Database helpers
# --------------------------------------------------------------------------- #
def db_query(sql, params=None, fetch=True):
    with psycopg2.connect(DSN) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall() if fetch else None


def log_event(vehicle_id, vehicle_type, color, direction):
    """Insert into PostgreSQL; if that fails write to events.log instead."""
    try:
        db_query(
            "INSERT INTO vehicle_events (vehicle_id, vehicle_type, color, direction) "
            "VALUES (%s, %s, %s, %s)",
            (vehicle_id, vehicle_type, color, direction),
            fetch=False,
        )
    except Exception as exc:
        print(f"[db] insert failed ({exc}); writing to {LOG_FILE}")
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()},{vehicle_id},{vehicle_type},{color},{direction}\n")


# --------------------------------------------------------------------------- #
# Dominant color of a vehicle crop
# --------------------------------------------------------------------------- #
def dominant_color(crop):
    h, w = crop.shape[:2]
    if h < 8 or w < 8:
        return "unknown"
    crop = crop[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]          # centre part = body
    small = cv2.resize(crop, (32, 32)).reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(small, 3, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    main = centers[np.bincount(labels.flatten()).argmax()].astype(np.uint8)
    hue, sat, val = cv2.cvtColor(main.reshape(1, 1, 3), cv2.COLOR_BGR2HSV)[0, 0]

    if val < 50:
        return "black"
    if sat < 40:
        return "white" if val > 170 else "gray"
    if hue < 10 or hue >= 170:
        return "red"
    if hue < 22:
        return "orange"
    if hue < 35:
        return "yellow"
    if hue < 85:
        return "green"
    if hue < 130:
        return "blue"
    return "purple"


# --------------------------------------------------------------------------- #
# Video processing loop (runs in a background thread)
# --------------------------------------------------------------------------- #
def process_video():
    global latest_jpeg
    model = YOLO("yolov8n.pt")              # downloaded automatically the first time
    video_input = VIDEO_SOURCE or VIDEO_PATH
    print(f"Video input: {video_input}")

    while True:
        capture_api = cv2.CAP_FFMPEG if VIDEO_SOURCE else cv2.CAP_ANY
        cap = cv2.VideoCapture(video_input, capture_api)
        if not cap.isOpened():
            print(f"Cannot open video source: {video_input}")
            time.sleep(3)
            continue
        if VIDEO_SOURCE:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        last_cy = {}                        # tracker id -> previous centre y
        counted = set()                     # (tracker id, direction) already logged
        delay = 1.0 / (25 if VIDEO_SOURCE else (cap.get(cv2.CAP_PROP_FPS) or 25))

        while True:
            started = time.time()
            ok, frame = cap.read()
            if not ok:
                break                       # end of input -> reopen and loop

            line_y = frame.shape[0] // 2    # predefined centre line
            result = model.track(
                frame, persist=True, classes=list(VEHICLES), tracker="bytetrack.yaml",
                imgsz=YOLO_IMAGE_SIZE, verbose=False
            )[0]

            if result.boxes.id is not None:
                ids = result.boxes.id.int().tolist()
                classes = result.boxes.cls.int().tolist()
                boxes = result.boxes.xyxy.int().tolist()

                for tid, cls, (x1, y1, x2, y2) in zip(ids, classes, boxes):
                    x1, y1 = max(x1, 0), max(y1, 0)
                    cy = (y1 + y2) // 2
                    prev = last_cy.get(tid)
                    last_cy[tid] = cy

                    direction = None
                    if prev is not None:
                        if prev < line_y <= cy:
                            direction = "IN"
                        elif prev >= line_y > cy:
                            direction = "OUT"

                    if direction and (tid, direction) not in counted:
                        counted.add((tid, direction))
                        crop = frame[y1:y2, x1:x2]                  # extracted bounding box
                        color = dominant_color(crop)
                        log_event(tid, VEHICLES[cls], color, direction)
                        print(f"counted id={tid} {VEHICLES[cls]} {color} {direction}")

                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f"#{tid} {VEHICLES[cls]}", (x1, max(y1 - 6, 12)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            cv2.line(frame, (0, line_y), (frame.shape[1], line_y), (0, 0, 255), 2)
            ok, jpg = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
            )
            if ok:
                with frame_lock:
                    latest_jpeg = jpg.tobytes()

            time.sleep(max(0, delay - (time.time() - started)))     # keep real-time speed

        cap.release()
        if VIDEO_SOURCE:
            time.sleep(1)


# --------------------------------------------------------------------------- #
# Flask routes
# --------------------------------------------------------------------------- #
def mjpeg_generator():
    while True:
        with frame_lock:
            jpg = latest_jpeg
        if jpg is None:
            time.sleep(0.1)
            continue
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
        time.sleep(0.03)


@app.route("/video_feed")
def video_feed():
    return Response(mjpeg_generator(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/logs")
def logs():
    try:
        rows = db_query(
            "SELECT id, vehicle_id, vehicle_type, color, direction, ts "
            "FROM vehicle_events ORDER BY ts DESC LIMIT 50"
        )
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/summary")
def summary():
    try:
        total = db_query("SELECT count(*)::int AS n FROM vehicle_events")[0]["n"]
        colors = db_query(
            "SELECT color, count(*)::int AS n FROM vehicle_events GROUP BY color ORDER BY n DESC"
        )
        return jsonify({"total": total, "byColor": colors})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    threading.Thread(target=process_video, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
