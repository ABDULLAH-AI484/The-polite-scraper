# The Polite Scraper — FlyRank W5 A9

A small Python scraping pipeline for the **Books to Scrape** practice sandbox. It follows the assignment’s stages: fetch and cache catalogue pages, discover book URLs, fetch detail pages, extract raw fields, normalize and validate records, store clean JSON, and report failures.

## Target classification

**Target:** [Books to Scrape](https://books.toscrape.com/), a public sandbox specifically built for practicing web scraping. This run is intentionally limited to the first **three catalogue pages** and their 60 book pages. The collected fields are title, product URL, price, availability, rating, description, source page, and fetch timestamp. This limited, low-rate collection is appropriate because the target is a practice sandbox and the assignment explicitly authorizes it.

I requested `https://books.toscrape.com/robots.txt` once. It returned **HTTP 404 Not Found**, so there was no robots file found. A missing robots file is not treated as permission for another site.

**I will not reuse this code on another site without checking its rules and terms first.**

file:///C:/Users/Mindwhiz/Videos/markmap.svg open this link 
<img width="1908" height="730" alt="Screenshot 2026-09-09 100222" src="https://github.com/user-attachments/assets/bcfb5a42-ac52-48df-8bd1-6bb5089d5181" />


## Quick start

```bash
cd scraper
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

The command discovers exactly three catalogue pages and writes `output/books.json`, `output/errors.json`, `output/books.csv`, and `output/run-report.json`. A second run mostly reads from `cache/` and remains idempotent: the JSON contains one record per canonical URL, not duplicates.

<img width="1917" height="1012" alt="Screenshot 2026-09-09 095823" src="https://github.com/user-attachments/assets/dea9aa4a-0099-4787-8d84-fc67c261e1e1" />


To demonstrate failure isolation with a deliberately fake URL, use:

```bash
python -m src.main --include-fake
```

The run still completes with the 60 good records and records one failed page in the report. The fake URL is never used to hammer the real site.

![Uploading Screenshot 2026-09-09 100259.png…]()



## Politeness rules

Every real request sends an identifying user-agent, has a 10-second timeout, checks for status 200 before parsing, and waits at least 500 ms between requests. Server errors and request timeouts receive one retry; 403 and 404 responses are not retried. Catalogue and detail HTML are cached locally, so development reruns do not repeatedly contact the site. A browser is unnecessary because the data is already in the HTML sent by the server; using one would add cost without adding information.

## Validated record schema

`src/main.py` defines the schema with Pydantic. Required fields are `title`, `product_url`, `price_text`, `price_gbp`, `availability_text`, `rating_text`, `source_page`, and `fetched_at`; `description` is optional and is stored as `null` when absent. URLs must be absolute HTTPS URLs, and `price_gbp` must be a non-negative number. Invalid records go to `output/errors.json` with a reason and never enter `books.json`.

## Tests

The parser tests cover price normalization, relative-to-absolute URL resolution, missing descriptions, duplicate URL identity, and a malformed fixture:

```bash
pytest -q
```

## Evidence from a real run

A representative successful report has this shape (timestamps and duration vary by run):

```json
{
  "catalogue_pages": 3,
  "discovered_urls": 60,
  "unique_urls": 60,
  "pages_fetched": 63,
  "cache_hits": 0,
  "valid_records": 60,
  "invalid_records": 0,
  "failed_pages": 0
}
```

With `--include-fake`, `failed_pages` becomes `1` while `valid_records` remains `60`.

## Ethics and limitations

Use an official API when one exists. Never bypass logins, paywalls, or blocks. Collect only what is needed, identify the client, keep the request rate low, and preserve provenance. This project is intentionally specialized to the Books to Scrape sandbox; it does not implement a general crawler, JavaScript rendering, or production-scale distributed fetching.
