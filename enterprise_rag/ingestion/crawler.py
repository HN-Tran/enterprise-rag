"""Web crawler for discovering and downloading documents from web pages."""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from enterprise_rag.config import get_category_map, settings
from enterprise_rag.db import get_conn
from enterprise_rag.ingestion.ingest import ingest_path
from enterprise_rag.ingestion.versioning import mark_crawl_seen, mark_orphaned


@dataclass
class DiscoveredLink:
    """A document link discovered on a web page."""

    url: str
    anchor_text: str | None
    source_url: str
    extension: str


@dataclass
class CrawlResult:
    """Result of crawling a web page."""

    source_url: str
    links: list[DiscoveredLink]
    error: str | None = None


@dataclass
class DownloadResult:
    """Result of downloading a file."""

    link: DiscoveredLink
    local_path: Path | None
    error: str | None = None
    skipped_not_modified: bool = False  # True if 304 Not Modified
    http_etag: str | None = None
    http_last_modified: str | None = None


@dataclass
class IngestResult:
    """Result of ingesting a downloaded file."""

    link: DiscoveredLink
    doc_id: str | None
    title: str | None
    error: str | None = None
    is_current: bool = True


def _get_cached_http_headers(download_url: str) -> tuple[str | None, str | None]:
    """Get cached ETag and Last-Modified for a download URL.

    Returns:
        Tuple of (etag, last_modified) or (None, None) if not cached
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT http_etag, http_last_modified
                    FROM documents
                    WHERE download_url = %(url)s AND is_current = TRUE
                    LIMIT 1
                    """,
                    {"url": download_url},
                )
                row = cur.fetchone()
                if row:
                    return row["http_etag"], row["http_last_modified"]
    except Exception:
        pass  # DB not available, skip caching
    return None, None


def _store_http_headers(download_url: str, etag: str | None, last_modified: str | None) -> None:
    """Store HTTP caching headers for a download URL."""
    if not etag and not last_modified:
        return

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE documents
                    SET http_etag = %(etag)s,
                        http_last_modified = %(last_mod)s
                    WHERE download_url = %(url)s
                    """,
                    {"url": download_url, "etag": etag, "last_mod": last_modified},
                )
            conn.commit()
    except Exception:
        pass  # DB not available, skip caching


def _get_allowed_extensions() -> set[str]:
    """Get set of allowed file extensions from settings."""
    exts = settings.CRAWLER_ALLOWED_EXTENSIONS.lower().split(",")
    return {e.strip() for e in exts if e.strip()}


def extract_category_from_url(url: str) -> str | None:
    """Extract category from URL's ?v= or ?V= parameter using config mapping.

    Args:
        url: Source URL (e.g., "https://example.com/docs?v=A" or "?V=A")

    Returns:
        Category name if found in mapping, None otherwise
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    # Look for ?v= or ?V= parameter (case-insensitive)
    v_values = params.get("v", []) or params.get("V", [])
    if not v_values:
        return None

    v_value = v_values[0]  # Take first value if multiple
    category_map = get_category_map()

    return category_map.get(v_value)


def _get_http_client_kwargs() -> dict[str, Any]:
    """Build kwargs for httpx.Client with proxy and SSL settings."""
    kwargs: dict[str, Any] = {
        "timeout": settings.CRAWLER_TIMEOUT,
        "follow_redirects": True,
        "headers": {"User-Agent": settings.CRAWLER_USER_AGENT},
    }

    # SSL verification
    if not settings.CRAWLER_VERIFY_SSL:
        kwargs["verify"] = False
    elif settings.CRAWLER_CA_BUNDLE:
        kwargs["verify"] = settings.CRAWLER_CA_BUNDLE

    # Proxy configuration
    if settings.CRAWLER_PROXY:
        kwargs["proxy"] = settings.CRAWLER_PROXY

    return kwargs


def _clean_anchor_text(text: str | None) -> str | None:
    """Clean anchor text to extract document title.

    Removes common download indicators and cleans whitespace.
    """
    if not text:
        return None

    # Remove common download indicators
    patterns_to_remove = [
        r"\s*\(PDF\)\s*",
        r"\s*\[PDF\]\s*",
        r"\s*\(Download\)\s*",
        r"\s*\[Download\]\s*",
        r"\s*\(DOCX?\)\s*",
        r"\s*\[DOCX?\]\s*",
        r"\s*\(XLSX?\)\s*",
        r"\s*\[XLSX?\]\s*",
        r"\s*►\s*",
        r"\s*↓\s*",
        r"\s*⬇\s*",
    ]

    cleaned = text
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

    # Normalize whitespace
    cleaned = " ".join(cleaned.split())
    return cleaned.strip() if cleaned.strip() else None


def _extract_extension(url: str) -> str | None:
    """Extract file extension from URL.

    Checks both the URL path and query parameters for document extensions.
    Handles URLs like:
    - /files/report.pdf
    - /download.asp?file=report.pdf
    - /get?doc=manual.docx&version=2
    """
    parsed = urlparse(url)
    allowed = _get_allowed_extensions()

    # First, check the path
    path = parsed.path.lower()
    if "." in path:
        ext = "." + path.rsplit(".", 1)[-1]
        if ext in allowed:
            return ext

    # If path doesn't have a document extension, check query parameters
    # Look for common patterns like file=X.pdf, doc=X.docx, etc.
    query = parsed.query.lower()
    if query:
        # Find any document extension in the query string
        for ext in allowed:
            if ext in query:
                return ext

    return None


def _extract_links_from_soup(
    soup: BeautifulSoup,
    base_url: str,
    source_url: str,
    seen_urls: set[str],
) -> list[DiscoveredLink]:
    """Extract document links from a BeautifulSoup object."""
    links: list[DiscoveredLink] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]

        # Resolve relative URLs
        full_url = urljoin(base_url, href)

        # Check if it's a document link
        ext = _extract_extension(full_url)
        if not ext:
            continue

        # Skip duplicates
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Extract anchor text
        anchor_text = _clean_anchor_text(anchor.get_text(strip=True))

        links.append(
            DiscoveredLink(
                url=full_url,
                anchor_text=anchor_text,
                source_url=source_url,
                extension=ext,
            )
        )

    return links


def crawl_page(url: str, follow_iframes: bool = True) -> CrawlResult:
    """Fetch a web page and extract document links.

    Args:
        url: URL of the page to crawl
        follow_iframes: If True, also fetch and parse iframe contents

    Returns:
        CrawlResult with discovered document links
    """
    try:
        client_kwargs = _get_http_client_kwargs()
        with httpx.Client(**client_kwargs) as client:
            response = client.get(url)
            response.raise_for_status()

            # Parse main page (use content bytes for better encoding detection)
            soup = BeautifulSoup(response.content, "html.parser")
            seen_urls: set[str] = set()
            links = _extract_links_from_soup(soup, url, url, seen_urls)

            # Also check iframes
            if follow_iframes:
                for iframe in soup.find_all("iframe", src=True):
                    iframe_src = iframe["src"]
                    iframe_url = urljoin(url, iframe_src)

                    try:
                        iframe_resp = client.get(iframe_url)
                        iframe_resp.raise_for_status()
                        iframe_soup = BeautifulSoup(iframe_resp.content, "html.parser")
                        iframe_links = _extract_links_from_soup(
                            iframe_soup, iframe_url, url, seen_urls
                        )
                        links.extend(iframe_links)
                    except Exception:
                        # Ignore iframe errors, continue with main page results
                        pass

            return CrawlResult(source_url=url, links=links)

    except httpx.TimeoutException:
        return CrawlResult(source_url=url, links=[], error="Request timeout")
    except httpx.HTTPStatusError as e:
        return CrawlResult(source_url=url, links=[], error=f"HTTP {e.response.status_code}")
    except Exception as e:
        return CrawlResult(source_url=url, links=[], error=str(e))


def download_file(link: DiscoveredLink, target_dir: Path) -> DownloadResult:
    """Download a file to the target directory.

    Uses HTTP conditional requests (If-None-Match, If-Modified-Since) to skip
    downloads when server confirms content is unchanged.

    Args:
        link: The discovered link to download
        target_dir: Directory to save the file

    Returns:
        DownloadResult with local path, or skipped_not_modified=True if unchanged
    """
    max_size = settings.CRAWLER_MAX_FILE_SIZE_MB * 1024 * 1024

    # Check for cached HTTP headers
    cached_etag, cached_last_modified = _get_cached_http_headers(link.url)

    try:
        client_kwargs = _get_http_client_kwargs()

        # Build conditional request headers
        headers = dict(client_kwargs.get("headers", {}))
        if cached_etag:
            headers["If-None-Match"] = cached_etag
        if cached_last_modified:
            headers["If-Modified-Since"] = cached_last_modified

        client_kwargs["headers"] = headers

        with httpx.Client(**client_kwargs) as client:
            # Stream the response to check size
            with client.stream("GET", link.url) as response:
                # Check for 304 Not Modified
                if response.status_code == 304:
                    return DownloadResult(
                        link=link,
                        local_path=None,
                        skipped_not_modified=True,
                    )

                response.raise_for_status()

                # Extract HTTP caching headers for future requests
                new_etag = response.headers.get("etag")
                new_last_modified = response.headers.get("last-modified")

                # Check content length if available
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_size:
                    return DownloadResult(
                        link=link,
                        local_path=None,
                        error=f"File too large: {int(content_length) / 1024 / 1024:.1f}MB",
                    )

                # Generate filename from URL
                url_hash = hashlib.sha256(link.url.encode()).hexdigest()[:12]
                filename = f"{url_hash}{link.extension}"
                local_path = target_dir / filename

                # Download with size limit
                downloaded = 0
                with open(local_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        downloaded += len(chunk)
                        if downloaded > max_size:
                            f.close()
                            local_path.unlink()
                            return DownloadResult(
                                link=link,
                                local_path=None,
                                error=f"File too large: >{settings.CRAWLER_MAX_FILE_SIZE_MB}MB",
                            )
                        f.write(chunk)

                return DownloadResult(
                    link=link,
                    local_path=local_path,
                    http_etag=new_etag,
                    http_last_modified=new_last_modified,
                )

    except httpx.TimeoutException:
        return DownloadResult(link=link, local_path=None, error="Download timeout")
    except httpx.HTTPStatusError as e:
        return DownloadResult(link=link, local_path=None, error=f"HTTP {e.response.status_code}")
    except Exception as e:
        return DownloadResult(link=link, local_path=None, error=str(e))


def crawl_and_ingest(
    url: str,
    download_dir: Path | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Crawl a page, download documents, and ingest them.

    Yields progress events for each step.

    Args:
        url: URL to crawl
        download_dir: Directory for downloads (uses temp dir if None)

    Yields:
        Progress events with type, status, and data
    """
    # Crawl the page
    yield {"type": "crawl_start", "url": url}
    result = crawl_page(url)

    if result.error:
        yield {"type": "crawl_error", "url": url, "error": result.error}
        return

    # Extract category from source URL
    source_category = extract_category_from_url(url)
    yield {
        "type": "crawl_done",
        "url": url,
        "link_count": len(result.links),
        "category": source_category,
    }

    if not result.links:
        yield {"type": "done", "ingested": [], "failed": []}
        return

    # Setup download directory
    if download_dir:
        download_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = None
    else:
        temp_dir = tempfile.TemporaryDirectory()
        download_dir = Path(temp_dir.name)

    try:
        ingested: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        seen_doc_ids: list[str] = []

        for i, link in enumerate(result.links, 1):
            yield {
                "type": "download_start",
                "url": link.url,
                "index": i,
                "total": len(result.links),
            }

            # Download file
            dl_result = download_file(link, download_dir)

            if dl_result.error:
                yield {"type": "download_error", "url": link.url, "error": dl_result.error}
                failed.append({"url": link.url, "error": dl_result.error})
                continue

            # Extract category from source URL
            category = extract_category_from_url(link.source_url)

            # Handle 304 Not Modified - update metadata without re-ingesting
            if dl_result.skipped_not_modified:
                yield {"type": "not_modified", "url": link.url}

                # Still need to update last_seen_at and accumulate categories
                try:
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            # Get doc_id for this download_url
                            cur.execute(
                                """
                                SELECT doc_id FROM documents
                                WHERE download_url = %(url)s AND is_current = TRUE
                                LIMIT 1
                                """,
                                {"url": link.url},
                            )
                            row = cur.fetchone()
                            if row:
                                doc_id = row["doc_id"]
                                seen_doc_ids.append(doc_id)

                                # Update last_seen_at and accumulate category
                                if category:
                                    cur.execute(
                                        """
                                        UPDATE documents
                                        SET last_seen_at = now(),
                                            categories = CASE
                                                WHEN categories IS NULL THEN ARRAY[%(cat)s]
                                                WHEN %(cat)s = ANY(categories) THEN categories
                                                ELSE categories || ARRAY[%(cat)s]
                                            END
                                        WHERE doc_id = %(doc)s
                                        """,
                                        {"doc": doc_id, "cat": category},
                                    )
                                else:
                                    cur.execute(
                                        "UPDATE documents SET last_seen_at = now() WHERE doc_id = %(doc)s",
                                        {"doc": doc_id},
                                    )
                        conn.commit()

                        ingested.append({
                            "url": link.url,
                            "doc_id": doc_id,
                            "status": "not_modified",
                            "category": category,
                        })
                except Exception as e:
                    failed.append({"url": link.url, "error": f"304 update failed: {e}"})
                continue

            yield {"type": "download_done", "url": link.url}

            # Ingest the file
            yield {"type": "ingest_start", "url": link.url}

            try:
                ingest_result = ingest_path(
                    str(dl_result.local_path),
                    title_override=link.anchor_text,
                    source_url=link.source_url,
                    download_url=link.url,
                    category=category,
                )

                # Store HTTP caching headers for future conditional requests
                if dl_result.http_etag or dl_result.http_last_modified:
                    _store_http_headers(link.url, dl_result.http_etag, dl_result.http_last_modified)

                doc_id = ingest_result["doc_id"]
                seen_doc_ids.append(doc_id)

                # Check if document was unchanged (skipped re-indexing)
                status = ingest_result.get("status")  # "unchanged" if skipped

                yield {
                    "type": "ingest_done",
                    "url": link.url,
                    "doc_id": doc_id,
                    "title": ingest_result.get("title"),
                    "is_current": ingest_result.get("is_current", True),
                    "category": category,
                    "status": status,
                }

                ingested.append(
                    {
                        "url": link.url,
                        "doc_id": doc_id,
                        "title": ingest_result.get("title"),
                        "pages": ingest_result.get("pages"),
                        "is_current": ingest_result.get("is_current", True),
                        "category": category,
                        "status": status,
                    }
                )

            except Exception as e:
                yield {"type": "ingest_error", "url": link.url, "error": str(e)}
                failed.append({"url": link.url, "error": str(e)})

        # Update last_seen_at for all ingested documents
        if seen_doc_ids:
            mark_crawl_seen(seen_doc_ids)

        # Mark orphaned documents (from this source URL but not seen in this crawl)
        orphaned_count = mark_orphaned(url, seen_doc_ids)
        if orphaned_count > 0:
            yield {"type": "orphaned", "count": orphaned_count, "source_url": url}

        yield {
            "type": "done",
            "ingested": ingested,
            "failed": failed,
            "orphaned_count": orphaned_count,
        }

    finally:
        if temp_dir:
            temp_dir.cleanup()


def preview_links(url: str) -> dict[str, Any]:
    """Preview document links on a page without downloading.

    Args:
        url: URL to crawl

    Returns:
        Dict with discovered links or error
    """
    result = crawl_page(url)

    if result.error:
        return {"error": result.error, "url": url}

    # Extract category from source URL for preview
    category = extract_category_from_url(url)

    return {
        "url": url,
        "category": category,
        "discovered": [
            {
                "url": link.url,
                "title": link.anchor_text,
                "extension": link.extension,
            }
            for link in result.links
        ],
    }
