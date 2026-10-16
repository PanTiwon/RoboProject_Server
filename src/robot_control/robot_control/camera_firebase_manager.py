import os
import glob
import subprocess
import threading
import base64
import time
import re
from datetime import datetime, timezone
import cv2
import numpy as np
import firebase_admin
from firebase_admin import credentials, initialize_app, db

# Flask imports for WebRTC FPV dashboard
from flask import Flask, Response, render_template_string, request
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

# ==========================================
# CAPTURE MODE CONFIGURATION (Dual Capture Mode)
# Options:
#   - "STREAM_GRAB"    : Instant / Zero-Downtime mode. Grabs current 720p frame directly from active
#                        MediaMTX RTSP stream (rtsp://127.0.0.1:8554/live) without pausing or stopping
#                        the WebRTC FPV stream. FPV screen stays 100% continuous without blackouts.
#   - "HARDWARE_STILL" : High-Res Turbo mode. Pauses MediaMTX briefly (150ms buffer), triggers
#                        rpicam-still with 600ms timeout, immediately re-launches MediaMTX (< 1s total),
#                        and performs OCR & Firebase upload in the background.
# ==========================================
DEFAULT_CAPTURE_MODE = "STREAM_GRAB"

# Multi-Meter Detection Toggle (HSV + RapidOCR)
# True  : Automatically detects multiple blue meter boxes (left-to-right) via HSV.
#         If 0 boxes are found, it seamlessly falls back to Fixed Center ROI.
# False : Always uses classic Fixed Center ROI.
ENABLE_MULTI_METER_DETECTION = True

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
    html_file = os.path.expanduser('~/ros2_ws/whep_client_demo.html')
    if os.path.exists(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    return render_template_string('''
        <html>
          <head><title>Robot FPV WebRTC</title></head>
          <body style="background:#0b0f19;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;">
            <div style="text-align:center;">
              <h2>WebRTC Stream Broker (MediaMTX)</h2>
              <p>Direct Player: <a style="color:#00f0ff;" href="http://{{ request.host.split(':')[0] }}:8889/live">http://{{ request.host.split(':')[0] }}:8889/live</a></p>
              <p>WHEP Endpoint: <code style="color:#00ff88;">http://{{ request.host.split(':')[0] }}:8889/live/whep</code></p>
            </div>
          </body>
        </html>
    ''')

@app.route('/video_feed')
def video_feed():
    return Response(
        "Stream migrated to WebRTC WHEP. Connect to http://<pi_ip>:8889/live or http://<pi_ip>:5000",
        mimetype='text/plain',
        status=200
    )
# --------------------------



class CameraFirebaseManager:
    def __init__(self, cred_path="/home/spark/firebase_key.json", 
                 database_url="https://roboproject1-a9c63-default-rtdb.asia-southeast1.firebasedatabase.app/",
                 processing_mode=DEFAULT_PROCESSING_MODE,
                 capture_mode=DEFAULT_CAPTURE_MODE,
                 enable_multi_meter=ENABLE_MULTI_METER_DETECTION,
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
        self.capture_mode = capture_mode
        self.enable_multi_meter = enable_multi_meter

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
        """Starts the MediaMTX subprocess for native WebRTC H.264 streaming with Continuous Autofocus."""
        mediamtx_bin = "/home/spark/mediamtx/mediamtx"
        mediamtx_cfg = "/home/spark/mediamtx/mediamtx.yml"
        cmd = [mediamtx_bin, mediamtx_cfg]
        self._log_info("Starting MediaMTX WebRTC server (WHEP at :8889/live/whep)...")
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def toggle_stream(self):
        """Toggles the MediaMTX WebRTC stream ON/OFF, managing the camera resource."""
        with self._camera_lock:
            if self.is_streaming:
                # Turn OFF
                self.is_streaming = False
                if self.stream_process:
                    self.stream_process.terminate()
                    try:
                        self.stream_process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        self._log_info("MediaMTX ignored SIGTERM, forcing SIGKILL.")
                        self.stream_process.kill()
                        self.stream_process.wait()
                    self.stream_process = None
                self._log_info("FPV WebRTC Stream toggled OFF. Camera Released.")
            else:
                # Turn ON (Check if capture is currently holding the camera)
                if self._is_capturing:
                    self._log_error("Cannot start stream while high-res capture is in progress.")
                    return False
                
                try:
                    self.stream_process = self._start_vid_process()
                    self.is_streaming = True
                    self._log_info("FPV WebRTC Stream toggled ON. Watch at http://<pi_ip>:8889/live or http://<pi_ip>:5000")
                except Exception as e:
                    self._log_error(f"Failed to start MediaMTX stream process: {e}")
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

    def _detect_meter_boxes(self, cv_image):
        """
        Detects blue meter boxes/enclosures (rectangular and cylindrical) using HSV segmentation.
        Filters contours by area and aspect ratio to suppress background noise.
        Returns a list of bounding boxes [(x1, y1, x2, y2), ...] sorted strictly left-to-right (x1 ascending).
        """
        h_img, w_img = cv_image.shape[:2]
        img_area = float(w_img * h_img)

        # Blue color range in HSV space (tuned for meter enclosures, handles specular glare)
        hsv = cv2.cvtColor(cv_image, cv2.COLOR_BGR2HSV)
        lower_blue = np.array([90, 45, 30])
        upper_blue = np.array([140, 255, 255])
        mask = cv2.inRange(hsv, lower_blue, upper_blue)

        # Noise reduction via morphology open/close
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Filtering thresholds
        min_area = img_area * 0.005  # At least 0.5% of total frame area
        max_area = img_area * 0.70  # At most 70% of total frame area

        boxes = []
        for c in contours:
            area = cv2.contourArea(c)
            if min_area < area < max_area:
                bx, by, bw, bh = cv2.boundingRect(c)
                ar = bw / float(bh)
                # Meter boxes (rectangular / cylindrical) aspect ratio check
                if 0.35 < ar < 3.0:
                    boxes.append((bx, by, bx + bw, by + bh))

        # Sort strictly left-to-right by X coordinate
        boxes.sort(key=lambda b: b[0])
        return boxes

    def _extract_digits_from_roi(self, roi):
        """
        Runs RapidOCR (or PaddleOCR fallback) on a given cropped ROI.
        Performs box containment suppression, header exclusion ('REAI', etc.), and digit normalization.
        Returns:
            detected_number_str (str): Extracted digit sequence (e.g. '4802') or 'NOT_DETECTED' / 'MOCK_1234'
            valid_detected_boxes (list): List of detected character box dicts with local coordinates
        """
        detected_number_str = ""
        extracted_digits_list = []
        valid_detected_boxes = []

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

                digit_map = {'O': '0', 'o': '0', 'D': '0', 'I': '1', 'l': '1', 'i': '1', 'Z': '2', 'z': '2', 'S': '5', 's': '5', 'B': '8', 'b': '6'}

                # 1. Parse and immediately filter out non-digit headers (e.g., 'REAI')
                parsed_boxes = []
                for box, text, score in raw_boxes:
                    raw_text = str(text).strip()
                    # Skip known English header labels like 'REAI', 'WATER', etc.
                    if 'REA' in raw_text.upper() or 'EAI' in raw_text.upper():
                        continue
                    invalid_chars = [c for c in raw_text if c.isalpha() and c not in digit_map]
                    if len(invalid_chars) > 0 and len(raw_text) > 2:
                        continue

                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    xmin, xmax = min(xs), max(xs)
                    ymin, ymax = min(ys), max(ys)
                    parsed_boxes.append({
                        'box': box, 'text': raw_text, 'score': float(score),
                        'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax
                    })

                # 2. 2D Suppression filter: Only suppress if boxes significantly overlap in both X and Y
                filtered_boxes = []
                for i, b1 in enumerate(parsed_boxes):
                    is_contained = False
                    for j, b2 in enumerate(parsed_boxes):
                        if i != j:
                            x_overlap = max(0, min(b1['xmax'], b2['xmax']) - max(b1['xmin'], b2['xmin']))
                            y_overlap = max(0, min(b1['ymax'], b2['ymax']) - max(b1['ymin'], b2['ymin']))
                            area1 = (b1['xmax'] - b1['xmin']) * (b1['ymax'] - b1['ymin'])
                            if area1 > 0 and ((x_overlap * y_overlap) / float(area1)) > 0.55 and b1['score'] < b2['score']:
                                is_contained = True
                                break
                    if not is_contained:
                        filtered_boxes.append(b1)

                filtered_boxes.sort(key=lambda b: b['xmin'])

                # 3. Extract and normalize digits
                for b in filtered_boxes:
                    converted = ''.join(digit_map.get(c, c) for c in b['text'])
                    digits = re.sub(r'\D', '', converted)
                    if digits:
                        extracted_digits_list.append(digits)
                        valid_detected_boxes.append(b)

                if extracted_digits_list:
                    detected_number_str = "".join(extracted_digits_list)
                else:
                    detected_number_str = "NOT_DETECTED"
            except Exception as e:
                self._log_error(f"Error during OCR inference: {e}. Falling back to MOCK_1234.")
                detected_number_str = "MOCK_1234"
        else:
            detected_number_str = "MOCK_1234"

        return detected_number_str, valid_detected_boxes

    def _process_image_ocr(self, cv_image):
        """
        Hybrid Meter Detection + RapidOCR Pipeline:
        1. Checks self.enable_multi_meter and detects blue meter boxes using HSV.
        2. Safety Fallback: If toggle is False OR 0 blue boxes detected -> Falls back to classic Fixed Center ROI.
        3. Multi-Meter Mode: If boxes detected -> Iterates through boxes (sorted left-to-right),
           crops each with 15% horizontal / 12% vertical padding, runs RapidOCR, and creates:
           - An individually annotated cropped image for each meter (used for split upload).
           - A unified full annotated image (for local archive).
        Returns:
            annotated_image (np.ndarray): Full image with green/yellow/red HUD bounding boxes and badges
            meter_records (list): List of dicts per meter:
                [{
                    "label": "METER 1: 7527" (or "CENTER_METER: 1234"),
                    "reading": "7527",
                    "cropped_image": crop_annotated (np.ndarray),
                    "meter_index": 1,
                    "is_fallback": False
                }, ...]
        """
        self._log_info("Running Hybrid Meter Detection + OCR pipeline...")
        h, w = cv_image.shape[:2]
        annotated_image = cv_image.copy()

        # Check Multi-Meter detection toggle and find boxes
        meter_boxes = []
        if self.enable_multi_meter:
            meter_boxes = self._detect_meter_boxes(cv_image)
            if meter_boxes:
                self._log_info(f"HSV Multi-Meter: Found {len(meter_boxes)} meter box(es) (sorted left-to-right).")
            else:
                self._log_info("HSV Multi-Meter: 0 blue meter boxes detected. Engaging Fixed Center ROI Fallback.")
        else:
            self._log_info("Multi-Meter toggle is OFF. Using Fixed Center ROI mode.")

        # If no meter boxes detected (or multi-meter disabled), use Fixed Center ROI
        if not meter_boxes:
            roi_w = int(w * 0.45)
            roi_h = int(h * 0.35)
            start_x = (w - roi_w) // 2
            start_y = (h - roi_h) // 2
            meter_boxes = [(start_x, start_y, start_x + roi_w, start_y + roi_h)]
            is_fallback_mode = True
        else:
            is_fallback_mode = False

        meter_records = []

        # Process each meter box
        for idx, (bx1, by1, bx2, by2) in enumerate(meter_boxes):
            # Apply padding (15% horizontal, 12% vertical) if detected via HSV; center ROI already has appropriate margins
            if not is_fallback_mode:
                pad_x = int((bx2 - bx1) * 0.15)
                pad_y = int((by2 - by1) * 0.12)
                crop_x1 = max(0, bx1 - pad_x)
                crop_y1 = max(0, by1 - pad_y)
                crop_x2 = min(w, bx2 + pad_x)
                crop_y2 = min(h, by2 + pad_y)
            else:
                crop_x1, crop_y1, crop_x2, crop_y2 = bx1, by1, bx2, by2

            roi = cv_image[crop_y1:crop_y2, crop_x1:crop_x2]
            reading, valid_boxes = self._extract_digits_from_roi(roi)

            # Determine label text
            if is_fallback_mode:
                label_text = f"CENTER_METER: {reading}"
            else:
                label_text = f"METER {idx + 1}: {reading}"

            # Determine HUD color
            if reading not in ("NOT_DETECTED", "MOCK_1234"):
                box_color = (0, 255, 0)      # Green: Successful OCR
            elif reading == "MOCK_1234":
                box_color = (0, 200, 255)    # Yellow/Cyan: Fallback Mock
            else:
                box_color = (0, 0, 255)      # Red: Not detected

            # --- Create Annotated Cropped Image for this specific meter ---
            crop_annotated = roi.copy()
            ch, cw = crop_annotated.shape[:2]

            # 1. Draw outer border on the crop
            cv2.rectangle(crop_annotated, (2, 2), (cw - 3, ch - 3), box_color, 3)

            # 2. Draw individual detected character polygons inside the crop
            for b in valid_boxes:
                box_pts = b['box']
                pts = np.array(box_pts, np.int32).reshape((-1, 1, 2))
                cv2.polylines(crop_annotated, [pts], isClosed=True, color=(0, 255, 255), thickness=2)

            # 3. Draw HUD Label Banner on the crop
            crop_font_scale = max(0.6, min(1.1, cw / 260.0))
            crop_thickness = max(2, int(crop_font_scale * 2))
            (ctw, cth), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, crop_font_scale, crop_thickness)
            cv2.rectangle(crop_annotated, (0, 0), (min(cw, ctw + 18), cth + 16), (0, 0, 0), -1)
            cv2.putText(crop_annotated, label_text, (8, cth + 10),
                        cv2.FONT_HERSHEY_SIMPLEX, crop_font_scale, box_color, crop_thickness, cv2.LINE_AA)

            meter_records.append({
                "label": label_text,
                "reading": reading,
                "cropped_image": crop_annotated,
                "meter_index": idx + 1 if not is_fallback_mode else 1,
                "is_fallback": is_fallback_mode
            })

            # --- Also Draw on Full Image (for local archive) ---
            cv2.rectangle(annotated_image, (crop_x1, crop_y1), (crop_x2, crop_y2), box_color, 3)
            for b in valid_boxes:
                box_pts = b['box']
                pts = np.array([[int(p[0] + crop_x1), int(p[1] + crop_y1)] for p in box_pts], np.int32)
                pts = pts.reshape((-1, 1, 2))
                cv2.polylines(annotated_image, [pts], isClosed=True, color=(0, 255, 255), thickness=2)

            # Draw Label on full image
            full_font_scale = max(0.55, min(1.0, (crop_x2 - crop_x1) / 250.0))
            full_thickness = max(1, int(full_font_scale * 2))
            (ftw, fth), baseline = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, full_font_scale, full_thickness)

            if crop_y1 - fth - 12 >= 0:
                fbg_y1 = crop_y1 - fth - 12
                fbg_y2 = crop_y1
                ftext_y = crop_y1 - 6
            else:
                fbg_y1 = crop_y1
                fbg_y2 = crop_y1 + fth + 12
                ftext_y = crop_y1 + fth + 6

            fbg_x1 = crop_x1
            fbg_x2 = min(w, crop_x1 + ftw + 14)
            cv2.rectangle(annotated_image, (fbg_x1, fbg_y1), (fbg_x2, fbg_y2), (0, 0, 0), -1)
            cv2.putText(annotated_image, label_text, (fbg_x1 + 6, ftext_y),
                        cv2.FONT_HERSHEY_SIMPLEX, full_font_scale, box_color, full_thickness, cv2.LINE_AA)

        summary_str = ", ".join(m["label"] for m in meter_records)
        self._log_info(f"✅ OCR Results: {summary_str} ({len(meter_records)} meter(s))")

        return annotated_image, meter_records

    def _grab_frame_from_stream(self):
        """
        Grabs the latest 720p frame directly from the active MediaMTX RTSP stream
        (rtsp://127.0.0.1:8554/live) with zero downtime to the WebRTC FPV stream.
        Returns:
            frame (np.ndarray or None): Decoded BGR image
        """
        auto_started = False
        with self._camera_lock:
            if not self.is_streaming or self.stream_process is None or self.stream_process.poll() is not None:
                self._log_info("STREAM_GRAB: MediaMTX stream is not currently active. Auto-starting stream...")
                self.stream_process = self._start_vid_process()
                self.is_streaming = True
                auto_started = True

        if auto_started:
            time.sleep(1.8) # Wait briefly for RTSP broker ready

        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        t0 = time.time()
        cap = cv2.VideoCapture("rtsp://127.0.0.1:8554/live", cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        frame = None
        if cap.isOpened():
            ret, grabbed = cap.read()
            if ret and grabbed is not None:
                frame = grabbed
                elapsed = (time.time() - t0) * 1000
                self._log_info(f"✅ STREAM_GRAB: Captured {frame.shape[1]}x{frame.shape[0]} frame in {elapsed:.1f}ms (Zero Downtime)")
            cap.release()
        else:
            self._log_error("STREAM_GRAB: Failed to connect to RTSP endpoint rtsp://127.0.0.1:8554/live")

        return frame

    def _capture_and_upload_worker(self, pitch_angle):
        """Blocking workload executed in the background thread."""
        try:
            timestamp_dt = datetime.now(timezone.utc)
            timestamp_str_file = timestamp_dt.strftime("%Y%m%d_%H%M%S")
            iso_timestamp = timestamp_dt.isoformat()

            index = self._get_next_image_index()
            filename = f"img_{index:04d}_{timestamp_str_file}.jpg"
            filepath = os.path.join(self.images_dir, filename)

            img = None
            was_streaming = False

            # ==========================================
            # DUAL CAPTURE MODE ROUTING
            # ==========================================
            if self.capture_mode == "STREAM_GRAB":
                self._log_info(f"📸 Triggering capture: {filename} via [STREAM_GRAB] (Zero-Downtime Mode)...")
                img = self._grab_frame_from_stream()
                if img is not None:
                    # Save local archive copy
                    cv2.imwrite(filepath, img)
                    self._log_info(f"Saved locally: {filepath}")
                    self.manage_local_storage()
                else:
                    self._log_error("STREAM_GRAB failed. Falling back to HARDWARE_STILL mode...")

            if img is None:
                # ==========================================
                # HARDWARE_STILL (High-Res Turbo Mode)
                # ==========================================
                self._log_info(f"📸 Triggering capture: {filename} via [HARDWARE_STILL] (Turbo High-Res Mode)...")

                with self._camera_lock:
                    if self.is_streaming:
                        self._log_info("Pausing MediaMTX WebRTC stream to free camera for high-res capture...")
                        was_streaming = True
                        self.is_streaming = False
                        if self.stream_process:
                            self.stream_process.terminate()
                            try:
                                self.stream_process.wait(timeout=1.0)
                            except subprocess.TimeoutExpired:
                                self.stream_process.kill()
                                self.stream_process.wait()
                            self.stream_process = None

                # Minimized hardware release buffer (0.15s)
                if was_streaming:
                    time.sleep(0.15)

                af_range = "macro" if pitch_angle <= 0 else "normal"
                self._log_info(f"Capturing: {filename} (Pitch: {pitch_angle:.1f}°, AF Range: {af_range}, Timeout: 600ms)...")
                cmd = [
                    CAPTURE_COMMAND,
                    "-o", filepath,
                    "--autofocus-on-capture",
                    "--autofocus-range", af_range,
                    "--autofocus-window", "0.25,0.25,0.5,0.5",
                    "--hdr", "sensor",
                    "--timeout", "600",
                    "--nopreview"
                ]
                if FLIP_VIDEO:
                    cmd.extend(["--hflip", "--vflip"])

                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                # --- IMMEDIATE RE-LAUNCH: Resume MediaMTX stream immediately so FPV returns in < 1s ---
                if was_streaming:
                    self._log_info("Hardware capture complete. Immediately re-launching MediaMTX stream...")
                    with self._camera_lock:
                        try:
                            self.stream_process = self._start_vid_process()
                            self.is_streaming = True
                            was_streaming = False # Cleared since already resumed
                        except Exception as e:
                            self._log_error(f"Failed to re-launch MediaMTX: {e}")

                if result.returncode != 0:
                    self._log_error(f"Camera capture failed: {result.stderr}")
                    return

                self._log_info(f"Saved locally: {filepath}")
                self.manage_local_storage()

                # Read captured high-res image
                img = cv2.imread(filepath)
                if img is None:
                    self._log_error(f"OpenCV failed to read {filepath}")
                    return

            # ==========================================
            # COMMON PIPELINE: OCR & Firebase Upload
            # ==========================================
            meter_records = []

            if self.processing_mode == "OPENCV_OCR":
                annotated_full, meter_records = self._process_image_ocr(img)
                # Overwrite locally saved full image with annotated full image for archive
                cv2.imwrite(filepath, annotated_full)
            else:
                meter_records = [{
                    "label": "DIRECT_MODE",
                    "reading": "DIRECT_MODE",
                    "cropped_image": img,
                    "meter_index": 1,
                    "is_fallback": True
                }]

            # Upload each meter record individually (Split Uploads using Cropped Images)
            self._log_info(f"Uploading {len(meter_records)} meter record(s) to Firebase RTDB...")
            meter_type = "electricity" if pitch_angle > 0 else "water"

            for idx, item in enumerate(meter_records):
                crop_img = item["cropped_image"]

                # Resize crop if larger than 800px (safety check, crops are usually ~300-600px)
                ch, cw = crop_img.shape[:2]
                if max(ch, cw) > 800:
                    scale = 800.0 / float(max(ch, cw))
                    crop_img = cv2.resize(crop_img, (int(cw * scale), int(ch * scale)), interpolation=cv2.INTER_AREA)

                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                success, buffer = cv2.imencode('.jpg', crop_img, encode_param)
                if not success:
                    self._log_error(f"OpenCV failed to encode cropped image for {item['label']}.")
                    continue

                # Convert to Base64 (uploading cropped ROI only)
                b64_string = base64.b64encode(buffer).decode('utf-8')
                crop_data_uri = f"data:image/jpeg;base64,{b64_string}"

                try:
                    record_id = db.reference('/meter_records').push().key
                except Exception:
                    record_id = uuid.uuid4().hex

                suffix = f"_m{item['meter_index']}" if not item.get("is_fallback") else "_center"
                crop_filename = f"{filename[:-4]}{suffix}.jpg"

                payload = {
                    "record_id": record_id,
                    "filename": crop_filename,
                    "image_base64": crop_data_uri,
                    "timestamp": iso_timestamp,
                    "meter_reading": str(item["reading"]),
                    "meter_index": item["meter_index"],
                    "meter_type": meter_type,
                    "is_fallback": item.get("is_fallback", False)
                }

                try:
                    db.reference(f'/meter_records/{record_id}').set(payload)
                    self._log_info(f"✅ Successfully pushed to RTDB! Record ID: {record_id} | {item['label']} (Reading: {item['reading']})")
                except Exception as e:
                    self._log_error(f"Upload failed for {item['label']}: {e}. Queuing for offline sync.")
                    self._queue_payload(payload)

            self.last_capture_time = time.time()

        except Exception as e:
            self._log_error(f"Exception in worker: {e}")
        finally:
            # Safety recovery if stream was paused but failed to resume before
            if was_streaming:
                self._log_info("Safety recovery: Resuming MediaMTX WebRTC stream...")
                with self._camera_lock:
                    try:
                        self.stream_process = self._start_vid_process()
                        self.is_streaming = True
                    except Exception as e:
                        self._log_error(f"Failed to resume WebRTC stream: {e}")

            with self._upload_lock:
                self._is_capturing = False

