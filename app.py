"""
app.py - Main Flask Application for AI CCTV Surveillance System
"""

import os
import cv2
import time
import threading
from datetime import datetime
from flask import Flask, render_template, Response, jsonify

from detector import PersonDetector
from alert import AlertManager

# ---------------------------------------------------------------------------
# Flask Application Setup
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", static_url_path="/static")

# Serve snapshots directory
from flask import send_from_directory

@app.route("/snapshots/<filename>")
def serve_snapshot(filename):
    return send_from_directory("snapshots", filename)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VIDEO_SOURCE = os.getenv("VIDEO_SOURCE", "test.mp4")
VIDEO_SOURCE = int(VIDEO_SOURCE) if VIDEO_SOURCE.isdigit() else VIDEO_SOURCE

# Small restricted zone right at the shutter entrance (848×478 frame)
# Tight area: only the ground directly in front of the shutter door
DEFAULT_ZONE = [(600, 280), (848, 280), (848, 478), (600, 478)]

# ---------------------------------------------------------------------------
# Global State
# ---------------------------------------------------------------------------
current_frame = None
alert_active = False
event_log = []
system_running = True
fps_display = 0
detector_ready = False

frame_lock = threading.Lock()
log_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Initialize Components
# ---------------------------------------------------------------------------
alert_manager = AlertManager(cooldown_seconds=20, snapshots_dir="snapshots")

detector = None


def add_event(message, event_type="info"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event = {"timestamp": timestamp, "message": message, "type": event_type}
    with log_lock:
        event_log.insert(0, event)
        if len(event_log) > 100:
            event_log.pop()


import os
import cv2
import time
import threading
import queue
from datetime import datetime
from flask import Flask, render_template, Response, jsonify

from detector import PersonDetector
from alert import AlertManager

# ---------------------------------------------------------------------------
# Flask Application Setup
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", static_url_path="/static")

# Serve snapshots directory
from flask import send_from_directory

@app.route("/snapshots/<filename>")
def serve_snapshot(filename):
    return send_from_directory("snapshots", filename)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VIDEO_SOURCE = os.getenv("VIDEO_SOURCE", "test.mp4")
VIDEO_SOURCE = int(VIDEO_SOURCE) if VIDEO_SOURCE.isdigit() else VIDEO_SOURCE

# Small restricted zone right at the shutter entrance (848×478 frame)
# Tight area: only the ground directly in front of the shutter door
DEFAULT_ZONE = [(600, 280), (848, 280), (848, 478), (600, 478)]

# ---------------------------------------------------------------------------
# Global State
# ---------------------------------------------------------------------------
current_frame = None
alert_active = False
event_log = []
system_running = True
fps_display = 0
detector_ready = False

frame_lock = threading.Lock()
log_lock = threading.Lock()
recording_queue = queue.Queue(maxsize=100)

# ---------------------------------------------------------------------------
# Initialize Components
# ---------------------------------------------------------------------------
alert_manager = AlertManager(cooldown_seconds=20, snapshots_dir="snapshots")

detector = None


def add_event(message, event_type="info"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event = {"timestamp": timestamp, "message": message, "type": event_type}
    with log_lock:
        event_log.insert(0, event)
        if len(event_log) > 100:
            event_log.pop()


def recording_worker(filepath, fourcc, fps, width, height):
    print(f"[Recorder] Starting recording to {filepath}")
    recorder = cv2.VideoWriter(filepath, fourcc, fps, (width, height))
    while system_running or not recording_queue.empty():
        try:
            frame = recording_queue.get(timeout=1)
            recorder.write(frame)
        except queue.Empty:
            continue
    recorder.release()
    print(f"[Recorder] Finished recording to {filepath}")


def video_processing_loop():
    global current_frame, alert_active, fps_display, detector_ready, system_running

    try:
        global detector
        detector = PersonDetector("yolov8n.pt")
        detector.set_zone(DEFAULT_ZONE)
        detector_ready = True
        add_event("AI Model loaded successfully", "success")
    except Exception as e:
        add_event(f"Failed to load AI model: {e}", "alert")
        print(f"[ERROR] Failed to load model: {e}")
        return

    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        add_event(f"Failed to open video source: {VIDEO_SOURCE}", "alert")
        print(f"[ERROR] Could not open video source: {VIDEO_SOURCE}")
        system_running = False
        return

    add_event(f"Video source opened: {VIDEO_SOURCE}", "success")
    add_event("System monitoring ACTIVE", "success")

    # --- Dashboard video recorder thread ---
    recordings_dir = "recordings"
    os.makedirs(recordings_dir, exist_ok=True)
    rec_filename = f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.avi"
    rec_filepath = os.path.join(recordings_dir, rec_filename)

    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out_fps = 20
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 848
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 478
    
    rec_thread = threading.Thread(
        target=recording_worker, 
        args=(rec_filepath, fourcc, out_fps, frame_w, frame_h),
        daemon=True
    )
    rec_thread.start()
    add_event(f"Recording: {rec_filename}", "info")

    frame_count = 0
    skip_frames = 1 # Process every 2nd frame to boost FPS if on CPU
    
    while system_running:
        ret, frame = cap.read()
        if not ret:
            if isinstance(VIDEO_SOURCE, str):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            else:
                cap.release()
                cap = cv2.VideoCapture(VIDEO_SOURCE)
                continue

        if frame.shape[1] != frame_w or frame.shape[0] != frame_h:
            frame = cv2.resize(frame, (frame_w, frame_h))

        # Frame skipping for performance
        if frame_count % (skip_frames + 1) == 0:
            processed_frame, alert_triggered, detections = detector.process_frame(frame)
            
            # Queue for recording without blocking
            if not recording_queue.full():
                recording_queue.put(processed_frame)

            if alert_triggered:
                if alert_manager.trigger_alert(processed_frame):
                    alert_active = True
                    add_event("⚠ PERSON NEAR SHUTTER — ALERT!", "alert")
                    add_event("Screenshot + image sent to Telegram", "warning")

                    def reset_alert():
                        global alert_active
                        time.sleep(5)
                        alert_active = False
                    threading.Thread(target=reset_alert, daemon=True).start()
                else:
                    if frame_count % 60 == 0:
                        add_event("Person in zone — cooldown active", "info")
            else:
                if frame_count % 90 == 0 and detections:
                    add_event(f"Person detected (safe): {len(detections)}", "info")

            fps_display = detector.fps

            with frame_lock:
                current_frame = processed_frame.copy()
        
        frame_count += 1

    cap.release()


def generate_frames():
    global current_frame
    while True:
        with frame_lock:
            if current_frame is not None:
                _, buffer = cv2.imencode('.jpg', current_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                placeholder = create_placeholder_frame()
                _, buffer = cv2.imencode('.jpg', placeholder, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.033)


def create_placeholder_frame():
    frame = cv2.cvtColor(cv2.imread("static/placeholder.png"), cv2.COLOR_RGB2BGR) \
        if os.path.exists("static/placeholder.png") \
        else cv2.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(frame, "SYSTEM INITIALIZING...", (150, 230),
               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
    cv2.putText(frame, "Loading AI Model...", (200, 270),
               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return frame


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route("/api/status")
def api_status():
    with log_lock:
        recent_events = event_log[:10]
    alert_status = alert_manager.get_alert_status()
    latest_snapshot = alert_manager.get_latest_snapshot()
    return jsonify({
        "system_running": system_running,
        "detector_ready": detector_ready,
        "alert_active": alert_active,
        "fps": round(fps_display, 1),
        "alert_status": alert_status,
        "recent_events": recent_events,
        "latest_snapshot": f"/{latest_snapshot}" if latest_snapshot else None,
        "video_source": str(VIDEO_SOURCE)
    })


@app.route("/api/events")
def api_events():
    with log_lock:
        return jsonify({"events": event_log})


@app.route("/api/test_alert")
def api_test_alert():
    global current_frame
    with frame_lock:
        if current_frame is not None:
            alert_manager.trigger_alert(current_frame, "TEST ALERT from Dashboard")
            add_event("Manual test alert triggered", "warning")
            return jsonify({"status": "Test alert sent!"})
    return jsonify({"status": "No frame available"})


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  AI CCTV SURVEILLANCE SYSTEM")
    print("  YOLOv8 + Flask + Telegram Alerts")
    print("=" * 60)

    video_thread = threading.Thread(target=video_processing_loop, daemon=True)
    video_thread.start()
    time.sleep(2)

    print()
    print("Dashboard: http://localhost:5000")
    print("Stream:    http://localhost:5000/video_feed")
    print()
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
