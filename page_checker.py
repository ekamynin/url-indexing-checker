import asyncio
import aiohttp
from dataclasses import dataclass
from typing import Optional, Callable
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}


@dataclass
class PageCheckResult:
    url: str
    http_status: Optional[int] = None
    noindex: Optional[bool] = None
    nofollow: Optional[bool] = None
    error: Optional[str] = None


def _parse_noindex(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        if name in ("robots", "googlebot"):
            content = meta.get("content", "").lower()
            if "noindex" in content:
                return True
    return False


def _parse_nofollow(html: str) -> bool:
    """Page-level nofollow via meta robots tag."""
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        if name in ("robots", "googlebot"):
            content = meta.get("content", "").lower()
            if "nofollow" in content:
                return True
    return False


async def _check_one(
    session: aiohttp.ClientSession,
    url: str,
    target_domain: str,
) -> PageCheckResult:
    try:
        async with session.get(
            url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True, ssl=False,
        ) as resp:
            status = resp.status
            try:
                html = await resp.text(errors="replace")
            except Exception:
                return PageCheckResult(url=url, http_status=status, error="Не вдалось прочитати HTML")

            noindex  = _parse_noindex(html)
            nofollow = _parse_nofollow(html)
            return PageCheckResult(url=url, http_status=status, noindex=noindex, nofollow=nofollow)

    except asyncio.TimeoutError:
        return PageCheckResult(url=url, error="Timeout")
    except Exception as e:
        return PageCheckResult(url=url, error=str(e)[:80])


async def check_pages(
    urls: list[str],
    concurrency: int = 5,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> list[PageCheckResult]:
    semaphore = asyncio.Semaphore(concurrency)
    results: list[PageCheckResult] = []

    async def bounded(url: str):
        async with semaphore:
            result = await _check_one(session, url, "")
        results.append(result)
        if progress_callback:
            progress_callback(len(results), len(urls))

    connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        await asyncio.gather(*[bounded(u) for u in urls])

    order = {url: i for i, url in enumerate(urls)}
    results.sort(key=lambda r: order.get(r.url, 0))
    return results
