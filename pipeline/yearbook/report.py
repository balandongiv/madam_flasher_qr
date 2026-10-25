"""Stage 8: CSV report, attention list and contact sheets with alignment guides."""
import csv
import math
import os
import re

import cv2
import numpy as np

COLS = ['status', 'original_file', 'output_file', 'photo_path', 'matric', 'name', 'email', 'programme', 'year',
        'faces', 'confidence', 'roll_deg', 'yaw_deg', 'pitch_deg', 'rotation_applied_deg',
        'scale', 'scale_eye_only', 'mouth_offset_px', 'padding_total', 'padding_head',
        'sharpness', 'manual_landmarks', 'warnings']

STATUS_COLOR = {'ok': (40, 160, 70), 'review': (230, 150, 0), 'fail': (210, 40, 40)}


def write_csv(rows, path):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:      # BOM so Excel shows names right
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def _year_key(y):
    m = re.search(r'\d+', y or '')
    return (int(m.group()) if m else 99, y or '')


def write_datamerge(rows, path, encoding='utf-16'):
    """InDesign Data Merge source: one row per student, sorted by programme, year, name.

    The "@" in "@photo_path" tells InDesign the field holds an image path.
    """
    students = [r for r in rows if not r.get('superseded')]
    students.sort(key=lambda r: ((r['programme'] or '').upper(), _year_key(r['year']), r['name']))
    with open(path, 'w', newline='', encoding=encoding) as f:
        w = csv.writer(f)
        w.writerow(['Program', 'year_of_study', 'student_id', 'name', 'id', 'quote', '@photo_path'])
        for i, r in enumerate(students, 1):
            w.writerow([r['programme'], r['year'], r['matric'], r['name'], i, r['quote'], r['photo_path']])
    return len(students)


def write_manual_template(rows, path):
    """Landmark override sheet for flagged photos; existing entries are kept."""
    keep = {}
    if os.path.exists(path):
        with open(path, newline='', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                keep[r['output_stem']] = r
    fields = ['output_stem', 'accept', 'left_eye_x', 'left_eye_y', 'right_eye_x', 'right_eye_y',
              'mouth_x', 'mouth_y', 'note']
    for r in rows:
        stem = os.path.splitext(r['output_file'])[0]
        if r['status'] != 'ok' and stem not in keep:
            keep[stem] = {'output_stem': stem, 'note': r['warnings'][:200]}
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for k in sorted(keep):
            w.writerow(keep[k])


def read_manual(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            out[r['output_stem']] = r
    return out


def contact_sheets(entries, cfg, out_dir, prefix='contact_sheet'):
    """entries: list of (rgb_or_None, label, status). Draws template eye/mouth guides on every tile."""
    t, e = cfg['template'], cfg['export']
    cols, rows_ = e['contact_columns'], e['contact_rows']
    tw = e['contact_thumb_width']
    k = tw / t['width']
    th = int(round(t['height'] * k))
    label_h, pad = 34, 8
    per = cols * rows_
    paths = []
    for page in range(math.ceil(len(entries) / per)):
        chunk = entries[page * per:(page + 1) * per]
        nrows = math.ceil(len(chunk) / cols)
        sheet = np.full((pad + nrows * (th + label_h + pad), pad + cols * (tw + pad), 3), 245, np.uint8)
        for i, (img, label, status) in enumerate(chunk):
            x = pad + (i % cols) * (tw + pad)
            y = pad + (i // cols) * (th + label_h + pad)
            if img is not None:
                sheet[y:y + th, x:x + tw] = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
            else:
                cv2.putText(sheet, 'NO IMAGE', (x + 60, y + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (120, 0, 0), 2)
            ey, my = int(y + t['eye_center_y'] * k), int(y + t['mouth_y'] * k)
            ex = int(x + t['eye_center_x'] * k)
            half = int(t['interocular'] * k / 2)
            cv2.line(sheet, (x, ey), (x + tw, ey), (0, 200, 255), 1)              # eye level
            cv2.line(sheet, (x, my), (x + tw, my), (255, 0, 200), 1)              # mouth level
            for cx in (ex - half, ex + half):
                cv2.drawMarker(sheet, (cx, ey), (0, 200, 255), cv2.MARKER_CROSS, 12, 1)
            cv2.drawMarker(sheet, (ex, my), (255, 0, 200), cv2.MARKER_CROSS, 12, 1)
            cv2.rectangle(sheet, (x - 2, y - 2), (x + tw + 1, y + th + 1), STATUS_COLOR[status], 3)
            for j, line in enumerate(_wrap(label, 30)[:2]):
                cv2.putText(sheet, line, (x, y + th + 14 + j * 14), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                            (30, 30, 30), 1, cv2.LINE_AA)
        p = os.path.join(out_dir, f'{prefix}_{page + 1:02d}.jpg')
        cv2.imwrite(p, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
        paths.append(p)
    return paths


def _wrap(s, n):
    words, lines, cur = s.split(), [], ''
    for wd in words:
        if len(cur) + len(wd) + 1 > n and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = f'{cur} {wd}'.strip()
    return lines + ([cur] if cur else [])
