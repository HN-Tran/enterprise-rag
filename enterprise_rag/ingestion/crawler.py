"""Web crawler for discovering and downloading documents from web pages."""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import time
from collections import deque
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


@dataclass
class DiscoveredPage:
    """An HTML page link discovered during recursive crawling."""

    url: str
    anchor_text: str | None
    source_url: str
    depth: int


@dataclass
class FullCrawlResult:
    """Result of crawling a page for both document and page links."""

    source_url: str
    doc_links: list[DiscoveredLink]
    page_links: list[DiscoveredPage]
    html_content: bytes | None = None
    page_title: str | None = None
    error: str | None = None


log = logging.getLogger(__name__)


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
        href = anchor["href"].strip()

        # Extract HTTP URLs embedded in mailto: body parameters
        if href.lower().startswith("mailto:"):
            http_match = re.search(r"(https?://[^\s&\"']+)", href)
            if http_match:
                href = http_match.group(1)
            else:
                continue

        # Skip non-HTTP schemes (javascript:, ftp:, tel:, etc.)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href) and not href.lower().startswith(("http://", "https://")):
            continue

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


# ---------------------------------------------------------------------------
# Recursive page crawling
# ---------------------------------------------------------------------------

_DOC_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".xls", ".doc",
    ".pptx", ".ppt", ".odt", ".ods", ".odp",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".csv", ".tsv", ".json", ".xml",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg",
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
}


def _strip_fragment(url: str) -> str:
    """Remove fragment (#...) from a URL for deduplication."""
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def _build_allowed_domains(seed_url: str) -> set[str]:
    """Build the set of allowed domains from the seed URL + config."""
    domains: set[str] = set()

    seed_host = urlparse(seed_url).hostname
    if seed_host:
        domains.add(seed_host.lower())

    extra = settings.CRAWLER_EXTRA_DOMAINS.strip()
    if extra:
        for d in extra.split(","):
            d = d.strip().lower()
            if d:
                domains.add(d)

    return domains


def _extract_page_links_from_soup(
    soup: BeautifulSoup,
    base_url: str,
    source_url: str,
    allowed_domains: set[str],
    seen_urls: set[str],
    depth: int,
) -> list[DiscoveredPage]:
    """Extract HTML page links (non-document) from a BeautifulSoup object.

    Complements ``_extract_links_from_soup`` which finds document links.
    This function finds links to other HTML pages that should be followed
    during a recursive crawl.
    """
    pages: list[DiscoveredPage] = []
    allowed_ext = _get_allowed_extensions()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()

        # Skip non-HTTP schemes
        if href.lower().startswith("mailto:"):
            continue
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href) and not href.lower().startswith(
            ("http://", "https://")
        ):
            continue

        # Skip fragment-only links
        if href.startswith("#"):
            continue

        full_url = urljoin(base_url, href)
        clean_url = _strip_fragment(full_url)

        # Skip if already seen
        if clean_url in seen_urls:
            continue

        # Check domain
        parsed = urlparse(clean_url)
        host = (parsed.hostname or "").lower()
        if host not in allowed_domains:
            continue

        # Skip URLs that look like document downloads
        path_lower = parsed.path.lower()
        if "." in path_lower.rsplit("/", 1)[-1]:
            ext = "." + path_lower.rsplit(".", 1)[-1]
            if ext in allowed_ext or ext in _DOC_EXTENSIONS:
                continue

        seen_urls.add(clean_url)
        anchor_text = _clean_anchor_text(anchor.get_text(strip=True))

        pages.append(
            DiscoveredPage(
                url=clean_url,
                anchor_text=anchor_text,
                source_url=source_url,
                depth=depth + 1,
            )
        )

    return pages


def _save_html_to_temp(html_bytes: bytes, url: str, temp_dir: Path) -> Path:
    """Save fetched HTML to a temp .html file for ingest_path().

    Uses a URL-based hash for the filename to ensure uniqueness.
    """
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    filename = f"{url_hash}.html"
    path = temp_dir / filename
    path.write_bytes(html_bytes)
    return path


def crawl_page_full(
    url: str,
    allowed_domains: set[str],
    seen_urls: set[str],
    depth: int,
    follow_iframes: bool = True,
) -> FullCrawlResult:
    """Crawl a page and return both document links and page links.

    Like ``crawl_page()`` but also discovers HTML page links for recursive
    crawling and returns the raw HTML content for ingestion.

    Args:
        url: URL of the page to crawl
        allowed_domains: Set of hostnames we are allowed to follow
        seen_urls: Shared set of already-visited URLs (mutated in-place)
        depth: Current BFS depth (used for discovered page link depths)
        follow_iframes: If True, also fetch and parse iframe contents

    Returns:
        FullCrawlResult with doc links, page links, and HTML content
    """
    try:
        client_kwargs = _get_http_client_kwargs()
        with httpx.Client(**client_kwargs) as client:
            response = client.get(url)
            response.raise_for_status()

            html_content = response.content
            soup = BeautifulSoup(html_content, "html.parser")

            # Extract page title
            title_tag = soup.find("title")
            page_title = title_tag.get_text(strip=True) if title_tag else None

            # Extract document links (reuse existing helper)
            doc_links = _extract_links_from_soup(soup, url, url, seen_urls)

            # Extract page links for recursive following
            page_links = _extract_page_links_from_soup(
                soup, url, url, allowed_domains, seen_urls, depth
            )

            # Also check iframes for document links
            if follow_iframes:
                for iframe in soup.find_all("iframe", src=True):
                    iframe_src = iframe["src"]
                    iframe_url = urljoin(url, iframe_src)
                    try:
                        iframe_resp = client.get(iframe_url)
                        iframe_resp.raise_for_status()
                        iframe_soup = BeautifulSoup(iframe_resp.content, "html.parser")
                        iframe_doc_links = _extract_links_from_soup(
                            iframe_soup, iframe_url, url, seen_urls
                        )
                        doc_links.extend(iframe_doc_links)
                        iframe_page_links = _extract_page_links_from_soup(
                            iframe_soup, iframe_url, url, allowed_domains, seen_urls, depth
                        )
                        page_links.extend(iframe_page_links)
                    except Exception:
                        pass

            return FullCrawlResult(
                source_url=url,
                doc_links=doc_links,
                page_links=page_links,
                html_content=html_content,
                page_title=page_title,
            )

    except httpx.TimeoutException:
        return FullCrawlResult(
            source_url=url, doc_links=[], page_links=[], error="Request timeout"
        )
    except httpx.HTTPStatusError as e:
        return FullCrawlResult(
            source_url=url, doc_links=[], page_links=[], error=f"HTTP {e.response.status_code}"
        )
    except Exception as e:
        return FullCrawlResult(
            source_url=url, doc_links=[], page_links=[], error=str(e)
        )


def crawl_and_ingest_recursive(
    seed_url: str,
    max_depth: int,
    download_dir: Path | None = None,
    extra_domains: str | None = None,
    max_pages: int | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Recursively crawl pages (BFS), ingesting HTML content and document files.

    Follows HTML page links up to ``max_depth`` levels. Each discovered page
    is itself crawled for document links and further page links.

    Args:
        seed_url: Starting URL
        max_depth: Maximum BFS depth (1 = seed + its direct links)
        download_dir: Directory for downloads (uses temp dir if None)
        extra_domains: Comma-separated extra allowed domains (overrides config)
        max_pages: Safety cap on total pages to visit (overrides config)

    Yields:
        Progress events compatible with the CLI display loop
    """
    if max_pages is None:
        max_pages = settings.CRAWLER_MAX_PAGES

    # Build allowed domains
    allowed_domains = _build_allowed_domains(seed_url)
    if extra_domains:
        for d in extra_domains.split(","):
            d = d.strip().lower()
            if d:
                allowed_domains.add(d)

    # BFS state
    seen_urls: set[str] = set()
    clean_seed = _strip_fragment(seed_url)
    seen_urls.add(clean_seed)

    queue: deque[DiscoveredPage] = deque()
    queue.append(DiscoveredPage(url=clean_seed, anchor_text=None, source_url="", depth=0))

    pages_visited = 0

    # Setup download directory
    if download_dir:
        download_dir.mkdir(parents=True, exist_ok=True)
        temp_dir_obj = None
    else:
        temp_dir_obj = tempfile.TemporaryDirectory()
        download_dir = Path(temp_dir_obj.name)

    try:
        all_ingested: list[dict[str, Any]] = []
        all_failed: list[dict[str, Any]] = []
        all_seen_doc_ids: list[str] = []

        while queue and pages_visited < max_pages:
            page = queue.popleft()
            pages_visited += 1

            yield {
                "type": "page_start",
                "url": page.url,
                "depth": page.depth,
                "page_num": pages_visited,
                "max_pages": max_pages,
                "queue_size": len(queue),
            }

            # Politeness delay (skip for the very first page)
            if pages_visited > 1:
                time.sleep(settings.CRAWLER_PAGE_DELAY)

            # Crawl the page
            result = crawl_page_full(
                page.url, allowed_domains, seen_urls, page.depth
            )

            if result.error:
                yield {"type": "page_error", "url": page.url, "error": result.error}
                continue

            # Extract category from source URL
            source_category = extract_category_from_url(page.url)

            yield {
                "type": "page_done",
                "url": page.url,
                "depth": page.depth,
                "doc_link_count": len(result.doc_links),
                "page_link_count": len(result.page_links),
                "page_title": result.page_title,
                "category": source_category,
            }

            # Ingest the HTML page content itself
            if result.html_content:
                try:
                    html_path = _save_html_to_temp(result.html_content, page.url, download_dir)
                    ingest_result = ingest_path(
                        str(html_path),
                        title_override=result.page_title,
                        source_url=page.source_url or page.url,
                        download_url=page.url,
                        category=source_category,
                    )

                    doc_id = ingest_result["doc_id"]
                    all_seen_doc_ids.append(doc_id)
                    status = ingest_result.get("status")

                    yield {
                        "type": "page_ingest_done",
                        "url": page.url,
                        "doc_id": doc_id,
                        "title": ingest_result.get("title"),
                        "status": status,
                        "category": source_category,
                    }

                    all_ingested.append({
                        "url": page.url,
                        "doc_id": doc_id,
                        "title": ingest_result.get("title"),
                        "pages": ingest_result.get("pages"),
                        "category": source_category,
                        "status": status,
                        "kind": "page",
                    })

                except Exception as e:
                    log.warning("Failed to ingest HTML for %s: %s", page.url, e)
                    yield {"type": "page_ingest_error", "url": page.url, "error": str(e)}

            # Download and ingest document files
            for i, link in enumerate(result.doc_links, 1):
                yield {
                    "type": "download_start",
                    "url": link.url,
                    "index": i,
                    "total": len(result.doc_links),
                }

                dl_result = download_file(link, download_dir)

                if dl_result.error:
                    yield {"type": "download_error", "url": link.url, "error": dl_result.error}
                    all_failed.append({"url": link.url, "error": dl_result.error})
                    continue

                category = extract_category_from_url(link.source_url)

                # Handle 304 Not Modified
                if dl_result.skipped_not_modified:
                    yield {"type": "not_modified", "url": link.url}
                    try:
                        with get_conn() as conn:
                            with conn.cursor() as cur:
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
                                    all_seen_doc_ids.append(doc_id)
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

                            all_ingested.append({
                                "url": link.url,
                                "doc_id": doc_id,
                                "status": "not_modified",
                                "category": category,
                                "kind": "doc",
                            })
                    except Exception as e:
                        all_failed.append({"url": link.url, "error": f"304 update failed: {e}"})
                    continue

                yield {"type": "download_done", "url": link.url}

                # Ingest the document file
                yield {"type": "ingest_start", "url": link.url}

                try:
                    ingest_result = ingest_path(
                        str(dl_result.local_path),
                        title_override=link.anchor_text,
                        source_url=link.source_url,
                        download_url=link.url,
                        category=category,
                    )

                    if dl_result.http_etag or dl_result.http_last_modified:
                        _store_http_headers(
                            link.url, dl_result.http_etag, dl_result.http_last_modified
                        )

                    doc_id = ingest_result["doc_id"]
                    all_seen_doc_ids.append(doc_id)
                    status = ingest_result.get("status")

                    yield {
                        "type": "ingest_done",
                        "url": link.url,
                        "doc_id": doc_id,
                        "title": ingest_result.get("title"),
                        "is_current": ingest_result.get("is_current", True),
                        "category": category,
                        "status": status,
                    }

                    all_ingested.append({
                        "url": link.url,
                        "doc_id": doc_id,
                        "title": ingest_result.get("title"),
                        "pages": ingest_result.get("pages"),
                        "is_current": ingest_result.get("is_current", True),
                        "category": category,
                        "status": status,
                        "kind": "doc",
                    })

                except Exception as e:
                    yield {"type": "ingest_error", "url": link.url, "error": str(e)}
                    all_failed.append({"url": link.url, "error": str(e)})

            # Enqueue discovered page links if within depth limit
            if page.depth < max_depth:
                for plink in result.page_links:
                    if plink.depth <= max_depth:
                        queue.append(plink)

                if result.page_links:
                    yield {
                        "type": "pages_enqueued",
                        "count": len(result.page_links),
                        "queue_size": len(queue),
                    }

        if queue:
            yield {
                "type": "max_pages_reached",
                "visited": pages_visited,
                "remaining_in_queue": len(queue),
            }

        # Update last_seen_at for all ingested documents
        if all_seen_doc_ids:
            mark_crawl_seen(all_seen_doc_ids)

        # Mark orphaned documents
        orphaned_count = mark_orphaned(seed_url, all_seen_doc_ids)
        if orphaned_count > 0:
            yield {"type": "orphaned", "count": orphaned_count, "source_url": seed_url}

        yield {
            "type": "done",
            "ingested": all_ingested,
            "failed": all_failed,
            "pages_visited": pages_visited,
            "orphaned_count": orphaned_count,
        }

    finally:
        if temp_dir_obj:
            temp_dir_obj.cleanup()


def crawl_and_ingest_pattern(
    pattern_url: str,
    start: int,
    end: int,
    pad_width: int,
    not_found_text: str,
    max_consecutive_misses: int = 10,
    download_dir: Path | None = None,
    category: str | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Crawl pages by enumerating a numeric placeholder in a URL pattern.

    Iterates ``start`` to ``end``, replacing ``{}`` in *pattern_url* with
    zero-padded numbers.  Each page is fetched; if the HTTP status is non-200
    **or** the response body contains *not_found_text*, the page counts as a
    miss.  After *max_consecutive_misses* misses in a row the crawl stops
    early.

    Valid pages are saved as HTML and ingested, and any document links
    discovered on the page are downloaded and ingested as well.

    Args:
        pattern_url: URL with ``{}`` placeholder (e.g. ``"https://x.com/p?id={}"``).
        start: First number to try.
        end: Last number to try (inclusive).
        pad_width: Zero-padding width (4 → ``0001``).
        not_found_text: Substring in the response body that signals "not found".
        max_consecutive_misses: Stop after this many consecutive misses.
        download_dir: Directory for downloads (uses temp dir if ``None``).
        category: Optional fixed category for all ingested items.

    Yields:
        Progress event dicts (see ``crawl_and_ingest`` for the event pattern).
    """

    yield {
        "type": "pattern_start",
        "pattern_url": pattern_url,
        "start": start,
        "end": end,
        "pad_width": pad_width,
        "not_found_text": not_found_text,
        "max_consecutive_misses": max_consecutive_misses,
    }

    # Setup download directory
    if download_dir:
        download_dir.mkdir(parents=True, exist_ok=True)
        temp_dir_obj = None
    else:
        temp_dir_obj = tempfile.TemporaryDirectory()
        download_dir = Path(temp_dir_obj.name)

    try:
        all_ingested: list[dict[str, Any]] = []
        all_failed: list[dict[str, Any]] = []
        all_seen_doc_ids: list[str] = []
        consecutive_misses = 0
        total_hits = 0
        total_misses = 0

        client_kwargs = _get_http_client_kwargs()

        for num in range(start, end + 1):
            pid = str(num).zfill(pad_width)
            url = pattern_url.replace("{}", pid)

            # Politeness delay (skip for the very first request)
            if num > start:
                time.sleep(settings.CRAWLER_PAGE_DELAY)

            # -- Fetch -------------------------------------------------------
            try:
                with httpx.Client(**client_kwargs) as client:
                    response = client.get(url)

                    # Non-200 → miss
                    if response.status_code != 200:
                        consecutive_misses += 1
                        total_misses += 1
                        yield {
                            "type": "pattern_miss",
                            "url": url,
                            "num": num,
                            "reason": f"HTTP {response.status_code}",
                            "consecutive_misses": consecutive_misses,
                        }
                        if consecutive_misses >= max_consecutive_misses:
                            yield {
                                "type": "pattern_gap_stop",
                                "num": num,
                                "consecutive_misses": consecutive_misses,
                            }
                            break
                        continue

                    # Body contains not-found marker → miss
                    body_text = response.text
                    if not_found_text in body_text:
                        consecutive_misses += 1
                        total_misses += 1
                        yield {
                            "type": "pattern_miss",
                            "url": url,
                            "num": num,
                            "reason": "not-found text matched",
                            "consecutive_misses": consecutive_misses,
                        }
                        if consecutive_misses >= max_consecutive_misses:
                            yield {
                                "type": "pattern_gap_stop",
                                "num": num,
                                "consecutive_misses": consecutive_misses,
                            }
                            break
                        continue

                    # -- Hit! -------------------------------------------------
                    consecutive_misses = 0
                    total_hits += 1
                    html_content = response.content

                    yield {
                        "type": "pattern_hit",
                        "url": url,
                        "num": num,
                        "total_hits": total_hits,
                    }

            except Exception as exc:
                consecutive_misses += 1
                total_misses += 1
                yield {
                    "type": "pattern_miss",
                    "url": url,
                    "num": num,
                    "reason": str(exc),
                    "consecutive_misses": consecutive_misses,
                }
                if consecutive_misses >= max_consecutive_misses:
                    yield {
                        "type": "pattern_gap_stop",
                        "num": num,
                        "consecutive_misses": consecutive_misses,
                    }
                    break
                continue

            # -- Ingest the HTML page ----------------------------------------
            page_category = category or extract_category_from_url(url)
            try:
                html_path = _save_html_to_temp(html_content, url, download_dir)
                soup = BeautifulSoup(html_content, "html.parser")
                title_tag = soup.find("title")
                page_title = title_tag.get_text(strip=True) if title_tag else None

                ingest_result = ingest_path(
                    str(html_path),
                    title_override=page_title,
                    source_url=pattern_url,
                    download_url=url,
                    category=page_category,
                )

                doc_id = ingest_result["doc_id"]
                all_seen_doc_ids.append(doc_id)
                status = ingest_result.get("status")

                yield {
                    "type": "page_ingest_done",
                    "url": url,
                    "doc_id": doc_id,
                    "title": ingest_result.get("title"),
                    "status": status,
                    "category": page_category,
                }

                all_ingested.append({
                    "url": url,
                    "doc_id": doc_id,
                    "title": ingest_result.get("title"),
                    "pages": ingest_result.get("pages"),
                    "category": page_category,
                    "status": status,
                    "kind": "page",
                })

            except Exception as e:
                log.warning("Failed to ingest HTML for %s: %s", url, e)
                yield {"type": "page_ingest_error", "url": url, "error": str(e)}
                all_failed.append({"url": url, "error": str(e), "kind": "page"})

            # -- Download & ingest document links from this page -------------
            seen_urls: set[str] = set()
            doc_links = _extract_links_from_soup(soup, url, url, seen_urls)

            for i, link in enumerate(doc_links, 1):
                yield {
                    "type": "download_start",
                    "url": link.url,
                    "index": i,
                    "total": len(doc_links),
                }

                dl_result = download_file(link, download_dir)

                if dl_result.error:
                    yield {"type": "download_error", "url": link.url, "error": dl_result.error}
                    all_failed.append({"url": link.url, "error": dl_result.error, "kind": "doc"})
                    continue

                link_category = page_category or extract_category_from_url(link.source_url)

                if dl_result.skipped_not_modified:
                    yield {"type": "not_modified", "url": link.url}
                    try:
                        with get_conn() as conn:
                            with conn.cursor() as cur:
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
                                    all_seen_doc_ids.append(doc_id)
                                    if link_category:
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
                                            {"doc": doc_id, "cat": link_category},
                                        )
                                    else:
                                        cur.execute(
                                            "UPDATE documents SET last_seen_at = now() WHERE doc_id = %(doc)s",
                                            {"doc": doc_id},
                                        )
                            conn.commit()

                            all_ingested.append({
                                "url": link.url,
                                "doc_id": doc_id,
                                "status": "not_modified",
                                "category": link_category,
                                "kind": "doc",
                            })
                    except Exception as e:
                        all_failed.append({
                            "url": link.url,
                            "error": f"304 update failed: {e}",
                            "kind": "doc",
                        })
                    continue

                yield {"type": "download_done", "url": link.url}

                # Ingest the document file
                yield {"type": "ingest_start", "url": link.url}

                try:
                    ingest_result = ingest_path(
                        str(dl_result.local_path),
                        title_override=link.anchor_text,
                        source_url=link.source_url,
                        download_url=link.url,
                        category=link_category,
                    )

                    if dl_result.http_etag or dl_result.http_last_modified:
                        _store_http_headers(
                            link.url, dl_result.http_etag, dl_result.http_last_modified
                        )

                    doc_id = ingest_result["doc_id"]
                    all_seen_doc_ids.append(doc_id)
                    status = ingest_result.get("status")

                    yield {
                        "type": "ingest_done",
                        "url": link.url,
                        "doc_id": doc_id,
                        "title": ingest_result.get("title"),
                        "is_current": ingest_result.get("is_current", True),
                        "category": link_category,
                        "status": status,
                    }

                    all_ingested.append({
                        "url": link.url,
                        "doc_id": doc_id,
                        "title": ingest_result.get("title"),
                        "pages": ingest_result.get("pages"),
                        "is_current": ingest_result.get("is_current", True),
                        "category": link_category,
                        "status": status,
                        "kind": "doc",
                    })

                except Exception as e:
                    yield {"type": "ingest_error", "url": link.url, "error": str(e)}
                    all_failed.append({"url": link.url, "error": str(e), "kind": "doc"})

        # -- Wrap up ---------------------------------------------------------
        if all_seen_doc_ids:
            mark_crawl_seen(all_seen_doc_ids)

        orphaned_count = mark_orphaned(pattern_url, all_seen_doc_ids)
        if orphaned_count > 0:
            yield {"type": "orphaned", "count": orphaned_count, "source_url": pattern_url}

        yield {
            "type": "done",
            "ingested": all_ingested,
            "failed": all_failed,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "orphaned_count": orphaned_count,
        }

    finally:
        if temp_dir_obj:
            temp_dir_obj.cleanup()


def preview_links_recursive(
    seed_url: str,
    max_depth: int,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Dry-run BFS preview of pages and document links that would be crawled.

    Args:
        seed_url: Starting URL
        max_depth: Maximum BFS depth
        max_pages: Safety cap on pages to visit

    Returns:
        Dict with discovered pages and document links
    """
    if max_pages is None:
        max_pages = settings.CRAWLER_MAX_PAGES

    allowed_domains = _build_allowed_domains(seed_url)
    seen_urls: set[str] = set()
    clean_seed = _strip_fragment(seed_url)
    seen_urls.add(clean_seed)

    queue: deque[DiscoveredPage] = deque()
    queue.append(DiscoveredPage(url=clean_seed, anchor_text=None, source_url="", depth=0))

    pages_visited = 0
    all_doc_links: list[dict[str, Any]] = []
    all_pages: list[dict[str, Any]] = []

    while queue and pages_visited < max_pages:
        page = queue.popleft()
        pages_visited += 1

        # Politeness delay (skip for the very first page)
        if pages_visited > 1:
            time.sleep(settings.CRAWLER_PAGE_DELAY)

        result = crawl_page_full(page.url, allowed_domains, seen_urls, page.depth)

        if result.error:
            all_pages.append({
                "url": page.url,
                "depth": page.depth,
                "error": result.error,
            })
            continue

        all_pages.append({
            "url": page.url,
            "depth": page.depth,
            "title": result.page_title,
            "doc_links": len(result.doc_links),
            "page_links": len(result.page_links),
        })

        for link in result.doc_links:
            all_doc_links.append({
                "url": link.url,
                "title": link.anchor_text,
                "extension": link.extension,
                "found_on": page.url,
            })

        # Enqueue page links within depth limit
        if page.depth < max_depth:
            for plink in result.page_links:
                if plink.depth <= max_depth:
                    queue.append(plink)

    category = extract_category_from_url(seed_url)

    return {
        "url": seed_url,
        "category": category,
        "pages_visited": pages_visited,
        "pages": all_pages,
        "doc_links": all_doc_links,
        "truncated": len(queue) > 0,
        "remaining_in_queue": len(queue),
    }
