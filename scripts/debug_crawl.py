"""Debug script to inspect links and iframes on a webpage."""

from __future__ import annotations

import sys
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from enterprise_rag.config import settings


def get_client_kwargs() -> dict:
    kwargs = {"timeout": 30, "follow_redirects": True}
    if not settings.CRAWLER_VERIFY_SSL:
        kwargs["verify"] = False
    if settings.CRAWLER_PROXY:
        kwargs["proxy"] = settings.CRAWLER_PROXY
    return kwargs


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/debug_crawl.py <URL>")
        sys.exit(1)

    url = sys.argv[1]

    with httpx.Client(**get_client_kwargs()) as client:
        print(f"=== Fetching main page: {url} ===\n")
        resp = client.get(url)
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', 'unknown')}")

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find all links
        links = soup.find_all("a", href=True)
        print(f"\n=== Main page: {len(links)} <a> tags ===")
        for a in links[:10]:  # First 10
            print(f"  {a['href'][:80]}")
        if len(links) > 10:
            print(f"  ... and {len(links) - 10} more")

        # Find all iframes
        iframes = soup.find_all("iframe")
        print(f"\n=== Found {len(iframes)} <iframe> tags ===")

        for i, iframe in enumerate(iframes, 1):
            src = iframe.get("src", "(no src)")
            print(f"\n--- Iframe {i}: {src} ---")

            if iframe.get("src"):
                iframe_url = urljoin(url, iframe["src"])
                try:
                    iframe_resp = client.get(iframe_url)
                    print(f"    Status: {iframe_resp.status_code}")
                    iframe_soup = BeautifulSoup(iframe_resp.text, "html.parser")

                    iframe_links = iframe_soup.find_all("a", href=True)
                    print(f"    Links in iframe: {len(iframe_links)}")
                    for a in iframe_links[:5]:
                        print(f"      {a['href'][:80]}")
                    if len(iframe_links) > 5:
                        print(f"      ... and {len(iframe_links) - 5} more")

                    # Check for nested iframes
                    nested = iframe_soup.find_all("iframe")
                    if nested:
                        print(f"    Nested iframes: {len(nested)}")
                        for n in nested:
                            print(f"      {n.get('src', '(no src)')}")

                except Exception as e:
                    print(f"    Error fetching iframe: {e}")

        # Also check for frames (old-style framesets)
        frames = soup.find_all("frame")
        if frames:
            print(f"\n=== Found {len(frames)} <frame> tags (frameset) ===")
            for frame in frames:
                print(f"  {frame.get('src', '(no src)')}")


if __name__ == "__main__":
    main()
