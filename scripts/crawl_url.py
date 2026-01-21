"""Crawl web pages to discover and ingest document links."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from enterprise_rag.ingestion.crawler import crawl_and_ingest, preview_links


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
    args = ap.parse_args()

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
    total_failed = 0
    total_orphaned = 0
    total_discovered = 0  # For dry-run mode

    for url in urls:
        print(f"\n{'=' * 60}")
        print(f"Crawling: {url}")
        print("=" * 60)

        if args.dry_run:
            # Preview mode
            result = preview_links(url)

            if "error" in result:
                print(f"[ERROR] {result['error']}")
                continue

            links = result.get("discovered", [])
            total_discovered += len(links)
            print(f"\nDiscovered {len(links)} document link(s):\n")

            for i, link in enumerate(links, 1):
                title = link.get("title") or "(no title)"
                ext = link.get("extension", "")
                print(f"  {i}. [{ext.upper()[1:]}] {title}")
                print(f"      {link['url']}")
                print()

        else:
            # Full crawl and ingest mode
            for event in crawl_and_ingest(url, download_dir=args.download_dir):
                event_type = event.get("type")

                if event_type == "crawl_start":
                    if not args.quiet:
                        print("Fetching page...")

                elif event_type == "crawl_error":
                    print(f"[ERROR] Crawl failed: {event['error']}")

                elif event_type == "crawl_done":
                    print(f"Found {event['link_count']} document link(s)")

                elif event_type == "download_start":
                    if not args.quiet:
                        print(f"  [{event['index']}/{event['total']}] Downloading...")

                elif event_type == "download_error":
                    print(f"  [FAILED] Download: {event['error']}")
                    print(f"           URL: {event['url']}")

                elif event_type == "download_done":
                    if not args.quiet:
                        print(f"           Downloaded: {event['url'][:60]}...")

                elif event_type == "ingest_start":
                    if not args.quiet:
                        print("           Ingesting...")

                elif event_type == "ingest_error":
                    print(f"  [FAILED] Ingest: {event['error']}")

                elif event_type == "ingest_done":
                    status = "" if event.get("is_current", True) else " [archived]"
                    print(f"  [OK] {event.get('title') or 'Untitled'}{status}")
                    print(f"       doc_id: {event['doc_id']}")

                elif event_type == "orphaned":
                    if event["count"] > 0:
                        print(f"\n  Marked {event['count']} previously-ingested document(s) as orphaned")

                elif event_type == "done":
                    ingested = event.get("ingested", [])
                    failed = event.get("failed", [])
                    orphaned = event.get("orphaned_count", 0)

                    total_ingested += len(ingested)
                    total_failed += len(failed)
                    total_orphaned += orphaned

                    print(f"\nSummary for {url}:")
                    print(f"  Ingested: {len(ingested)}")
                    print(f"  Failed:   {len(failed)}")
                    if orphaned > 0:
                        print(f"  Orphaned: {orphaned}")

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
