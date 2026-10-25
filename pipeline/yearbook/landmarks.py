"""Stage 2-3: face detection and landmark extraction with MediaPipe."""
import math
import os
from dataclasses import dataclass

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

# MediaPipe Face Mesh indices (478-point model with irises).
IRIS_A, IRIS_B = 468, 473
MOUTH = (13, 14, 61, 291)          # inner upper/lower lip, mouth corners
FOREHEAD, CHIN, NOSE_TIP = 10, 152, 1
DETECT_MAX_SIDE = 1600             # detection runs on a downscaled copy for speed


@dataclass
class Face:
    left_eye: np.ndarray           # image-left eye (smaller x), source pixels
    right_eye: np.ndarray
    mouth: np.ndarray
    forehead: np.ndarray
    chin: np.ndarray
    points: np.ndarray             # all 478 points, source pixels
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    blink: float = 0.0
    confidence: float = 0.0
    face_count: int = 1


class Detector:
    def __init__(self, models_dir, cfg_q):
        self.q = cfg_q
        self.landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=os.path.join(models_dir, 'face_landmarker.task')),
            num_faces=4, output_face_blendshapes=True, output_facial_transformation_matrixes=True,
            min_face_detection_confidence=0.3, min_face_presence_confidence=0.3))
        self.detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=os.path.join(models_dir, 'blaze_face_short_range.tflite')),
            min_detection_confidence=0.2))

    def close(self):
        self.landmarker.close()
        self.detector.close()

    def detect(self, rgb):
        """Return (Face or None, list of (severity, message))."""
        h, w = rgb.shape[:2]
        k = min(1.0, DETECT_MAX_SIDE / max(h, w))
        small = cv2.resize(rgb, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else rgb
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(small))
        res = self.landmarker.detect(image)
        if not res.face_landmarks:
            return None, [('fail', 'no face detected')]

        faces = []
        for i, lm in enumerate(res.face_landmarks):
            pts = np.array([[p.x * w, p.y * h] for p in lm], dtype=np.float64)
            faces.append((np.linalg.norm(pts[IRIS_A] - pts[IRIS_B]), i, pts))
        faces.sort(key=lambda f: -f[0])
        iod, idx, pts = faces[0]
        warnings = []
        others = [f for f in faces[1:] if f[0] >= self.q['second_face_ratio'] * iod]
        if 1 + len(others) > self.q['max_faces']:
            warnings.append(('review', f'{1 + len(others)} faces detected'))

        a, b = pts[IRIS_A], pts[IRIS_B]
        le, re_ = (a, b) if a[0] < b[0] else (b, a)
        face = Face(le, re_, pts[list(MOUTH)].mean(axis=0), pts[FOREHEAD], pts[CHIN], pts,
                    face_count=1 + len(others))

        m = np.array(res.facial_transformation_matrixes[idx])[:3, :3]
        face.pitch = math.degrees(math.atan2(m[2, 1], m[2, 2]))
        face.yaw = math.degrees(math.asin(max(-1.0, min(1.0, -m[2, 0]))))
        face.roll = math.degrees(math.atan2(re_[1] - le[1], re_[0] - le[0]))
        bs = {c.category_name: c.score for c in res.face_blendshapes[idx]}
        face.blink = max(bs.get('eyeBlinkLeft', 0), bs.get('eyeBlinkRight', 0))

        det = self.detector.detect(image)
        face.confidence = max((d.categories[0].score for d in det.detections), default=0.0)
        return face, warnings
