import os
import glob
import subprocess
import threading
import base64
import time
from datetime import datetime, timezone
import cv2
import firebase_admin
from firebase_admin import credentials, initialize_app, db

# Flask imports for MJPEG Stream
from flask import Flask, Response, render_template_string
import logging

# ==========================================
# SYSTEM CONFIGURATION: CHOOSE PROCESSING MODE
# Options: 
#   - "DIRECT_UPLOAD" : Capture -> Resize & Compress -> Base64 -> Upload to RTDB (Fallback / Safe mode)
#   - "OPENCV_OCR"    : Capture -> OpenCV Preprocessing & OCR Pipeline -> Upload to RTDB (Semester 2 mode)
# ==========================================
DEFAULT_PROCESSING_MODE = "DIRECT_UPLOAD"
CAPTURE_COMMAND = "rpicam-still"

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
              body { background-color: #111; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; flex-direction: column; font-family: Arial, sans-serif;}
              img { max-width: 100%; max-height: 85vh; border: 3px solid #444; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
              h1 { margin-bottom: 20px; }
            </style>
          </head>
          <body>
            <h1>Mecanum FPV Camera</h1>
            <!-- The img src points to the multipart/x-mixed-replace stream -->
            <img src="{{ url_for('video_feed') }}">
          </body>
        </html>
    ''')

def generate_frames():
    global _global_camera_manager
    while True:
        if _global_camera_manager is None or not _global_camera_manager.is_streaming:
            time.sleep(0.1)
            continue
            
        # Get the current active subprocess
        proc = _global_camera_manager.stream_process
        if proc is None or proc.stdout is None:
            time.sleep(0.1)
            continue
            
        buffer = b''
        try:
            # Read stdout continuously as long as stream is ON and process hasn't been replaced
            while _global_camera_manager.is_streaming and proc == _global_camera_manager.stream_process:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    # Subprocess ended or pipe closed
                    break
                buffer += chunk
                
                # Find start (SOI) and end (EOI) of a JPEG frame
                a = buffer.find(b'\xff\xd8')
                b = buffer.find(b'\xff\xd9')
                
                if a != -1 and b != -1:
                    if b < a:
                        # Found end marker before start marker (started reading mid-frame). Discard.
                        buffer = buffer[b+2:]
                    else:
                        # Complete JPEG frame found
                        jpg = buffer[a:b+2]
                        buffer = buffer[b+2:]
                        
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')
        except Exception as e:
            time.sleep(0.1)

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
        os.makedirs(self.images_dir, exist_ok=True)
        
        # State tracking
        self._is_capturing = False # High-res upload active
        self._upload_lock = threading.Lock()
        
        # Streaming State
        self.is_streaming = False
        self.stream_process = None
        self._camera_lock = threading.Lock() # Protects stream_process and is_streaming
        
        # Start Flask server in background thread (starts immediately, but serves nothing until Stream is ON)
        self.flask_thread = threading.Thread(target=self._run_flask_server, daemon=True)
        self.flask_thread.start()

        self._init_firebase()

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
            "--framerate", "15",
            "--inline",
            "-o", "-" # Output to stdout
        ]
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

    def capture_and_upload_task(self):
        """Non-blocking public entry point."""
        with self._upload_lock:
            if self._is_capturing:
                self._log_info("High-res capture already in progress. Ignoring.")
                return
            self._is_capturing = True

        thread = threading.Thread(target=self._capture_and_upload_worker, daemon=True)
        thread.start()

    def _process_image_ocr(self, cv_image):
        """Semester 2 Pipeline Stub"""
        self._log_info("Running OPENCV_OCR pipeline...")
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        processed_image = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        detected_reading_str = "MOCK_OCR_1234.5"
        return processed_image, detected_reading_str

    def _capture_and_upload_worker(self):
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

            existing_files = glob.glob(os.path.join(self.images_dir, "*.jpg"))
            index = len(existing_files) + 1
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
            ref = db.reference('/meter_records')
            new_record_ref = ref.push()
            payload = {
                "record_id": new_record_ref.key,
                "filename": filename,
                "image_base64": data_uri,
                "timestamp": iso_timestamp,
                "meter_reading": meter_reading
            }
            new_record_ref.set(payload)
            self._log_info(f"Successfully pushed to RTDB! Record ID: {new_record_ref.key} | Mode: {self.processing_mode}")

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
