"""Stages 4-7: eye-level rotation, scale normalization, reference alignment, standardized crop.

Only a similarity transform (rotation + uniform scale + translation) is applied,
so facial proportions are never distorted.
"""
import math
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Result:
    image: np.ndarray
    matrix: np.ndarray        # 2x3, source px -> output px
    angle_deg: float          # rotation applied
    scale: float              # total scale applied (output px per source px)
    scale_iod: float          # scale from eye distance alone
    mouth_out: np.ndarray     # mouth centre in output px
    mouth_dev: float          # vertical distance from template mouth_y
    head_top: float           # estimated head top (incl. hair) in output px
    chin_out: np.ndarray
    pad_total: float          # fraction of output not covered by the source photo
    pad_head: float           # same, inside the head region
    sharpness: float


def similarity(face, t):
    """Return (2x3 matrix, angle_deg, scale, scale_iod)."""
    le, re_, mouth = face.left_eye, face.right_eye, face.mouth
    eye_mid = (le + re_) / 2
    d = re_ - le
    theta = math.atan2(d[1], d[0])
    iod = float(np.hypot(*d))
    # Eye-to-mouth distance measured perpendicular to the eye line (tilt-independent).
    v = mouth - eye_mid
    em = abs(-math.sin(theta) * v[0] + math.cos(theta) * v[1])

    s_iod = t['interocular'] / iod
    s_em = (t['mouth_y'] - t['eye_center_y']) / em if em > 1 else s_iod
    w = t['mouth_weight']
    s = math.exp((1 - w) * math.log(s_iod) + w * math.log(s_em))
    dev = t['max_scale_deviation']
    s = min(max(s, s_iod * (1 - dev)), s_iod * (1 + dev))

    c, sn = math.cos(-theta), math.sin(-theta)
    a = s * np.array([[c, -sn], [sn, c]])
    tvec = np.array([t['eye_center_x'], t['eye_center_y']]) - a @ eye_mid
    return np.hstack([a, tvec[:, None]]), math.degrees(theta), s, s_iod


def _apply(m, p):
    return m[:, :2] @ np.asarray(p, dtype=np.float64) + m[:, 2]


def warp(rgb, face, cfg):
    t, cr = cfg['template'], cfg['crop']
    W, H = t['width'], t['height']
    m, angle, s, s_iod = similarity(face, t)

    # Large downscales: resample with INTER_AREA first to avoid aliasing, then warp at ~1:1.
    src, mm = rgb, m.copy()
    if s < 0.9:
        src = cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        mm[:, :2] = m[:, :2] / s
    if cr['fill'] == 'color':
        border, value = cv2.BORDER_CONSTANT, tuple(int(x) for x in cr['fill_color'])
    else:
        border, value = cv2.BORDER_REPLICATE, 0
    out = cv2.warpAffine(src, mm, (W, H), flags=cv2.INTER_LANCZOS4, borderMode=border, borderValue=value)
    out = np.clip(out, 0, 255).astype(np.uint8)

    mask = cv2.warpAffine(np.full(src.shape[:2], 255, np.uint8), mm, (W, H), flags=cv2.INTER_NEAREST,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    iod_out = t['interocular']
    mouth_out = _apply(m, face.mouth)
    chin_out = _apply(m, face.chin)
    head_top = _apply(m, face.forehead)[1] - cr['hair_allowance'] * iod_out

    # Head region: ellipse-ish box around the face, from head top to chin.
    x0, x1 = int(max(0, t['eye_center_x'] - 1.6 * iod_out)), int(min(W, t['eye_center_x'] + 1.6 * iod_out))
    y0, y1 = int(max(0, head_top)), int(min(H, chin_out[1]))
    head = mask[y0:y1, x0:x1]
    pad_head = float((head == 0).mean()) if head.size else 1.0
    pad_total = float((mask == 0).mean())

    fy0, fy1 = int(max(0, t['eye_center_y'] - 0.5 * iod_out)), int(min(H, mouth_out[1] + 0.3 * iod_out))
    fx0, fx1 = int(max(0, t['eye_center_x'] - iod_out)), int(min(W, t['eye_center_x'] + iod_out))
    gray = cv2.cvtColor(out[fy0:fy1, fx0:fx1], cv2.COLOR_RGB2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray.size else 0.0

    return Result(out, m, angle, s, s_iod, mouth_out, float(mouth_out[1] - t['mouth_y']),
                  float(head_top), chin_out, pad_total, pad_head, sharp)


def check(face, res, cfg):
    """Return list of (severity, message) for the aligned result."""
    q, cr, t = cfg['quality'], cfg['crop'], cfg['template']
    w = []
    if face.confidence < q['min_face_confidence']:
        w.append(('review', f'low face-detection confidence {face.confidence:.2f}'))
    if abs(face.roll) > q['max_roll_deg']:
        w.append(('review', f'strong head tilt {face.roll:.0f} deg (corrected, check look)'))
    if abs(face.yaw) > q['max_yaw_deg']:
        w.append(('review', f'face turned sideways (yaw {face.yaw:.0f} deg)'))
    if abs(face.pitch) > q['max_pitch_deg']:
        w.append(('review', f'head tilted up/down (pitch {face.pitch:.0f} deg)'))
    if face.blink > q['max_blink']:
        w.append(('review', f'eyes may be closed (blink {face.blink:.2f})'))
    if res.scale > q['max_upscale']:
        w.append(('review' if q.get('flag_low_resolution', True) else 'info', f'low resolution source: upscaled x{res.scale:.2f}'))
    elif res.scale > 1.0:
        w.append(('info', f'slight upscale x{res.scale:.2f}'))
    if res.sharpness < q['min_sharpness']:
        w.append(('review', f'face looks blurry (sharpness {res.sharpness:.0f})'))
    if res.pad_head > cr['max_padding_head']:
        w.append(('review', f'head/hair cut off in source ({res.pad_head:.0%} of head area filled)'))
    if res.pad_total > cr['max_padding_total']:
        w.append(('review' if q.get('flag_tight_crop', True) else 'info', f'source photo too tightly cropped ({res.pad_total:.0%} of portrait filled)'))
    elif res.pad_total > 0.01:
        w.append(('info', f'{res.pad_total:.0%} of portrait edge extended from photo border'))
    if res.head_top < cr['min_top_margin']:
        w.append(('review', f'little space above head ({res.head_top:.0f}px)'))
    if t['height'] - res.chin_out[1] < cr['min_chin_to_bottom']:
        w.append(('review', 'little room below chin for shoulders'))
    if abs(res.mouth_dev) > q['mouth_tolerance']:
        w.append(('info', f'mouth {res.mouth_dev:+.0f}px from template (natural anatomy kept)'))
    return w
