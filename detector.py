"""
detector.py - YOLOv8 Person Detection with Zone-based Intrusion Detection
"""

import cv2
import time
import numpy as np
from ultralytics import YOLO


class PersonDetector:
    PERSON_CLASS_ID = 0

    def __init__(self, model_path="yolov8n.pt"):
        print(f"[Detector] Loading YOLOv8 model: {model_path}...")
        self.model = YOLO(model_path)
        print("[Detector] Model loaded!")
        self.prev_time = 0
        self.fps = 0
        self.zone = []
        self.zone_set = False

    def set_zone(self, zone_points):
        self.zone = np.array(zone_points, dtype=np.int32)
        self.zone_set = True
        print(f"[Detector] Zone set: {zone_points}")

    def is_point_in_zone(self, point):
        if not self.zone_set:
            return False
        return cv2.pointPolygonTest(self.zone, point, False) >= 0

    def is_person_in_zone(self, bbox, frame_height, frame_width):
        if not self.zone_set:
            return False
        x1, y1, x2, y2 = bbox
        # Check: feet (bottom-center) AND body center — either inside zone
        feet = (int((x1 + x2) / 2), int(y2))
        center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
        return self.is_point_in_zone(feet) or self.is_point_in_zone(center)

    def calculate_fps(self):
        current_time = time.time()
        delta = current_time - self.prev_time
        self.prev_time = current_time
        if delta > 0:
            self.fps = 1 / delta
        return self.fps

    def process_frame(self, frame):
        alert_triggered = False
        detections = []

        # Lower confidence for better recall
        results = self.model(frame, verbose=False, conf=0.8)
        frame_height, frame_width = frame.shape[:2]

        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                confidence = float(box.conf[0])
                if cls_id != self.PERSON_CLASS_ID:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                in_zone = self.is_person_in_zone((x1, y1, x2, y2), frame_height, frame_width)

                if in_zone:
                    alert_triggered = True

                detections.append({
                    "bbox": (x1, y1, x2, y2),
                    "confidence": confidence,
                    "in_zone": in_zone
                })

                # RED box + thick for alert, GREEN for normal
                color = (0, 0, 255) if in_zone else (0, 255, 0)
                thickness = 3 if in_zone else 2
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

                label = f"ALERT {confidence:.2f}" if in_zone else f"Person {confidence:.2f}"
                label_w, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                cv2.rectangle(frame, (x1, y1 - 28), (x1 + label_w, y1), color, -1)
                cv2.putText(frame, label, (x1, y1 - 6),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Draw restricted zone (small polygon near shutter)
        if self.zone_set:
            cv2.polylines(frame, [self.zone], True, (0, 0, 255), 2)
            overlay = frame.copy()
            cv2.fillPoly(overlay, [self.zone], (0, 0, 255))
            cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)

        # FPS
        fps = self.calculate_fps()
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # LIVE indicator (blinking red)
        live_color = (0, 0, 255) if int(time.time() * 2) % 2 == 0 else (0, 0, 150)
        cv2.putText(frame, "[LIVE]", (frame_width - 100, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, live_color, 2)

        # Alert banner (centered)
        if alert_triggered:
            text = "ALERT: PERSON NEAR SHUTTER"
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.65
            thick = 2
            tw, th = cv2.getTextSize(text, font, scale, thick)[0]
            tx = (frame_width - tw) // 2
            ty = 50
            cv2.rectangle(frame, (tx - 8, ty - th - 8), (tx + tw + 8, ty + 8), (0, 0, 0), -1)
            cv2.rectangle(frame, (tx - 8, ty - th - 8), (tx + tw + 8, ty + 8), (0, 0, 255), 2)
            cv2.putText(frame, text, (tx, ty - 3), font, scale, (0, 0, 255), thick)

        return frame, alert_triggered, detections
