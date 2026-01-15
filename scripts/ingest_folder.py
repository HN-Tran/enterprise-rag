from __future__ import annotations

import argparse
from pathlib import Path

from tqdm import tqdm

from enterprise_rag.ingestion.ingest import ingest_path

# Supported file types
FILE_TYPES = {
    "pdf": ["*.pdf"],
    "docx": ["*.docx"],
    "xls": ["*.xls"],
    "xlsx": ["*.xlsx", "*.xlsm"],
    "html": ["*.html", "*.htm", "*.aspx"],
}
ALL_PATTERNS = [p for patterns in FILE_TYPES.values() for p in patterns]


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest documents into Enterprise RAG")
    ap.add_argument("--folder", required=True, help="Folder to ingest from")
    ap.add_argument("--recursive", action="store_true", default=True, help="Include subfolders")
    ap.add_argument(
        "--type",
        choices=list(FILE_TYPES.keys()),
        help="Only ingest specific file type (pdf, docx, xlsx, html)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even if file content hasn't changed",
    )
    args = ap.parse_args()

    folder = Path(args.folder)

    # Select patterns based on --type argument
    if args.type:
        patterns = FILE_TYPES[args.type]
        print(f"Filtering for: {args.type} files only")
    else:
        patterns = ALL_PATTERNS

    paths: list[Path] = []
    for pat in patterns:
        paths.extend(folder.rglob(pat) if args.recursive else folder.glob(pat))
    paths = sorted(set(paths))

    if not paths:
        print(f"No matching files found in {folder}")
        return

    print(f"Found {len(paths)} files to ingest")

    ok = 0
    for p in tqdm(paths, desc="Ingest", unit="file"):
        try:
            ingest_path(str(p), force=args.force)
            ok += 1
        except Exception as e:
            print(f"[ERROR] {p}: {e}")

    print(f"Done. Ingested {ok}/{len(paths)} files.")


if __name__ == "__main__":
    main()
