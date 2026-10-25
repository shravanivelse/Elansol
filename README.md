# Real-Time Vehicle Analytics (OpenCV + YOLO + Flask + React)

```
traffic.mp4 → OpenCV → YOLO detect → ByteTrack IDs → center-line crossing
            → crop + dominant color → PostgreSQL → Flask (/video_feed, /api/logs) → React dashboard
```

```
sv/
├── traffic.mp4          sample video (keep it in this folder)
├── db/init.sql          vehicle_events table
├── backend/app.py       Flask + full vision pipeline
├── backend/requirements.txt
└── frontend/            React dashboard (live stream + logs table)
```

## Prerequisites
Python 3.9+, Node.js, and PostgreSQL. MediaMTX and FFmpeg are only needed if you
choose the optional RTSP streaming setup below.

## Setup (once, from `sv`)
```
psql -U postgres -c "CREATE USER sv WITH PASSWORD 'sv_password';"
psql -U postgres -c "CREATE DATABASE vehicles OWNER sv;"
psql -U sv -d vehicles -f db\init.sql

cd .\backend
py -3.11 -m pip install -r requirements.txt
cd ..\frontend
npm install
```

## Run the demo directly from `traffic.mp4` (two VS Code terminals)

Keep `traffic.mp4` in the `sv` folder. The backend's default `VIDEO_PATH`
points to this file, so it reads and processes the original video directly
without publishing or re-encoding it through MediaMTX.

Open terminals in the `sv` folder and start each command in its own terminal:

1. Start the backend:
   ```
   cd .\backend
   Remove-Item Env:VIDEO_SOURCE -ErrorAction SilentlyContinue
   py -3.11 app.py
   ```
2. Start the frontend:
   ```
   cd .\frontend
   npm run dev
   ```

Open http://localhost:5173. The backend processes frames from the original file,
draws detections and the counting line, and serves the annotated frames to the
dashboard as MJPEG at `/video_feed`. The output cannot be sharper than the
original video; direct input avoids the extra H.264 re-encoding step used by
the optional RTSP workflow. YOLO uses a 960-pixel inference size and the
backend encodes output frames at JPEG quality 98.

If PostgreSQL is not reachable, events are written to `backend/events.log` instead.
Set another database with the `PG_DSN` environment variable.

To process a different local video, set `VIDEO_PATH` to its full path before
starting the backend. For example, from `sv\backend` in PowerShell:

```
$env:VIDEO_PATH = "C:\videos\traffic.mp4"
py -3.11 app.py
```

## Optional: Run through MediaMTX (RTSP)

Use this mode only when you need to simulate a camera/RTSP input. It requires
MediaMTX and FFmpeg and re-encodes the video before the backend receives it, so
it is not the recommended mode for the clearest local-file demo.

1. Start MediaMTX with its configuration.
2. Publish the file with FFmpeg:
   ```
   ffmpeg -re -stream_loop -1 -i .\traffic.mp4 -an -c:v libx264 -preset medium -crf 16 -tune zerolatency -pix_fmt yuv420p -f rtsp -rtsp_transport tcp rtsp://localhost:8554/traffic
   ```
3. In a separate backend terminal, set the RTSP source and start Flask:
   ```
   cd .\backend
   $env:VIDEO_SOURCE = "rtsp://localhost:8554/traffic"
   py -3.11 app.py
   ```
4. Start the frontend as above.
