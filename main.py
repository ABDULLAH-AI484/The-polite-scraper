from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator

BASE_URL = "https://books.toscrape.com/"
USER_AGENT = "FlyRankInternship-A9/1.0 (+https://github.com/example/flyrank-a9-scraper)"


class BookRecord(BaseModel):
    """Validated, normalized book record stored in books.json."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    product_url: HttpUrl
    price_text: str = Field(min_length=1)
    price_gbp: float = Field(ge=0)
    availability_text: str = Field(min_length=1)
    rating_text: str = Field(min_length=1)
    description: Optional[str] = None
    source_page: HttpUrl
    fetched_at: datetime

    @field_validator("product_url", "source_page")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("URL must use https")
        return value


@dataclass
class RunStats:
    pages_fetched: int = 0
    cache_hits: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    failed_pages: list[dict[str, str]] = field(default_factory=list)


class PoliteFetcher:
    def __init__(self, cache_dir: Path, delay: float = 0.5, timeout: float = 10.0, stats: RunStats | None = None):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = max(0.5, delay)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
        self._last_request_at: float | None = None
        self.stats = stats or RunStats()

    def _cache_path(self, url: str, kind: str) -> Path:
        if kind == "catalogue":
            match = re.search(r"page-(\d+)\.html$", url)
            name = f"catalogue-page-{match.group(1) if match else '1'}.html"
        else:
            digest = hashlib.sha256(url.encode()).hexdigest()[:20]
            name = f"detail-{digest}.html"
        return self.cache_dir / name

    def _wait_before_request(self) -> None:
        if self._last_request_at is not None:
            remaining = self.delay - (perf_counter() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)

    def fetch(self, url: str, kind: str = "detail") -> tuple[str, bool]:
        path = self._cache_path(url, kind)
        if path.exists():
            self.stats.cache_hits += 1
            print(f"CACHE HIT {url} ({path.stat().st_size} bytes)")
            return path.read_text(encoding="utf-8"), True

        attempts = 2
        last_error = "unknown fetch error"
        for attempt in range(1, attempts + 1):
            self._wait_before_request()
            self._last_request_at = perf_counter()
            try:
                response = self.session.get(url, timeout=self.timeout)
                status = response.status_code
                if status == 200:
                    # Books to Scrape serves UTF-8; set it explicitly because
                    # relying on an absent/ambiguous HTTP charset can produce
                    # mojibake such as "Â£" for the pound sign.
                    response.encoding = "utf-8"
                    path.write_text(response.text, encoding="utf-8")
                    self.stats.pages_fetched += 1
                    print(f"FETCH {url} -> {status} ({len(response.content)} bytes)")
                    return response.text, False
                last_error = f"HTTP {status}"
                # A second try is appropriate only for transient server errors.
                if not (500 <= status <= 599):
                    break
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(self.delay)
        raise RuntimeError(last_error)


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_price(price_text: str) -> float:
    match = re.search(r"\d+(?:\.\d+)?", price_text.replace(",", ""))
    if not match:
        raise ValueError(f"could not parse price: {price_text!r}")
    return float(match.group(0))


def absolute_url(href: str, page_url: str) -> str:
    return urljoin(page_url, href)


def discover_catalogue(fetcher: PoliteFetcher, max_pages: int = 3) -> tuple[list[tuple[str, str]], int, int]:
    current = BASE_URL
    seen_catalogue: set[str] = set()
    links: list[tuple[str, str]] = []
    catalogue_pages = 0
    while current and catalogue_pages < max_pages and current not in seen_catalogue:
        html, _ = fetcher.fetch(current, "catalogue")
        seen_catalogue.add(current)
        catalogue_pages += 1
        soup = BeautifulSoup(html, "html.parser")
        for article in soup.select("article.product_pod"):
            anchor = article.select_one("h3 a")
            if anchor and anchor.get("href"):
                links.append((absolute_url(anchor["href"], current), current))
        next_link = soup.select_one("li.next a[href]")
        current = absolute_url(next_link["href"], current) if next_link else ""
    unique: dict[str, str] = {}
    for product_url, source_page in links:
        unique.setdefault(product_url, source_page)
    return list(unique.items()), catalogue_pages, len(links)


def extract_raw_record(html: str, product_url: str, source_page: str, fetched_at: datetime) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    product = soup.select_one(".product_main")
    if product is None:
        raise ValueError("missing product_main section")
    title = clean_text(product.select_one("h1").get_text(" ") if product.select_one("h1") else None)
    price_node = product.select_one(".price_color")
    availability_node = product.select_one(".availability")
    rating_node = product.select_one(".star-rating")
    description_node = soup.select_one("#product_description + p")
    raw = {
        "title": title,
        "product_url": product_url,
        "price_text": clean_text(price_node.get_text(" ") if price_node else None),
        "availability_text": clean_text(availability_node.get_text(" ") if availability_node else None),
        "rating_text": clean_text(" ".join(rating_node.get("class", [])[1:]) if rating_node else None),
        "description": clean_text(description_node.get_text(" ") if description_node else None) or None,
        "source_page": source_page,
        "fetched_at": fetched_at,
    }
    # Keep the raw eight-field shape; normalization adds price_gbp afterward.
    if not raw["description"]:
        raw["description"] = None
    return raw


def normalize_and_validate(raw: dict[str, Any]) -> BookRecord:
    normalized = dict(raw)
    normalized["price_gbp"] = normalize_price(str(raw["price_text"]))
    return BookRecord.model_validate(normalized)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = ["title", "product_url", "price_text", "price_gbp", "availability_text", "rating_text", "description", "source_page", "fetched_at"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: record.get(key) for key in fields} for record in records)


def run(root: Path, include_fake: bool = False, delay: float = 0.5) -> int:
    started = datetime.now(timezone.utc)
    timer = perf_counter()
    stats = RunStats()
    fetcher = PoliteFetcher(root / "cache", delay=delay, stats=stats)
    output_dir = root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    valid: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    try:
        discovered, page_count, discovered_count = discover_catalogue(fetcher)
        print(f"catalogue_pages={page_count} discovered={discovered_count} unique_urls={len(discovered)}")
        targets = list(discovered)
        if include_fake:
            targets.append(("https://books.toscrape.com/catalogue/this-book-does-not-exist_404/index.html", BASE_URL + "catalogue/page-1.html"))
        for product_url, source_page in targets:
            try:
                html, _ = fetcher.fetch(product_url)
                raw = extract_raw_record(html, product_url, source_page, datetime.now(timezone.utc))
                record = normalize_and_validate(raw)
                valid[str(record.product_url)] = json.loads(record.model_dump_json())
            except (RuntimeError, ValueError, ValidationError, requests.RequestException) as exc:
                stats.invalid_records += 1
                reason = f"{type(exc).__name__}: {exc}"
                stats.failed_pages.append({"url": product_url, "reason": reason})
                errors.append({"url": product_url, "reason": reason})
                print(f"SKIP {product_url} — {reason}")
        records = [valid[url] for url in sorted(valid)]
        stats.valid_records = len(records)
        write_json(output_dir / "books.json", records)
        write_json(output_dir / "errors.json", errors)
        write_csv(output_dir / "books.csv", records)
        if records:
            print("sample_raw_record=" + json.dumps({k: records[0][k] for k in ("title", "product_url", "price_text", "availability_text", "rating_text", "description", "source_page", "fetched_at")}, ensure_ascii=False))
        return_code = 0
    except Exception as exc:
        stats.failed_pages.append({"url": BASE_URL, "reason": f"{type(exc).__name__}: {exc}"})
        write_json(output_dir / "books.json", list(valid.values()))
        write_json(output_dir / "errors.json", errors + [{"url": BASE_URL, "reason": str(exc)}])
        return_code = 1
    report = {
        "started_at": started.isoformat(),
        "duration_seconds": round(perf_counter() - timer, 3),
        "catalogue_pages": locals().get("page_count", 0),
        "discovered_urls": locals().get("discovered_count", 0),
        "unique_urls": len(valid) if 'discovered' not in locals() else len(discovered),
        "pages_fetched": stats.pages_fetched,
        "cache_hits": stats.cache_hits,
        "valid_records": stats.valid_records,
        "invalid_records": stats.invalid_records,
        "failed_pages": len(stats.failed_pages),
        "failures": stats.failed_pages,
    }
    write_json(output_dir / "run-report.json", report)
    print(f"detail_pages={stats.valid_records + stats.invalid_records} valid_records={stats.valid_records} failed_pages={len(stats.failed_pages)}")
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Polite Books to Scrape pipeline")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="project root")
    parser.add_argument("--include-fake", action="store_true", help="append a deliberate 404 to demonstrate failure isolation")
    parser.add_argument("--delay", type=float, default=0.5, help="minimum delay between real requests (minimum 0.5 seconds)")
    args = parser.parse_args()
    return run(args.root, include_fake=args.include_fake, delay=args.delay)


if __name__ == "__main__":
    sys.exit(main())
