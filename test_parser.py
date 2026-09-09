from datetime import datetime, timezone

import pytest

from src.main import absolute_url, extract_raw_record, normalize_and_validate, normalize_price


def fixture(description: str = "A useful description.") -> str:
    return f'''<html><body><section class="product_main"><h1>  Test Book  </h1><p class="price_color"> £12.50 </p><p class="availability">\n In stock (3 available)\n</p><p class="star-rating Three"></p></section><div id="product_description"><h2>Description</h2></div><p>{description}</p></body></html>'''


def test_normalize_price():
    assert normalize_price("£51.77") == 51.77


def test_relative_url_is_absolute():
    assert absolute_url("../book/index.html", "https://books.toscrape.com/catalogue/page-1.html") == "https://books.toscrape.com/book/index.html"


def test_missing_description_is_null():
    html = fixture("") .replace('<p></p>', '')
    raw = extract_raw_record(html, "https://books.toscrape.com/catalogue/test/index.html", "https://books.toscrape.com/catalogue/page-1.html", datetime.now(timezone.utc))
    assert raw["description"] is None


def test_duplicate_urls_are_deduplicated_by_identity():
    first = normalize_and_validate({"title":"A", "product_url":"https://books.toscrape.com/a/", "price_text":"£1.00", "availability_text":"In stock", "rating_text":"One", "description":None, "source_page":"https://books.toscrape.com/catalogue/page-1.html", "fetched_at":datetime.now(timezone.utc)})
    second = normalize_and_validate({"title":"A updated", "product_url":"https://books.toscrape.com/a/", "price_text":"£2.00", "availability_text":"In stock", "rating_text":"Two", "description":None, "source_page":"https://books.toscrape.com/catalogue/page-1.html", "fetched_at":datetime.now(timezone.utc)})
    records = {str(record.product_url): record for record in (first, second)}
    assert len(records) == 1
    assert records[str(first.product_url)].price_gbp == 2.0


def test_malformed_fixture_fails_validation():
    with pytest.raises(Exception):
        normalize_and_validate({"title":"", "product_url":"not-a-url", "price_text":"free", "availability_text":"", "rating_text":"", "description":None, "source_page":"http://bad", "fetched_at":datetime.now(timezone.utc)})
