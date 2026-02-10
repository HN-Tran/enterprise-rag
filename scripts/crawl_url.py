"""Crawl web pages to discover and ingest document links."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from enterprise_rag.ingestion.crawler import (
    crawl_and_ingest,
    crawl_and_ingest_pattern,
    crawl_and_ingest_recursive,
    preview_links,
    preview_links_recursive,
)
from enterprise_rag.ingestion.versioning import mark_unseen_orphaned


def _handle_recursive_dry_run(url: str, args: argparse.Namespace) -> int:
    """Run recursive dry-run preview and print results. Returns discovered count."""
    result = preview_links_recursive(
        url,
        max_depth=args.depth,
        max_pages=args.max_pages,
    )

    if "error" in result:
        print(f"[ERROR] {result['error']}")
        return 0

    pages = result.get("pages", [])
    doc_links = result.get("doc_links", [])
    category = result.get("category")

    cat_info = f" (category: {category})" if category else ""
    print(f"\nVisited {result['pages_visited']} page(s){cat_info}:")

    for p in pages:
        depth_prefix = "  " * p["depth"]
        title = p.get("title") or "(no title)"
        if p.get("error"):
            print(f"  {depth_prefix}[ERROR] {p['url']}: {p['error']}")
        else:
            print(
                f"  {depth_prefix}[d={p['depth']}] {title} "
                f"({p['doc_links']} docs, {p['page_links']} pages)"
            )
            print(f"  {depth_prefix}       {p['url']}")

    if doc_links:
        print(f"\nDiscovered {len(doc_links)} document link(s):\n")
        for i, link in enumerate(doc_links, 1):
            title = link.get("title") or "(no title)"
            ext = link.get("extension", "")
            print(f"  {i}. [{ext.upper()[1:]}] {title}")
            print(f"      {link['url']}")
            print(f"      Found on: {link['found_on']}")
            print()

    if result.get("truncated"):
        print(
            f"  (truncated: {result['remaining_in_queue']} page(s) "
            f"remaining in queue, increase --max-pages to continue)"
        )

    return len(doc_links)


def _handle_recursive_ingest(
    url: str, args: argparse.Namespace,
) -> tuple[int, int, int, int, list[str]]:
    """Run recursive crawl+ingest and print progress.

    Returns (ingested, skipped, failed, orphaned, seen_doc_ids).
    """
    total_ingested = 0
    total_skipped = 0
    total_failed = 0
    total_orphaned = 0
    seen_doc_ids: list[str] = []

    for event in crawl_and_ingest_recursive(
        url,
        max_depth=args.depth,
        download_dir=args.download_dir,
        max_pages=args.max_pages,
    ):
        event_type = event.get("type")

        if event_type == "page_start":
            if not args.quiet:
                print(
                    f"\n  Page {event['page_num']}/{event['max_pages']} "
                    f"(depth={event['depth']}, queue={event['queue_size']})"
                )
                print(f"  URL: {event['url']}")

        elif event_type == "page_error":
            print(f"  [ERROR] Page failed: {event['error']}")
            print(f"          URL: {event['url']}")

        elif event_type == "page_done":
            cat_info = f" [{event['category']}]" if event.get("category") else ""
            title = event.get("page_title") or "(no title)"
            print(
                f"  [{title}]{cat_info} "
                f"- {event['doc_link_count']} doc(s), "
                f"{event['page_link_count']} page link(s)"
            )

        elif event_type == "page_ingest_done":
            if not args.quiet:
                if event.get("status") == "unchanged":
                    print(f"    [PAGE SKIP] {event.get('title') or 'Untitled'} (unchanged)")
                else:
                    print(f"    [PAGE OK] {event.get('title') or 'Untitled'}")

        elif event_type == "page_ingest_error":
            print(f"    [PAGE FAIL] HTML ingest: {event['error']}")

        elif event_type == "download_start":
            if not args.quiet:
                print(f"    [{event['index']}/{event['total']}] Downloading...")

        elif event_type == "download_error":
            print(f"    [FAILED] Download: {event['error']}")
            print(f"             URL: {event['url']}")

        elif event_type == "download_done":
            if not args.quiet:
                print(f"             Downloaded: {event['url'][:60]}...")

        elif event_type == "not_modified":
            print(f"    [304] Not modified: {event['url'][:50]}...")

        elif event_type == "ingest_start":
            if not args.quiet:
                print("             Ingesting...")

        elif event_type == "ingest_error":
            print(f"    [FAILED] Ingest: {event['error']}")

        elif event_type == "ingest_done":
            archived_status = "" if event.get("is_current", True) else " [archived]"
            cat_suffix = f" [{event['category']}]" if event.get("category") else ""
            if event.get("status") == "unchanged":
                print(f"    [SKIP] {event.get('title') or 'Untitled'} (unchanged){cat_suffix}")
            else:
                print(f"    [OK] {event.get('title') or 'Untitled'}{archived_status}{cat_suffix}")
                print(f"         doc_id: {event['doc_id']}")

        elif event_type == "pages_enqueued":
            if not args.quiet:
                print(f"    Enqueued {event['count']} page link(s) (queue: {event['queue_size']})")

        elif event_type == "max_pages_reached":
            print(
                f"\n  Max pages reached ({event['visited']}). "
                f"{event['remaining_in_queue']} page(s) not visited."
            )

        elif event_type == "orphaned":
            if event["count"] > 0:
                print(f"\n  Marked {event['count']} previously-ingested document(s) as orphaned")

        elif event_type == "done":
            ingested = event.get("ingested", [])
            failed = event.get("failed", [])
            orphaned = event.get("orphaned_count", 0)
            pages_visited = event.get("pages_visited", 0)

            skipped = [
                i for i in ingested if i.get("status") in ("not_modified", "unchanged")
            ]
            actually_ingested = [
                i for i in ingested if i.get("status") not in ("not_modified", "unchanged")
            ]

            total_ingested = len(actually_ingested)
            total_skipped = len(skipped)
            total_failed = len(failed)
            total_orphaned = orphaned

            for item in ingested:
                if item.get("doc_id"):
                    seen_doc_ids.append(item["doc_id"])

            print(f"\nSummary for {url}:")
            print(f"  Pages visited: {pages_visited}")
            print(f"  Ingested: {total_ingested}")
            if total_skipped:
                print(f"  Skipped:  {total_skipped} (unchanged)")
            print(f"  Failed:   {total_failed}")
            if total_orphaned > 0:
                print(f"  Orphaned: {total_orphaned}")

    return total_ingested, total_skipped, total_failed, total_orphaned, seen_doc_ids


def _handle_pattern_dry_run(args: argparse.Namespace) -> int:
    """Dry-run pattern crawl: fetch pages and report hit/miss without ingesting.

    Returns total number of hits.
    """
    import httpx

    from enterprise_rag.config import settings
    from enterprise_rag.ingestion.crawler import _get_http_client_kwargs

    pattern_url: str = args.pattern
    start: int = args.start
    end: int = args.end
    pad_width: int = args.pad_width
    not_found_text: str = args.not_found_text
    max_gaps: int = args.max_gaps

    total_hits = 0
    consecutive_misses = 0
    client_kwargs = _get_http_client_kwargs()

    for num in range(start, end + 1):
        pid = str(num).zfill(pad_width)
        url = pattern_url.replace("{}", pid)

        # Politeness delay (skip first)
        if num > start:
            import time

            time.sleep(settings.CRAWLER_PAGE_DELAY)

        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.get(url)

                if response.status_code != 200:
                    consecutive_misses += 1
                    print(f"  [MISS] {pid} - HTTP {response.status_code}  ({consecutive_misses} consecutive)")
                    if consecutive_misses >= max_gaps:
                        print(f"\n  Stopped: {max_gaps} consecutive misses reached at {pid}")
                        break
                    continue

                # Check not-found text in main page + iframe content
                from urllib.parse import urljoin
                from bs4 import BeautifulSoup

                body_text = response.text
                soup = BeautifulSoup(response.content, "html.parser")
                for iframe in soup.find_all("iframe", src=True):
                    try:
                        iframe_url = urljoin(url, iframe["src"])
                        iframe_resp = client.get(iframe_url)
                        iframe_resp.raise_for_status()
                        body_text += iframe_resp.text
                    except Exception:
                        pass
                nf_matched = not_found_text in body_text
                if not nf_matched and "{}" in not_found_text:
                    nf_matched = (
                        not_found_text.replace("{}", str(num)) in body_text
                        or not_found_text.replace("{}", pid) in body_text
                    )
                if nf_matched:
                    consecutive_misses += 1
                    print(f"  [MISS] {pid} - not-found text matched  ({consecutive_misses} consecutive)")
                    if consecutive_misses >= max_gaps:
                        print(f"\n  Stopped: {max_gaps} consecutive misses reached at {pid}")
                        break
                    continue

                consecutive_misses = 0
                total_hits += 1
                print(f"  [HIT]  {pid} - {url}")

        except Exception as exc:
            consecutive_misses += 1
            print(f"  [MISS] {pid} - {exc}  ({consecutive_misses} consecutive)")
            if consecutive_misses >= max_gaps:
                print(f"\n  Stopped: {max_gaps} consecutive misses reached at {pid}")
                break

    return total_hits


def _handle_pattern_ingest(args: argparse.Namespace) -> tuple[int, int, int, int, list[str]]:
    """Run pattern crawl+ingest and print progress.

    Returns (ingested, skipped, failed, orphaned, seen_doc_ids).
    """
    total_ingested = 0
    total_skipped = 0
    total_failed = 0
    total_orphaned = 0
    seen_doc_ids: list[str] = []

    for event in crawl_and_ingest_pattern(
        pattern_url=args.pattern,
        start=args.start,
        end=args.end,
        pad_width=args.pad_width,
        not_found_text=args.not_found_text,
        max_consecutive_misses=args.max_gaps,
        download_dir=args.download_dir,
    ):
        event_type = event.get("type")

        if event_type == "pattern_start":
            if not args.quiet:
                print(
                    f"  Range: {event['start']}..{event['end']} "
                    f"(pad={event['pad_width']}, max_gaps={event['max_consecutive_misses']})"
                )
                print(f"  Not-found text: \"{event['not_found_text']}\"")

        elif event_type == "pattern_hit":
            print(f"  [HIT]  {str(event['num']).zfill(args.pad_width)} - {event['url']}")

        elif event_type == "pattern_miss":
            if not args.quiet:
                pid = str(event["num"]).zfill(args.pad_width)
                print(
                    f"  [MISS] {pid} - {event['reason']}  "
                    f"({event['consecutive_misses']} consecutive)"
                )

        elif event_type == "pattern_gap_stop":
            print(
                f"\n  Stopped: {event['consecutive_misses']} consecutive misses "
                f"reached at {str(event['num']).zfill(args.pad_width)}"
            )

        elif event_type == "page_ingest_done":
            if not args.quiet:
                if event.get("status") == "unchanged":
                    print(f"    [PAGE SKIP] {event.get('title') or 'Untitled'} (unchanged)")
                else:
                    print(f"    [PAGE OK] {event.get('title') or 'Untitled'}")

        elif event_type == "page_ingest_error":
            print(f"    [PAGE FAIL] HTML ingest: {event['error']}")

        elif event_type == "download_start":
            if not args.quiet:
                print(f"    [{event['index']}/{event['total']}] Downloading...")

        elif event_type == "download_error":
            print(f"    [FAILED] Download: {event['error']}")
            print(f"             URL: {event['url']}")

        elif event_type == "download_done":
            if not args.quiet:
                print(f"             Downloaded: {event['url'][:60]}...")

        elif event_type == "not_modified":
            print(f"    [304] Not modified: {event['url'][:50]}...")

        elif event_type == "ingest_start":
            if not args.quiet:
                print("             Ingesting...")

        elif event_type == "ingest_error":
            print(f"    [FAILED] Ingest: {event['error']}")

        elif event_type == "ingest_done":
            archived_status = "" if event.get("is_current", True) else " [archived]"
            cat_suffix = f" [{event['category']}]" if event.get("category") else ""
            if event.get("status") == "unchanged":
                print(f"    [SKIP] {event.get('title') or 'Untitled'} (unchanged){cat_suffix}")
            else:
                print(f"    [OK] {event.get('title') or 'Untitled'}{archived_status}{cat_suffix}")
                print(f"         doc_id: {event['doc_id']}")

        elif event_type == "orphaned":
            if event["count"] > 0:
                print(f"\n  Marked {event['count']} previously-ingested document(s) as orphaned")

        elif event_type == "done":
            ingested = event.get("ingested", [])
            failed = event.get("failed", [])
            orphaned = event.get("orphaned_count", 0)

            skipped = [
                i for i in ingested if i.get("status") in ("not_modified", "unchanged")
            ]
            actually_ingested = [
                i for i in ingested if i.get("status") not in ("not_modified", "unchanged")
            ]

            total_ingested = len(actually_ingested)
            total_skipped = len(skipped)
            total_failed = len(failed)
            total_orphaned = orphaned

            for item in ingested:
                if item.get("doc_id"):
                    seen_doc_ids.append(item["doc_id"])

            print("\nSummary:")
            print(f"  Hits:     {event.get('total_hits', 0)}")
            print(f"  Misses:   {event.get('total_misses', 0)}")
            print(f"  Ingested: {total_ingested}")
            if total_skipped:
                print(f"  Skipped:  {total_skipped} (unchanged)")
            print(f"  Failed:   {total_failed}")
            if total_orphaned > 0:
                print(f"  Orphaned: {total_orphaned}")

    return total_ingested, total_skipped, total_failed, total_orphaned, seen_doc_ids


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Crawl web pages to discover and ingest documents (PDF, DOCX, XLSX)"
    )
    ap.add_argument("urls", nargs="*", help="URLs to crawl for document links")
    ap.add_argument(
        "--file",
        "-f",
        type=Path,
        help="Read URLs from a text file (one URL per line)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview discovered links without downloading/ingesting",
    )
    ap.add_argument(
        "--download-dir",
        type=Path,
        help="Directory to save downloaded files (uses temp dir if not specified)",
    )
    ap.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only show summary, not individual progress",
    )
    ap.add_argument(
        "--follow-pages",
        action="store_true",
        help="Follow HTML page links recursively (BFS). Requires --depth.",
    )
    ap.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Max BFS depth for --follow-pages (required with --follow-pages)",
    )
    ap.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Max pages to visit during recursive crawl (overrides CRAWLER_MAX_PAGES)",
    )

    # Pattern-based enumeration mode
    ap.add_argument(
        "--pattern",
        type=str,
        default=None,
        help='URL pattern with {} placeholder (e.g. "https://example.com/page?id={}")',
    )
    ap.add_argument(
        "--start",
        type=int,
        default=1,
        help="First number to try in pattern mode (default: 1)",
    )
    ap.add_argument(
        "--end",
        type=int,
        default=9999,
        help="Last number to try in pattern mode (default: 9999)",
    )
    ap.add_argument(
        "--pad-width",
        type=int,
        default=4,
        help="Zero-padding width for pattern numbers (default: 4, so 1 -> 0001)",
    )
    ap.add_argument(
        "--not-found-text",
        type=str,
        default=None,
        help='Substring in page body that indicates "not found" (required with --pattern)',
    )
    ap.add_argument(
        "--max-gaps",
        type=int,
        default=10,
        help="Consecutive misses before stopping pattern crawl (default: 10)",
    )
    ap.add_argument(
        "--mark-unseen",
        action="store_true",
        help="After crawling, mark documents without a download_url as orphaned "
        "if not matched by SHA256 during this run",
    )

    args = ap.parse_args()

    # Validate --follow-pages requires --depth
    if args.follow_pages and args.depth is None:
        print("Error: --follow-pages requires --depth N")
        sys.exit(1)

    # Validate --pattern and --follow-pages are mutually exclusive
    if args.pattern and args.follow_pages:
        print("Error: --pattern and --follow-pages are mutually exclusive")
        sys.exit(1)

    # Validate --pattern requires --not-found-text
    if args.pattern and not args.not_found_text:
        print("Error: --pattern requires --not-found-text")
        sys.exit(1)

    # ---------- Pattern mode (does not use positional urls) ----------
    if args.pattern:
        print(f"\n{'=' * 60}")
        print(f"Pattern crawl: {args.pattern}")
        print(f"  Mode: pattern (start={args.start}, end={args.end}, pad={args.pad_width})")
        print("=" * 60)

        if args.dry_run:
            total_hits = _handle_pattern_dry_run(args)
            print(f"\nTotal hits discovered: {total_hits}")
        else:
            ing, skip, fail, orph, seen = _handle_pattern_ingest(args)
            if args.mark_unseen:
                unseen_count = mark_unseen_orphaned(seen)
                if unseen_count > 0:
                    print(
                        f"\n  Marked {unseen_count} unmatched document(s)"
                        " as orphaned (no download_url)"
                    )
            if fail > 0:
                sys.exit(1)

        return

    # ---------- URL-based modes (positional urls / --file) ----------

    # Collect URLs from arguments and/or file
    urls: list[str] = list(args.urls) if args.urls else []

    if args.file:
        if not args.file.exists():
            print(f"Error: File not found: {args.file}")
            sys.exit(1)
        with open(args.file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith("#"):
                    urls.append(line)

    if not urls:
        print("Error: No URLs provided. Use positional arguments or --file")
        sys.exit(1)

    total_ingested = 0
    total_skipped = 0  # 304 Not Modified
    total_failed = 0
    total_orphaned = 0
    total_discovered = 0  # For dry-run mode
    all_seen_doc_ids: list[str] = []  # For --mark-unseen

    for url in urls:
        print(f"\n{'=' * 60}")
        print(f"Crawling: {url}")
        if args.follow_pages:
            print(f"  Mode: recursive (depth={args.depth}, max_pages={args.max_pages or 'default'})")
        print("=" * 60)

        if args.follow_pages:
            # Recursive page-following mode
            if args.dry_run:
                total_discovered += _handle_recursive_dry_run(url, args)
            else:
                ing, skip, fail, orph, seen = _handle_recursive_ingest(url, args)
                total_ingested += ing
                total_skipped += skip
                total_failed += fail
                total_orphaned += orph
                all_seen_doc_ids.extend(seen)

        elif args.dry_run:
            # Original single-page preview mode
            result = preview_links(url)

            if "error" in result:
                print(f"[ERROR] {result['error']}")
                continue

            links = result.get("discovered", [])
            category = result.get("category")
            total_discovered += len(links)

            cat_info = f" (category: {category})" if category else ""
            print(f"\nDiscovered {len(links)} document link(s){cat_info}:\n")

            for i, link in enumerate(links, 1):
                title = link.get("title") or "(no title)"
                ext = link.get("extension", "")
                print(f"  {i}. [{ext.upper()[1:]}] {title}")
                print(f"      {link['url']}")
                print()

        else:
            # Original single-page crawl and ingest mode
            for event in crawl_and_ingest(url, download_dir=args.download_dir):
                event_type = event.get("type")

                if event_type == "crawl_start":
                    if not args.quiet:
                        print("Fetching page...")

                elif event_type == "crawl_error":
                    print(f"[ERROR] Crawl failed: {event['error']}")

                elif event_type == "crawl_done":
                    cat_info = f" (category: {event['category']})" if event.get("category") else ""
                    print(f"Found {event['link_count']} document link(s){cat_info}")

                elif event_type == "download_start":
                    if not args.quiet:
                        print(f"  [{event['index']}/{event['total']}] Downloading...")

                elif event_type == "download_error":
                    print(f"  [FAILED] Download: {event['error']}")
                    print(f"           URL: {event['url']}")

                elif event_type == "download_done":
                    if not args.quiet:
                        print(f"           Downloaded: {event['url'][:60]}...")

                elif event_type == "not_modified":
                    print(f"  [304] Not modified, skipped download: {event['url'][:50]}...")

                elif event_type == "ingest_start":
                    if not args.quiet:
                        print("           Ingesting...")

                elif event_type == "ingest_error":
                    print(f"  [FAILED] Ingest: {event['error']}")

                elif event_type == "ingest_done":
                    archived_status = "" if event.get("is_current", True) else " [archived]"
                    cat_suffix = f" [{event['category']}]" if event.get("category") else ""
                    # Show if document was unchanged (skipped re-indexing)
                    if event.get("status") == "unchanged":
                        print(f"  [SKIP] {event.get('title') or 'Untitled'} (unchanged){cat_suffix}")
                    else:
                        print(f"  [OK] {event.get('title') or 'Untitled'}{archived_status}{cat_suffix}")
                        print(f"       doc_id: {event['doc_id']}")

                elif event_type == "orphaned":
                    if event["count"] > 0:
                        print(f"\n  Marked {event['count']} previously-ingested document(s) as orphaned")

                elif event_type == "done":
                    ingested = event.get("ingested", [])
                    failed = event.get("failed", [])
                    orphaned = event.get("orphaned_count", 0)

                    # Separate skipped (304 or unchanged) from actually ingested
                    skipped = [i for i in ingested if i.get("status") in ("not_modified", "unchanged")]
                    actually_ingested = [i for i in ingested if i.get("status") not in ("not_modified", "unchanged")]

                    total_ingested += len(actually_ingested)
                    total_skipped += len(skipped)
                    total_failed += len(failed)
                    total_orphaned += orphaned

                    # Collect seen doc_ids for --mark-unseen
                    for item in ingested:
                        if item.get("doc_id"):
                            all_seen_doc_ids.append(item["doc_id"])

                    print(f"\nSummary for {url}:")
                    print(f"  Ingested: {len(actually_ingested)}")
                    if skipped:
                        print(f"  Skipped:  {len(skipped)} (unchanged)")
                    print(f"  Failed:   {len(failed)}")
                    if orphaned > 0:
                        print(f"  Orphaned: {orphaned}")

    # --mark-unseen: orphan documents without download_url that weren't matched
    if args.mark_unseen and not args.dry_run:
        unseen_count = mark_unseen_orphaned(all_seen_doc_ids)
        if unseen_count > 0:
            print(
                f"\n  Marked {unseen_count} unmatched document(s)"
                " as orphaned (no download_url)"
            )
        total_orphaned += unseen_count

    # Final summary for multiple URLs
    if len(urls) > 1:
        print(f"\n{'=' * 60}")
        print("TOTAL SUMMARY")
        print("=" * 60)
        print(f"  URLs crawled: {len(urls)}")
        if args.dry_run:
            print(f"  Discovered:   {total_discovered}")
        else:
            print(f"  Ingested:     {total_ingested}")
            if total_skipped > 0:
                print(f"  Skipped:      {total_skipped} (unchanged)")
            print(f"  Failed:       {total_failed}")
            if total_orphaned > 0:
                print(f"  Orphaned:     {total_orphaned}")

    # Show total even for single URL in dry-run (useful for confirmation)
    elif args.dry_run:
        print(f"\nTotal documents discovered: {total_discovered}")

    # Exit with error code if any failures
    if total_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
