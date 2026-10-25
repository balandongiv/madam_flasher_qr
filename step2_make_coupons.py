r"""Step 2: build the student database, then the QR coupons.

1. Reads (paths in pipeline.yaml):
     eligible_xlsx   everyone eligible -> one coupon each
     responses_xlsx  "Will you be attending the ceremony?" -> CONFIRMED / NOT ATTENDING / NO RESPONSE
     datamerge_csv   written by step 1 -> id (Backup No.), program, year, name for students with a portrait
   and writes the student database to config.yaml paths.excel_file (the app reads it), plus
   <output_dir>\student_attention.txt with anything to check.
2. Generates <output_dir>\qr\, coupons.pdf (with the attendance status) and qr_test.pptx.

  python step2_make_coupons.py
  python step2_make_coupons.py --attendance confirmed      # coupons for confirmed students only
  python step2_make_coupons.py --rows 4                    # any generate_coupons.py option works
  python step2_make_coupons.py --db-only                   # only rebuild the student database
"""
from __future__ import annotations

import argparse
import sys

import generate_coupons
from app.data import load_config
from pipeline.settings import load_settings
from pipeline.students import build_from_settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Other options are passed to generate_coupons.py (see its --help).")
    ap.add_argument("--settings", help="path to pipeline.yaml")
    ap.add_argument("--config", help="path to config.yaml")
    ap.add_argument("--db-only", action="store_true", help="build the student database, skip the coupons")
    args, coupon_args = ap.parse_known_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    s = load_settings(args.settings)
    cfg = load_config(args.config)
    if cfg.images_dir.resolve() != s.indesign_images_dir.resolve():
        print(f"WARNING config.yaml images_dir ({cfg.images_dir}) differs from pipeline.yaml "
              f"indesign_images_dir ({s.indesign_images_dir}); the app shows images from config.yaml.")

    print(f"Eligible : {s.eligible_xlsx}\nResponses: {s.responses_xlsx}\nYearbook : {s.datamerge_csv}")
    df, notes, counts = build_from_settings(s)
    cfg.excel_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(cfg.excel_file, index=False, sheet_name="students")
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    (cfg.output_dir / "student_attention.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")

    print(f"\nStudent database: {cfg.excel_file}")
    print(f"  {len(df)} students | eligible list {counts['eligible']} | yearbook CSV {counts['yearbook_csv']} "
          f"| form responses {counts['responses']}")
    print("  attendance: " + " | ".join(f"{k.lower()} {counts.get(k, 0)}"
                                         for k in ("CONFIRMED", "NOT ATTENDING", "NO RESPONSE")))
    print(f"\nATTENTION ({len(notes)}):" if notes else "\nATTENTION: none")
    for m in notes:
        print(" -", m)
    if args.db_only:
        return 0
    print()
    return generate_coupons.main(([] if args.config is None else ["--config", args.config]) + coupon_args)


if __name__ == "__main__":
    sys.exit(main())
