"""Orchestrates: rename -> detect -> landmarks -> align -> crop -> QC -> export."""
import glob
import os
import time

import numpy as np

from . import align, imageio, naming, report
from .landmarks import Detector, Face


def _manual_face(row):
    def f(k):
        v = (row.get(k) or '').strip()
        return float(v) if v else None
    vals = [f(k) for k in ('left_eye_x', 'left_eye_y', 'right_eye_x', 'right_eye_y', 'mouth_x', 'mouth_y')]
    if None in vals[:4]:
        return None
    le, re_ = np.array(vals[0:2]), np.array(vals[2:4])
    if le[0] > re_[0]:
        le, re_ = re_, le
    iod = np.linalg.norm(re_ - le)
    mid = (le + re_) / 2
    perp = np.array([-(re_ - le)[1], (re_ - le)[0]]) / iod    # points down the face
    mouth = np.array(vals[4:6]) if None not in vals[4:6] else mid + 1.1 * iod * perp
    return Face(le, re_, mouth, mid - 1.2 * iod * perp, mid + 2.0 * iod * perp, np.zeros((0, 2)),
                confidence=1.0)


def run(cfg, only=None, log=print):
    p, e = cfg['paths'], cfg['export']
    out = p['output_dir']
    # Final portraits go directly in output_dir; problems are only listed in reports/report.csv.
    dirs = {'processed': out, 'reports': os.path.join(out, 'reports')}
    for d in list(dirs.values()) + [p['corrections_dir']]:
        os.makedirs(d, exist_ok=True)
    manual_path = os.path.join(dirs['reports'], 'manual_landmarks.csv')
    manual = report.read_manual(manual_path)

    items, notes = naming.plan(cfg)
    if only:
        keys = [o.lower() for o in only]
        items = [i for i in items if any(k in i.new_stem.lower() or k in i.original.lower() for k in keys)]
    ext = '.png' if e['format'] == 'png' else '.jpg'
    det = Detector(p['models_dir'], cfg['quality'])
    bg = cfg.get('background', {})
    remover = None
    if bg.get('enabled'):
        from .background import Remover
        remover = Remover(bg)
        log(f"  background removal: {bg['model']} on {remover.device}, mode {bg['mode']}")
    rows, sheet = [], []
    t0 = time.time()
    try:
        for n, it in enumerate(items, 1):
            src = it.source_path
            fixes = [f for f in glob.glob(os.path.join(p['corrections_dir'], it.new_stem + '.*'))
                     if f.lower().endswith(naming.IMAGE_EXT)]
            if fixes:
                src = fixes[0]
                it.warnings.append(('info', f'using corrected photo {os.path.basename(src)}'))
            for old in glob.glob(os.path.join(out, glob.escape(it.new_stem) + '.*')):   # stale output
                os.remove(old)
            row = {'original_file': it.original, 'matric': it.matric, 'name': it.name,
                   'email': it.email, 'programme': it.programme, 'manual_landmarks': '',
                   'year': it.year, 'quote': it.quote, 'superseded': it.superseded, 'photo_path': ''}
            warns = list(it.warnings)
            img = None
            try:
                rgb = imageio.load_rgb(src)
                m = manual.get(it.new_stem, {})
                face = _manual_face(m)
                if face is not None:
                    row['manual_landmarks'] = 'yes'
                else:
                    face, w = det.detect(rgb)
                    warns += w
                if face is not None:
                    res = align.warp(rgb, face, cfg)
                    if row['manual_landmarks']:
                        warns += [x for x in align.check(face, res, cfg)
                                  if 'confidence' not in x[1]]
                    else:
                        warns += align.check(face, res, cfg)
                    img = res.image
                    row.update(faces=face.face_count, confidence=f'{face.confidence:.2f}',
                               roll_deg=f'{face.roll:.1f}', yaw_deg=f'{face.yaw:.1f}',
                               pitch_deg=f'{face.pitch:.1f}', rotation_applied_deg=f'{-res.angle_deg:.2f}',
                               scale=f'{res.scale:.4f}', scale_eye_only=f'{res.scale_iod:.4f}',
                               mouth_offset_px=f'{res.mouth_dev:.0f}', padding_total=f'{res.pad_total:.3f}',
                               padding_head=f'{res.pad_head:.3f}', sharpness=f'{res.sharpness:.0f}')
            except Exception as ex:                       # unreadable file etc.
                warns.append(('fail', f'error: {ex}'))

            sev = {s for s, _ in warns}
            status = 'fail' if 'fail' in sev else 'review' if 'review' in sev else 'ok'
            if status == 'review' and str(manual.get(it.new_stem, {}).get('accept', '')).strip().lower() in ('yes', 'y', '1'):
                status = 'ok'
                warns.append(('info', 'accepted manually'))
            if img is not None and not it.superseded:
                if remover is not None:
                    try:
                        img = remover.apply(img)
                    except Exception as ex:
                        warns.append(('review', f'background removal failed: {ex}'))
                target = os.path.join(out, it.new_stem + ext)
                imageio.save(img, target, cfg)
                row['photo_path'] = os.path.normpath(target)
                row['output_file'] = os.path.relpath(target, out)
            else:
                row['output_file'] = ''      # older duplicate or no face: nothing exported
            row['status'] = status
            row['warnings'] = '; '.join(f'[{s}] {m}' for s, m in warns)
            rows.append(row)
            sheet.append((None if img is None else _flatten(img), f'{it.new_stem}', status))
            if n % 10 == 0 or n == len(items):
                log(f'  {n}/{len(items)} done ({time.time() - t0:.0f}s)')
    finally:
        det.close()

    stamp = '' if not only else time.strftime('_partial_%Y%m%d_%H%M%S')
    report.write_csv(rows, os.path.join(dirs['reports'], f'report{stamp}.csv'))
    report.write_manual_template(rows, manual_path)
    if not only:
        merge = os.path.join(out, e['datamerge_csv'])
        report.write_datamerge(rows, merge, e.get('datamerge_encoding', 'utf-16'))
    order = {'fail': 0, 'review': 1, 'ok': 2}
    sheet_sorted = sorted(sheet, key=lambda s: (order[s[2]], s[1]))
    for old in glob.glob(os.path.join(dirs['reports'], f'contact_sheet{stamp}_*.jpg')):
        os.remove(old)
    sheets = report.contact_sheets(sheet_sorted, cfg, dirs['reports'], f'contact_sheet{stamp}')

    attention = [m for s, m in notes if s == 'review'] + [m for s, m in notes if s == 'info']
    for r in rows:
        if r['status'] != 'ok':
            attention.append(f"{r['status'].upper():6} {r['output_file'] or r['original_file']}: "
                             + '; '.join(w.split('] ', 1)[1] for w in r['warnings'].split('; ')
                                         if w.startswith(('[review]', '[fail]'))))
    with open(os.path.join(dirs['reports'], f'attention{stamp}.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(attention) + '\n')
    counts = {k: sum(r['status'] == k for r in rows) for k in ('ok', 'review', 'fail')}
    return rows, counts, attention, sheets


def _flatten(img):
    """RGB for contact sheets: transparent areas shown on a grey checkerboard."""
    if img.shape[2] == 3:
        return img
    yy, xx = np.indices(img.shape[:2])
    board = np.where(((yy // 24 + xx // 24) % 2)[..., None] == 0, 205, 245).astype(np.float32)
    a = img[..., 3:4].astype(np.float32) / 255
    return (img[..., :3] * a + board * (1 - a)).round().astype(np.uint8)
