r"""Step 1: turn the Forms photo uploads into clean, aligned portraits.

Reads the photos and the responses Excel from pipeline.yaml `question`, then renames each photo to
<MATRIC>.png, aligns the face (eyes and mouth at the same place), removes the background on the GPU and writes:
  <clean_images_dir>\<MATRIC>.png           e.g. D:\book\new_name\BS25110295.png
  <clean_images_dir>\yearbook_datamerge.csv InDesign Data Merge source; its `id` is the coupon Backup No.
  <clean_images_dir>\reports\               report.csv, attention.txt, contact sheets
Originals are never changed. Next: merge in InDesign, export to indesign_images_dir, then run step 2.

Needs the image packages (requirements-images.txt), e.g. the conda env:
  conda activate madam-flasher-qr
  python step1_clean_images.py
  python step1_clean_images.py --only BS23110116 "TAN DEE"   # reprocess some photos (CSV not rewritten)
  python step1_clean_images.py --keep-bg                     # skip background removal
  python step1_clean_images.py --output-dir D:\tmp\test      # write somewhere else (for testing)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pipeline.settings import load_settings, readable_copy


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settings", help="path to pipeline.yaml")
    ap.add_argument("--only", nargs="+", help="process only photos whose name contains any of these texts")
    ap.add_argument("--keep-bg", action="store_true", help="do not remove the background this run")
    ap.add_argument("--output-dir", help="write portraits and reports here instead of clean_images_dir")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    try:
        from pipeline.yearbook.run import run
    except ImportError as e:
        print(f"ERROR: {e}\nStep 1 needs the image packages: pip install -r requirements-images.txt "
              f"(or: conda activate madam-flasher-qr)", file=sys.stderr)
        return 1

    s = load_settings(args.settings)
    cfg = s.yearbook_config()
    if args.keep_bg:
        cfg["background"]["enabled"] = False
    if args.output_dir:
        out = Path(args.output_dir).resolve()
        cfg["paths"]["output_dir"] = str(out)
        cfg["paths"]["corrections_dir"] = str(out / "corrections")
    print(f"Input : {s.question_dir}\nOutput: {cfg['paths']['output_dir']}")
    # the responses Excel may be open in Excel (locked): read a copy
    with readable_copy(s.responses_xlsx) as tmp:
        cfg["paths"]["responses_xlsx"] = str(tmp)
        rows, counts, attention, sheets = run(cfg, args.only)
    out_dir = cfg["paths"]["output_dir"]
    print(f"\nDone: {len(rows)} photos | ok {counts['ok']} | needs review {counts['review']} | failed {counts['fail']}")
    print(f"Contact sheets: {len(sheets)} in {os.path.join(out_dir, 'reports')}")
    print(f"\nATTENTION ({len(attention)}):" if attention else "\nATTENTION: none")
    for m in attention:
        print(" -", m)
    print("\nNext: InDesign Data Merge -> export images to", s.indesign_images_dir, "-> python step2_make_coupons.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
