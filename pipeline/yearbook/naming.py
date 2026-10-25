"""Stage 1: filename validation and renaming plan (no files are touched here)."""
import os
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.heic', '.webp', '.bmp', '.tif', '.tiff')
# Words in uploaded file names that say nothing about who is in the photo.
GENERIC = {'JPG', 'JPEG', 'PNG', 'HEIC', 'IMG', 'IMAGE', 'WHATSAPP', 'PHOTO', 'PICTURE', 'GAMBAR', 'PASPORT',
           'PASSPORT', 'UNTITLED', 'DESIGN', 'DSC', 'PRINT', 'SCREENSHOT', 'COPY', 'EDITED', 'FINAL', 'FORMAL',
           'BIN', 'BINTI', 'ANAK', 'MAD', 'NEW', 'SALINAN'}

# Column headers in the Forms export are long; match them by prefix.
COLS = {
    'email': 'Email',
    'form_name': 'Name',
    'full_name': 'FULL NAME',
    'matric': 'MATRIC NUMBER',
    'programme': 'PROGRAMME',
    'year': 'YEAR OF STUDY',
    'photo': 'Please Upload a Photo',
    'quote': 'Please Provide a Quote',
    'completed': 'Completion time',
}


@dataclass
class Item:
    original: str                 # file name in input_dir
    new_stem: str = ''            # standardized name without extension
    matric: str = ''
    name: str = ''
    email: str = ''
    programme: str = ''
    year: str = ''
    quote: str = ''
    completed: object = None
    superseded: bool = False      # older submission of a student who submitted again
    source_path: str = ''
    warnings: list = field(default_factory=list)   # (severity, message)


def _clean(s):
    return re.sub(r'\s+', ' ', re.sub(r'[\\/:*?"<>|]', '', str(s or ''))).strip()


def _find_cols(header, cols=None):
    idx = {}
    for key, prefix in (cols or COLS).items():
        for i, h in enumerate(header):
            h = str(h or '').strip()
            if (h == 'Name') if key == 'form_name' else h.startswith(prefix):
                idx[key] = i
                break
        else:
            raise SystemExit(f'Column starting with "{prefix}" not found in responses Excel.')
    return idx


def plan(cfg):
    """Return (items, notes). items = files to process; notes = folder-level problems."""
    p, n = cfg['paths'], cfg['naming']
    src = p['input_dir']
    local = {f for f in os.listdir(src)
             if f.lower().endswith(IMAGE_EXT) and os.path.isfile(os.path.join(src, f))}
    items, notes = [], []
    if n['mode'] == 'responses':
        import openpyxl
        rows = list(openpyxl.load_workbook(p['responses_xlsx'], read_only=True).active.iter_rows(values_only=True))
        c = _find_cols(rows[0], n.get('columns'))
        for r in rows[1:]:
            if not r[c['photo']]:
                continue
            for url in re.split(r'[;\s]+(?=https?://)', str(r[c['photo']]).strip()):
                orig = unquote(url.strip().rsplit('/', 1)[-1])
                it = Item(orig, matric=str(r[c['matric']] or '').strip().upper().replace(' ', ''),
                          name=_clean(r[c['full_name']] or r[c['form_name']]),
                          email=str(r[c['email']] or ''), programme=_clean(r[c['programme']]),
                          year=_clean(r[c['year']]), quote=' '.join(str(r[c['quote']] or '').split()),
                          completed=r[c['completed']])
                account = _clean(r[c['form_name']]).upper()
                acc_words = set(re.findall(r'[A-Z]{3,}', account)) - GENERIC
                if acc_words and not acc_words & set(re.findall(r'[A-Z]{3,}', it.name.upper())):
                    it.warnings.append(('review', f'submitted from another account ({account}) - '
                                                  f'confirm the photo shows {it.name.upper()}'))
                if orig not in local:
                    notes.append(('review', f'{it.name} ({it.matric}): uploaded "{orig}" is missing from the '
                                            f'input folder - download it from the responses Excel link.'))
                    continue
                items.append(it)
        used = {i.original for i in items}
        for f in sorted(local - used):
            notes.append(('info', f'"{f}" matches no form response (older/replaced upload?) - skipped.'))
    else:
        for f in sorted(local):
            stem = os.path.splitext(f)[0]
            m = re.match(r'\(?([A-Za-z]{2}\d{8})\)?[_\s-]*(.*)', stem)
            items.append(Item(f, matric=m.group(1).upper() if m else '', name=_clean(m.group(2) if m else stem)))

    if n.get('uppercase_name', True):
        for it in items:
            it.name = it.name.upper()

    rx = re.compile(n['matric_regex'])
    by_matric, used_stems = {}, set()
    for it in items:
        it.source_path = os.path.join(src, it.original)
        if not it.matric:
            it.warnings.append(('review', 'missing matric number'))
        elif not rx.match(it.matric):
            it.warnings.append(('review', f'matric "{it.matric}" does not match expected format'))
        else:
            by_matric.setdefault(it.matric, []).append(it)
        stem = _clean(n['pattern'].format(matric=it.matric or 'NOMATRIC', name=it.name)).strip('_ ')
        base, k = stem, 2
        while stem.lower() in used_stems:          # Windows names are case-insensitive
            stem = f'{base} ({k})'
            k += 1
        if stem != base:
            it.warnings.append(('review', f'name conflict - saved as "{stem}"'))
        used_stems.add(stem.lower())
        it.new_stem = stem
    for matric, group in by_matric.items():
        if len(group) > 1:
            # Keep the latest submission; older ones are reported but not exported.
            latest = max(group, key=lambda g: str(g.completed or ''))
            for it in group:
                if it is latest:
                    it.warnings.append(('info', f'{len(group)} submissions for {matric} - latest one used'))
                else:
                    it.superseded = True
                    it.warnings.append(('review', f'older duplicate submission for {matric} - not used'))
        names = {g.name for g in group}
        if len(names) > 1:
            for it in group:
                it.warnings.append(('review', f'matric {matric} used with different names: {", ".join(sorted(names))}'))

    # The latest submission gets the clean name; older ones get "(older N)" and are not used in the layout.
    for group in by_matric.values():
        if len(group) > 1:
            k = 1
            for it in group:
                base = re.sub(r' \(\d+\)$', '', it.new_stem)
                it.warnings = [w for w in it.warnings if not w[1].startswith('name conflict')]
                if it.superseded:
                    it.new_stem = f'{base} (older {k})'
                    k += 1
                else:
                    it.new_stem = base

    # Original file name hints at a different person than the submitter (e.g. wrong photo uploaded).
    for it in items:
        m = re.match(r'\(?([A-Za-z]{2}\d{8})', it.original)
        if m and it.matric and m.group(1).upper() != it.matric:
            it.warnings.append(('review', f'file name has matric {m.group(1).upper()} but submitter typed {it.matric}'))
        # Forms appends the submitter's (truncated) account name after the last "_";
        # earlier words in the file name are what the student typed when renaming.
        stem = os.path.splitext(it.original)[0]
        parts = stem.split('_')
        typed = ' '.join(parts[:-1]) if len(parts) > 1 else ''
        # Only whole alphabetic words count, so camera/UUID names ("DSC 6942print", "fb60d0e3-...") are ignored.
        words = {w for w in re.split(r'[^A-Z0-9]+', typed.upper()) if re.fullmatch(r'[A-Z]{3,}', w)} - GENERIC
        if len(words) >= 2 and not words & set(re.findall(r'[A-Z]{3,}', it.name.upper())):
            it.warnings.append(('review', f'file name mentions "{typed}" but submitted by {it.name} - wrong photo?'))
    return items, notes
