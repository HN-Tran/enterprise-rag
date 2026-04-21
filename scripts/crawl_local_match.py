"""Match local files to web URLs and ingest with titles from web."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from tqdm import tqdm

from enterprise_rag.config import settings
from enterprise_rag.ingestion.ingest import ingest_path

# Supported file types (same as ingest_folder.py)
FILE_TYPES = {
    "html": ["*.html", "*.htm"],
    "pdf": ["*.pdf"],
    "docx": ["*.docx"],
    "xlsx": ["*.xlsx", "*.xls", "*.xlsm"],
}
ALL_PATTERNS = [p for patterns in FILE_TYPES.values() for p in patterns]


def build_url(local_path: Path, local_base: Path, web_base: str, path_mappings: dict[str, str]) -> str:
    """Convert local path to web URL with path mappings.

    Args:
        local_path: Full path to local file
        local_base: Base directory for local files
        web_base: Base URL for web
        path_mappings: Dict of {local_subfolder: web_subfolder} renames

    Returns:
        Constructed web URL
    """
    # Get relative path from local base
    rel_path = local_path.relative_to(local_base)

    # Apply path mappings (subfolder renames)
    rel_str = str(rel_path)
    for local_name, web_name in path_mappings.items():
        rel_str = rel_str.replace(local_name, web_name)

    # Convert backslashes to forward slashes (Windows paths)
    rel_str = rel_str.replace("\\", "/")

    # Join with web base
    return urljoin(web_base.rstrip("/") + "/", rel_str)


def fetch_title(url: str, client: httpx.Client) -> str | None:
    """Fetch page and extract title.

    Returns:
        Title string or None if fetch failed or no title found
    """
    try:
        resp = client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        return None
    except Exception:
        return None


def check_url_exists(url: str, client: httpx.Client) -> bool:
    """Check if URL exists (HEAD request)."""
    try:
        resp = client.head(url)
        return resp.status_code == 200
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Match local files to web URLs and ingest with titles from web"
    )
    ap.add_argument(
        "local_dir",
        type=Path,
        help="Local directory containing files to match",
    )
    ap.add_argument(
        "web_base",
        help="Base URL for web (e.g., https://example.com/docs/)",
    )
    ap.add_argument(
        "--type",
        choices=list(FILE_TYPES.keys()),
        default="html",
        help="File type to process (default: html)",
    )
    ap.add_argument(
        "--mapping",
        "-m",
        action="append",
        default=[],
        help="Path mapping as 'local_name=web_name' (can specify multiple)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even if file content hasn't changed",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matches without ingesting",
    )
    ap.add_argument(
        "--skip-missing",
        action="store_true",
        help="Skip files whose URLs return 404 (not linked on web)",
    )
    ap.add_argument(
        "--category",
        "-c",
        help="Category to assign to all ingested documents",
    )
    args = ap.parse_args()

    if not args.local_dir.exists():
        print(f"Error: Directory not found: {args.local_dir}")
        sys.exit(1)

    # Parse path mappings
    path_mappings = {}
    for mapping in args.mapping:
        if "=" not in mapping:
            print(f"Error: Invalid mapping format '{mapping}', expected 'local=web'")
            sys.exit(1)
        local_name, web_name = mapping.split("=", 1)
        path_mappings[local_name] = web_name

    # Find all matching files (like ingest_folder.py)
    patterns = FILE_TYPES[args.type]
    local_files: list[Path] = []
    for pat in patterns:
        local_files.extend(args.local_dir.rglob(pat))
    local_files = sorted(set(local_files))

    if not local_files:
        print(f"No {args.type} files found in {args.local_dir}")
        sys.exit(0)

    print(f"Found {len(local_files)} {args.type} files")
    if path_mappings:
        print(f"Path mappings: {path_mappings}")

    # Setup HTTP client
    client_kwargs = {
        "timeout": settings.CRAWLER_TIMEOUT,
        "follow_redirects": True,
        "headers": {"User-Agent": settings.CRAWLER_USER_AGENT},
    }
    if not settings.CRAWLER_VERIFY_SSL:
        client_kwargs["verify"] = False

    ingested = 0
    skipped_404 = 0
    failed = 0

    with httpx.Client(**client_kwargs) as client:
        pbar = tqdm(local_files, desc="Processing", unit="file", disable=args.dry_run)
        for local_path in pbar:
            web_url = build_url(local_path, args.local_dir, args.web_base, path_mappings)
            pbar.set_postfix_str(local_path.name[:30])

            if args.dry_run:
                # In dry-run, just show URL mapping
                exists = check_url_exists(web_url, client)
                status = "OK" if exists else "404"
                print(f"[{status}] {local_path.name}")
                print(f"  -> {web_url}")
                continue

            # Fetch title from web
            title = fetch_title(web_url, client)

            if title is None and args.skip_missing:
                skipped_404 += 1
                continue

            # Ingest local file
            try:
                result = ingest_path(
                    str(local_path),
                    title_override=title,
                    source_url=args.web_base,
                    download_url=web_url,
                    category=args.category,
                    force=args.force,
                )
                ingested += 1

            except Exception as e:
                tqdm.write(f"[ERROR] {local_path.name}: {e}")
                failed += 1

    # Summary
    if not args.dry_run:
        print(f"\nDone. Ingested {ingested}/{len(local_files)} files.")
        if skipped_404:
            print(f"  Skipped (404): {skipped_404}")
        if failed:
            print(f"  Failed: {failed}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
