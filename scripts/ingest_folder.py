from __future__ import annotations

import argparse
from pathlib import Path

from tqdm import tqdm

from enterprise_rag.ingestion.ingest import ingest_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--recursive", action="store_true", default=True)
    args = ap.parse_args()

    folder = Path(args.folder)
    patterns = ["*.pdf", "*.docx", "*.xlsx", "*.xlsm", "*.html", "*.htm", "*.aspx"]

    paths: list[Path] = []
    for pat in patterns:
        paths.extend(folder.rglob(pat) if args.recursive else folder.glob(pat))
    paths = sorted(set(paths))

    ok = 0
    for p in tqdm(paths, desc="Ingest", unit="file"):
        try:
            ingest_path(str(p))
            ok += 1
        except Exception as e:
            print(f"[ERROR] {p}: {e}")

    print(f"Done. Ingested {ok}/{len(paths)} files.")


if __name__ == "__main__":
    main()
