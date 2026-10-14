import os
import glob
import subprocess
import threading
import base64
import time
import re
from datetime import datetime, timezone
import cv2
import firebase_admin
from firebase_admin import credentials, initialize_app, db

# Flask imports for MJPEG Stream
from flask import Flask, Response, render_template_string
import logging
import json
import uuid

# Deep Learning OCR Engine (RapidOCR ONNX Runtime with PaddleOCR fallback)
try:
    from rapidocr_onnxruntime import RapidOCR
    HAS_RAPIDOCR = True
except Exception:
    RapidOCR = None
    HAS_RAPIDOCR = False

try:
    from paddleocr import PaddleOCR
    HAS_PADDLEOCR = True
except Exception:
    PaddleOCR = None
    HAS_PADDLEOCR = False

# ==========================================
# SYSTEM CONFIGURATION: CHOOSE PROCESSING MODE
# Options: 
#   - "DIRECT_UPLOAD" : Capture -> Resize & Compress -> Base64 -> Upload to RTDB (Fallback / Safe mode)
#   - "OPENCV_OCR"    : Capture -> PaddleOCR Pipeline & Visualization -> Upload to RTDB (Active mode)
# ==========================================
DEFAULT_PROCESSING_MODE = "OPENCV_OCR"
CAPTURE_COMMAND = "rpicam-still"

# Video Settings
FLIP_VIDEO = True
SHOW_GUIDELINE = True

# --- FLASK SERVER SETUP ---
app = Flask(__name__)
# Suppress Werkzeug HTTP request logs to keep terminal clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Global reference so Flask routes can access the active CameraFirebaseManager instance
_global_camera_manager = None

@app.route('/')
def index():
    return render_template_string('''
        <html>
          <head>
            <title>Robot FPV Live Stream</title>
            <style>
              body { background-color: #000; margin: 0; overflow: hidden; display: flex; justify-content: center; align-items: center; height: 100vh; }
              /* Make image fill screen while keeping aspect ratio (contain) or filling completely (cover) */
              img { width: 100vw; height: 100vh; object-fit: contain; }
            </style>
          </head>
          <body>
            <img src="{{ url_for('video_feed') }}">
          </body>
        </html>
    ''')

_latest_frame = None
_frame_cond = threading.Condition()

def stream_reader_thread():
    global _global_camera_manager
    global _latest_frame
    buffer = b''
    while True:
        if _global_camera_manager is None or not _global_camera_manager.is_streaming:
            time.sleep(0.1)
            continue
            
        proc = _global_camera_manager.stream_process
        if proc is None or proc.stdout is None:
            time.sleep(0.1)
            continue
            
        try:
            while _global_camera_manager.is_streaming and proc == _global_camera_manager.stream_process:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                
                while True:
                    a = buffer.find(b'\xff\xd8')
                    b = buffer.find(b'\xff\xd9')
                    if a != -1 and b != -1:
                        if b < a:
                            buffer = buffer[b+2:]
                        else:
                            jpg = buffer[a:b+2]
                            buffer = buffer[b+2:]
                            with _frame_cond:
                                _latest_frame = jpg
                                _frame_cond.notify_all()
                    else:
                        break
        except Exception:
            pass

threading.Thread(target=stream_reader_thread, daemon=True).start()

import numpy as np

def generate_frames():
    global _latest_frame, _global_camera_manager
    while True:
        with _frame_cond:
            _frame_cond.wait(timeout=0.1)
            frame_bytes = _latest_frame
            
        if frame_bytes is not None:
            # OPTIMIZATION: Only decode/encode if we need to draw/flip
            needs_processing = SHOW_GUIDELINE or (_global_camera_manager is not None and (time.time() - _global_camera_manager.last_capture_time < 2.0))
            
            if needs_processing:
                np_arr = np.frombuffer(frame_bytes, np.uint8)
                img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                
                if img is not None:
                    h, w = img.shape[:2]
                    
                    if SHOW_GUIDELINE:
                        cx, cy = w // 2, h // 2
                        
                        # Modern crosshair
                        cv2.circle(img, (cx, cy), 4, (0, 255, 0), -1)
                        cv2.circle(img, (cx, cy), 30, (0, 255, 0), 2)
                        cv2.line(img, (cx - 45, cy), (cx - 15, cy), (0, 255, 0), 2)
                        cv2.line(img, (cx + 15, cy), (cx + 45, cy), (0, 255, 0), 2)
                        cv2.line(img, (cx, cy - 45), (cx, cy - 15), (0, 255, 0), 2)
                        cv2.line(img, (cx, cy + 15), (cx, cy + 45), (0, 255, 0), 2)

                        # Perspective Guidelines (Parking style)
                        bx1, bx2 = int(w * 0.25), int(w * 0.75) # Bottom width
                        tx1, tx2 = int(w * 0.40), int(w * 0.60) # Top width
                        by = h
                        ty = int(h * 0.6)

                        # Draw side trajectory lines
                        cv2.line(img, (bx1, by), (tx1, ty), (0, 165, 255), 3)
                        cv2.line(img, (bx2, by), (tx2, ty), (0, 165, 255), 3)
                        
                        # Distance markers [ratio (0=bottom, 1=top), distance_str, color]
                        distances = [
                            (0.0,  "0cm",  (0, 0, 255)),       # Red
                            (0.33, "20cm", (0, 255, 255)),     # Yellow
                            (0.66, "40cm", (0, 255, 255)),     # Yellow
                            (1.0,  "60cm", (0, 255, 0))        # Green
                        ]
                        
                        for ratio, dist_str, color in distances:
                            curr_y = int(by - ratio * (by - ty))
                            curr_x1 = int(bx1 + ratio * (tx1 - bx1))
                            curr_x2 = int(bx2 - ratio * (bx2 - tx2))
                            
                            # Draw horizontal segment
                            cv2.line(img, (curr_x1, curr_y), (curr_x2, curr_y), color, 2)
                            # Draw distance text
                            cv2.putText(img, dist_str, (curr_x2 + 15, curr_y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                    if _global_camera_manager:
                        # Draw UI Header Bar
                        cv2.rectangle(img, (0, 0), (w, 40), (0, 0, 0), -1)
                        
                        # Draw Telemetry (Angles)
                        yaw = _global_camera_manager.current_yaw
                        pitch = _global_camera_manager.current_pitch
                        ui_text = f"SYS: ONLINE  |  PAN (YAW): {yaw:>3}  |  TILT (PITCH): {pitch:>3}"
                        cv2.putText(img, ui_text, (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                        
                        # Draw Photo Taken notification (Animated Flash)
                        time_since_cap = time.time() - _global_camera_manager.last_capture_time
                        if time_since_cap < 2.0:
                            if int(time_since_cap * 5) % 2 == 0:
                                cv2.rectangle(img, (0, 0), (w-1, h-1), (255, 255, 255), 8) # White flash border
                            
                            text = ">> PHOTO CAPTURED <<"
                            text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)[0]
                            text_x = (w - text_size[0]) // 2
                            text_y = h // 2 - 120
                            
                            cv2.rectangle(img, (text_x - 15, text_y - 35), (text_x + text_size[0] + 15, text_y + 15), (0, 0, 0), -1)
                            cv2.putText(img, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)

                    # Encode back to JPEG (lower quality for stream to save CPU)
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 65]
                    success, buffer = cv2.imencode('.jpg', img, encode_param)
                    if success:
                        frame_bytes = buffer.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
# --------------------------


class CameraFirebaseManager:
    def __init__(self, cred_path="/home/spark/firebase_key.json", 
                 database_url="https://roboproject1-a9c63-default-rtdb.asia-southeast1.firebasedatabase.app/",
                 processing_mode=DEFAULT_PROCESSING_MODE,
                 logger=None):
        """
        Initializes the Camera, Flask Streamer, and Firebase Manager using RTDB.
        """
        global _global_camera_manager
        _global_camera_manager = self
        
        self.logger = logger
        self.cred_path = cred_path
        self.database_url = database_url
        self.processing_mode = processing_mode
        self.max_images = 50
        
        self.workspace_dir = os.path.expanduser("~/ros2_ws")
        self.images_dir = os.path.join(self.workspace_dir, "images")
        self.pending_file = os.path.join(self.workspace_dir, "pending_uploads.json")
        self.counter_file = os.path.join(self.workspace_dir, ".image_counter")
        os.makedirs(self.images_dir, exist_ok=True)
        
        # State tracking
        self._is_capturing = False # High-res upload active
        self._upload_lock = threading.Lock()
        
        # Streaming State
        self.is_streaming = False
        self.stream_process = None
        self._camera_lock = threading.Lock() # Protects stream_process and is_streaming
        
        # Display State
        self.current_yaw = 0
        self.current_pitch = 0
        self.last_capture_time = 0.0
        
        # Start Flask server in background thread (starts immediately, but serves nothing until Stream is ON)
        self.flask_thread = threading.Thread(target=self._run_flask_server, daemon=True)
        self.flask_thread.start()

        self._init_firebase()

        # Initialize Deep Learning OCR Engine (Loaded once at startup)
        self.ocr_reader = None
        self.ocr_engine_type = None

        if HAS_RAPIDOCR and RapidOCR is not None:
            try:
                self._log_info("Loading RapidOCR (ONNX Runtime Deep Learning engine)...")
                self.ocr_reader = RapidOCR()
                self.ocr_engine_type = "RAPIDOCR"
                self._log_info("RapidOCR model loaded successfully.")
            except Exception as e:
                self._log_error(f"Failed to initialize RapidOCR: {e}")
                self.ocr_reader = None

        if self.ocr_reader is None and HAS_PADDLEOCR and PaddleOCR is not None:
            try:
                self._log_info("Loading PaddleOCR fallback model...")
                self.ocr_reader = PaddleOCR(use_angle_cls=False, lang='en')
                self.ocr_engine_type = "PADDLEOCR"
                self._log_info("PaddleOCR model loaded successfully.")
            except Exception as e:
                self._log_error(f"Failed to initialize PaddleOCR: {e}")
                self.ocr_reader = None

        if self.ocr_reader is None:
            self._log_info("No Deep Learning OCR engine available. Running in MOCK_1234 mode.")

        # Start offline sync worker
        self.sync_thread = threading.Thread(target=self._sync_worker, daemon=True)
        self.sync_thread.start()

    def _sync_worker(self):
        """Background thread to sync offline payloads when internet returns."""
        while True:
            time.sleep(10) # Check every 10 seconds
            if not os.path.exists(self.pending_file):
                continue
            
            pending = []
            with self._upload_lock:
                try:
                    with open(self.pending_file, 'r') as f:
                        pending = json.load(f)
                except Exception:
                    pending = []
            
            if not pending:
                continue
            
            # Attempt to upload the first item
            payload = pending[0]
            record_id = payload.get("record_id")
            if not record_id:
                record_id = uuid.uuid4().hex
                payload["record_id"] = record_id

            try:
                reading_val = payload.get("meter_reading", "N/A")
                self._log_info(f"Attempting offline sync for record {record_id} (meter_reading: {reading_val})...")
                db.reference(f'/meter_records/{record_id}').set(payload)
                self._log_info(f"Offline sync successful for {record_id} (meter_reading: {reading_val})")
                
                # Remove from queue and save
                with self._upload_lock:
                    try:
                        with open(self.pending_file, 'r') as f:
                            current_pending = json.load(f)
                        if current_pending and current_pending[0].get("record_id") == record_id:
                            current_pending.pop(0)
                            with open(self.pending_file, 'w') as f:
                                json.dump(current_pending, f)
                    except Exception as e:
                        self._log_error(f"Failed to update pending file after sync: {e}")
            except Exception as e:
                self._log_error(f"Offline sync failed (still offline?): {e}")
                time.sleep(20) # Wait longer if we are offline

    def _queue_payload(self, payload):
        """Save payload to pending queue for offline sync."""
        with self._upload_lock:
            pending = []
            if os.path.exists(self.pending_file):
                try:
                    with open(self.pending_file, 'r') as f:
                        pending = json.load(f)
                except Exception:
                    pass
            pending.append(payload)
            try:
                with open(self.pending_file, 'w') as f:
                    json.dump(pending, f)
            except Exception as e:
                self._log_error(f"Failed to write to pending file: {e}")

    def _run_flask_server(self):
        try:
            self._log_info("Starting Flask FPV server on 0.0.0.0:5000 (Stream OFF by default)")
            app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        except Exception as e:
            self._log_error(f"Flask Server Failed: {e}")

    def _start_vid_process(self):
        """Starts the rpicam-vid subprocess for MJPEG streaming."""
        vid_cmd = CAPTURE_COMMAND.replace('still', 'vid')
        cmd = [
            vid_cmd,
            "-n", # Disable preview window to prevent crash on headless
            "-t", "0",
            "--codec", "mjpeg",
            "--width", "640",
            "--height", "480",
            "--framerate", "25",
            "--inline",
            "-o", "-" # Output to stdout
        ]
        if FLIP_VIDEO:
            cmd.extend(["--hflip", "--vflip"])
        self._log_info(f"Starting native video stream: {vid_cmd}")
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def toggle_stream(self):
        """Toggles the Subprocess MJPEG stream ON/OFF, managing the camera resource."""
        with self._camera_lock:
            if self.is_streaming:
                # Turn OFF
                self.is_streaming = False
                if self.stream_process:
                    self.stream_process.terminate()
                    try:
                        self.stream_process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        self._log_info("Stream process ignored SIGTERM, forcing SIGKILL.")
                        self.stream_process.kill()
                        self.stream_process.wait()
                    self.stream_process = None
                self._log_info("FPV Stream toggled OFF. Camera Released.")
            else:
                # Turn ON (Check if capture is currently holding the camera)
                if self._is_capturing:
                    self._log_error("Cannot start stream while high-res capture is in progress.")
                    return False
                
                try:
                    self.stream_process = self._start_vid_process()
                    self.is_streaming = True
                    self._log_info("FPV Stream toggled ON. Watch at http://<pi_ip>:5000")
                except Exception as e:
                    self._log_error(f"Failed to start video process: {e}")
                    return False
        
        return self.is_streaming

    def _log_info(self, msg):
        if self.logger:
            self.logger.info(f"[CameraManager] {msg}")
        else:
            print(f"[INFO] [CameraManager] {msg}")

    def _log_error(self, msg):
        if self.logger:
            self.logger.error(f"[CameraManager] {msg}")
        else:
            print(f"[ERROR] [CameraManager] {msg}")

    def _init_firebase(self):
        try:
            if not firebase_admin._apps:
                if not os.path.exists(self.cred_path):
                    self._log_error(f"Credentials not found at {self.cred_path}.")
                    return
                cred = credentials.Certificate(self.cred_path)
                initialize_app(cred, {'databaseURL': self.database_url})
                self._log_info("Firebase RTDB initialized successfully.")
        except Exception as e:
            self._log_error(f"Failed to initialize Firebase: {e}")

    def _get_next_image_index(self):
        """
        Determines the next incremental image index.
        Uses both existing files and a persistent state file to guarantee
        strictly monotonic incrementing sequence (0001, 0002, ..., 0051, 0052, ...),
        even after older files are rotated/deleted by manage_local_storage.
        """
        current_counter = 0
        if os.path.exists(self.counter_file):
            try:
                with open(self.counter_file, 'r') as f:
                    current_counter = int(f.read().strip())
            except Exception:
                current_counter = 0

        max_in_files = 0
        search_pattern = os.path.join(self.images_dir, "img_*.jpg")
        for f in glob.glob(search_pattern):
            basename = os.path.basename(f)
            match = re.match(r"img_(\d+)_", basename)
            if match:
                max_in_files = max(max_in_files, int(match.group(1)))

        next_index = max(current_counter, max_in_files) + 1

        try:
            with open(self.counter_file, 'w') as f:
                f.write(str(next_index))
        except Exception as e:
            self._log_error(f"Failed to persist image counter: {e}")

        return next_index

    def manage_local_storage(self):
        try:
            search_pattern = os.path.join(self.images_dir, "*.jpg")
            files = glob.glob(search_pattern)
            if len(files) > self.max_images:
                files.sort(key=os.path.getmtime)
                files_to_delete = len(files) - self.max_images
                for i in range(files_to_delete):
                    os.remove(files[i])
                    self._log_info(f"Deleted old image: {os.path.basename(files[i])}")
        except Exception as e:
            self._log_error(f"Error managing local storage: {e}")

    def capture_and_upload_task(self, pitch_angle=0.0):
        """Non-blocking public entry point."""
        with self._upload_lock:
            if self._is_capturing:
                self._log_info("High-res capture already in progress. Ignoring.")
                return
            self._is_capturing = True

        thread = threading.Thread(target=self._capture_and_upload_worker, args=(pitch_angle,), daemon=True)
        thread.start()

    def capture_and_upload(self, pitch_angle=0.0):
        """Public alias for capture_and_upload_task."""
        return self.capture_and_upload_task(pitch_angle)

    def _process_image_ocr(self, cv_image):
        """
        On-device Deep Learning OCR Pipeline using RapidOCR (ONNX Runtime).
        Extracts numbers/digits from the center Region of Interest (ROI),
        annotates the image with a visual HUD bounding box and detected digits,
        and returns the annotated image and detected digits string.
        """
        self._log_info("Running on-device OCR pipeline...")
        h, w = cv_image.shape[:2]

        # 1. Crop Region of Interest (ROI) - Centered bounding box where camera HUD crosshair aims
        # Designed for the meter box (4 digits under REAI header or real analog rolling counters)
        roi_w = int(w * 0.45)
        roi_h = int(h * 0.35)
        start_x = (w - roi_w) // 2
        start_y = (h - roi_h) // 2
        roi = cv_image[start_y:start_y + roi_h, start_x:start_x + roi_w]

        detected_number_str = ""
        extracted_digits_list = []
        valid_detected_boxes = []

        # 2. Run inference with RapidOCR / PaddleOCR
        if self.ocr_reader is not None:
            try:
                raw_boxes = []
                if self.ocr_engine_type == "RAPIDOCR":
                    ocr_result, elapse = self.ocr_reader(roi)
                    if ocr_result:
                        for box, text, score in ocr_result:
                            raw_boxes.append((box, text, score))
                elif self.ocr_engine_type == "PADDLEOCR":
                    ocr_result = self.ocr_reader.ocr(roi, cls=False)
                    if ocr_result and len(ocr_result) > 0:
                        lines = ocr_result[0] if (isinstance(ocr_result, list) and len(ocr_result) > 0 and isinstance(ocr_result[0], list)) else ocr_result
                        if lines:
                            for item in lines:
                                if item and len(item) >= 2 and isinstance(item[1], (tuple, list)):
                                    raw_boxes.append((item[0], item[1][0], item[1][1]))

                # Parse and compute bounding boxes
                parsed_boxes = []
                for box, text, score in raw_boxes:
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    xmin, xmax = min(xs), max(xs)
                    ymin, ymax = min(ys), max(ys)
                    parsed_boxes.append({
                        'box': box, 'text': str(text).strip(), 'score': float(score),
                        'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax
                    })

                # Suppression / containment filter:
                # If a smaller box is largely inside a larger box with higher score, suppress the smaller box
                filtered_boxes = []
                for i, b1 in enumerate(parsed_boxes):
                    is_contained = False
                    for j, b2 in enumerate(parsed_boxes):
                        if i != j:
                            if b1['xmin'] >= b2['xmin'] - 20 and b1['xmax'] <= b2['xmax'] + 20 and b1['score'] < b2['score']:
                                is_contained = True
                                break
                    if not is_contained:
                        filtered_boxes.append(b1)

                # Sort left to right by xmin for proper reading order
                filtered_boxes.sort(key=lambda b: b['xmin'])

                # Character normalization for digits (common OCR confusions in meter reading)
                digit_map = {'O': '0', 'o': '0', 'D': '0', 'I': '1', 'l': '1', 'i': '1', 'Z': '2', 'z': '2', 'S': '5', 's': '5', 'B': '8', 'b': '6'}

                for b in filtered_boxes:
                    raw_text = b['text']
                    # Skip English header labels like 'REAI', 'WATER', etc.
                    invalid_chars = [c for c in raw_text if c.isalpha() and c not in digit_map]
                    if len(invalid_chars) > 0 and len(raw_text) > 2:
                        continue

                    converted = ''.join(digit_map.get(c, c) for c in raw_text)
                    digits = re.sub(r'\D', '', converted)
                    if digits:
                        extracted_digits_list.append(digits)
                        valid_detected_boxes.append(b)

                if extracted_digits_list:
                    detected_number_str = "".join(extracted_digits_list)
                    self._log_info(f"✅ OCR Success: {detected_number_str}")
                else:
                    self._log_info("OCR ran successfully but no digits found in ROI.")
                    detected_number_str = "NOT_DETECTED"
            except Exception as e:
                self._log_error(f"Error during OCR inference: {e}. Falling back to MOCK_1234.")
                detected_number_str = "MOCK_1234"
        else:
            self._log_info("OCR engine not active. Using fallback reading: MOCK_1234")
            detected_number_str = "MOCK_1234"

        # 3. Visual Annotation on Image: Draw bounding box & text overlay
        annotated_image = cv_image.copy()

        # Box Color: Green for successful detection, Cyan/Yellow for fallback, Red for not detected
        if detected_number_str not in ("NOT_DETECTED", "MOCK_1234"):
            box_color = (0, 255, 0) # Green
        elif detected_number_str == "MOCK_1234":
            box_color = (0, 200, 255) # Yellow/Cyan
        else:
            box_color = (0, 0, 255) # Red

        # Draw ROI target border
        cv2.rectangle(annotated_image, (start_x, start_y), (start_x + roi_w, start_y + roi_h), box_color, 4)

        # Draw individual detected character/box highlights inside ROI
        for b in valid_detected_boxes:
            box_pts = b['box']
            pts = np.array([[int(p[0] + start_x), int(p[1] + start_y)] for p in box_pts], np.int32)
            pts = pts.reshape((-1, 1, 2))
            cv2.polylines(annotated_image, [pts], isClosed=True, color=(0, 255, 255), thickness=2)

        # Draw HUD Label on top of the ROI box
        label_text = f"METER READING: {detected_number_str}"
        font_scale = max(0.8, w / 2200.0 * 1.3)
        thickness = max(2, int(font_scale * 2))

        (text_w, text_h), baseline = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        text_bg_y1 = max(0, start_y - text_h - 18)
        text_bg_y2 = start_y
        cv2.rectangle(annotated_image, (start_x, text_bg_y1), (start_x + text_w + 20, text_bg_y2), (0, 0, 0), -1)
        cv2.putText(annotated_image, label_text, (start_x + 10, start_y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, box_color, thickness, cv2.LINE_AA)

        return annotated_image, detected_number_str

    def _capture_and_upload_worker(self, pitch_angle):
        """Blocking workload executed in the background thread."""
        try:
            # --- CONFLICT HANDLING ---
            # If stream is ON, we must pause it and release the hardware lock
            was_streaming = False
            with self._camera_lock:
                if self.is_streaming:
                    self._log_info("Pausing FPV stream to free camera for high-res capture...")
                    was_streaming = True
                    self.is_streaming = False
                    if self.stream_process:
                        self.stream_process.terminate()
                        try:
                            self.stream_process.wait(timeout=0.5)
                        except subprocess.TimeoutExpired:
                            self.stream_process.kill()
                            self.stream_process.wait()
                        self.stream_process = None
            
            # Give the hardware a split second to completely release the V4L2 device
            if was_streaming:
                time.sleep(0.5)
            # -------------------------

            timestamp_dt = datetime.now(timezone.utc)
            timestamp_str_file = timestamp_dt.strftime("%Y%m%d_%H%M%S")
            iso_timestamp = timestamp_dt.isoformat()

            index = self._get_next_image_index()
            filename = f"img_{index:04d}_{timestamp_str_file}.jpg"
            filepath = os.path.join(self.images_dir, filename)

            # 1. Capture Full-Res Image using rpicam-still (Hardware ISP & Autofocus)
            self._log_info(f"Capturing: {filename} using {CAPTURE_COMMAND}...")
            cmd = [
                CAPTURE_COMMAND,
                "-o", filepath,
                "--autofocus-on-capture",
                "--timeout", "1000",
                "--nopreview"
            ]
            if FLIP_VIDEO:
                cmd.extend(["--hflip", "--vflip"])
            
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                self._log_error(f"Camera capture failed: {result.stderr}")
                return

            self._log_info(f"Saved locally: {filepath}")
            self.manage_local_storage()

            # 2. Load with OpenCV for Processing/Compression
            self._log_info("Reading high-res image with OpenCV...")
            img = cv2.imread(filepath)
            if img is None:
                self._log_error(f"OpenCV failed to read {filepath}")
                return

            meter_reading = None

            # 3. Pipeline Routing based on Mode
            if self.processing_mode == "OPENCV_OCR":
                img, meter_reading = self._process_image_ocr(img)
            else:
                meter_reading = "DIRECT_MODE"

            if meter_reading and meter_reading not in ("NOT_DETECTED", "DIRECT_MODE", "MOCK_1234"):
                self._log_info(f"✅ OCR Success: {meter_reading}")
            else:
                self._log_info(f"OCR Mode '{self.processing_mode}' output: {meter_reading}")

            # 4. Resize and Compress
            max_dim = 800
            h, w = img.shape[:2]
            if max(h, w) > max_dim:
                scale = max_dim / float(max(h, w))
                img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75]
            success, buffer = cv2.imencode('.jpg', img, encode_param)
            if not success:
                self._log_error("OpenCV failed to encode image buffer.")
                return

            # Convert to Base64
            b64_string = base64.b64encode(buffer).decode('utf-8')
            data_uri = f"data:image/jpeg;base64,{b64_string}"
            self._log_info(f"Base64 generated (Size: {len(data_uri)/1024:.1f} KB)")

            # 5. Push to Firebase RTDB
            self._log_info("Pushing to Firebase RTDB (/meter_records)...")
            
            try:
                record_id = db.reference('/meter_records').push().key
            except Exception:
                record_id = uuid.uuid4().hex
                
            meter_type = "electricity" if pitch_angle > 0 else "water"
            
            payload = {
                "record_id": record_id,
                "filename": filename,
                "image_base64": data_uri,
                "image_data": data_uri,
                "timestamp": iso_timestamp,
                "meter_reading": meter_reading,
                "meter_type": meter_type
            }

            try:
                db.reference(f'/meter_records/{record_id}').set(payload)
                self.last_capture_time = time.time()
                self._log_info(f"Successfully pushed to RTDB! Record ID: {record_id} | Reading: {meter_reading} | Mode: {self.processing_mode}")
            except Exception as e:
                self._log_error(f"Upload failed: {e}. Queuing for offline sync.")
                self.last_capture_time = time.time()
                self._queue_payload(payload)

        except Exception as e:
            self._log_error(f"Exception in worker: {e}")
        finally:
            # --- CONFLICT RECOVERY ---
            # Resume stream if it was running before the capture
            if was_streaming:
                self._log_info("Resuming FPV stream...")
                with self._camera_lock:
                    try:
                        self.stream_process = self._start_vid_process()
                        self.is_streaming = True
                    except Exception as e:
                        self._log_error(f"Failed to resume FPV stream. {e}")
            # -------------------------

            with self._upload_lock:
                self._is_capturing = False
