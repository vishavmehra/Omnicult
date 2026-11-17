"""Opt-in live check of the curated culture dataset: every cited excerpt must appear verbatim on its URL.

    uv --directory backend run python -m scripts.culture_dataset_verify [FILE_OR_DIR ...]

With no argument it checks every file in app/integrations/culture/data/curated/. Each source needs a
`url` and an exact `excerpt`; the script fetches the page, strips markup and citation markers
(`[12]`, `[a]`, `[citation needed]`), collapses whitespace, and requires the excerpt (same normalisation)
to be a contiguous substring. Exit code 0 only when every source verifies. Uses the descriptive User-Agent
from settings and a short delay between requests; it never sends anything but GET requests to the cited URL.
"""

import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import httpx

from app.core.config import get_settings

DATA_DIR = Path(__file__).resolve().parent.parent / "app" / "integrations" / "culture" / "data" / "curated"
_SKIP_TAGS = {"script", "style", "noscript", "template"}
_CITATION = re.compile(r"\[(?:\d+|[a-z]|citation needed|clarification needed|note \d+)\]", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in {"p", "br", "li", "tr", "div", "h1", "h2", "h3", "h4", "td", "th"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def normalise(text: str) -> str:
    text = _CITATION.sub("", text.replace(" ", " ").replace("​", ""))
    return re.sub(r"\s+", " ", text).strip().lower()


def page_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return normalise("".join(parser.parts))  # inline nodes join without spaces: "Bengali" + ", 5.00%" stays "Bengali, 5.00%"


def fetch(client: httpx.Client, url: str, cache: dict[str, str | None]) -> str | None:
    if url in cache:
        return cache[url]
    time.sleep(0.4)
    try:
        response = client.get(url, follow_redirects=True)
        response.raise_for_status()
        cache[url] = page_text(response.text)
    except httpx.HTTPError as exc:
        print(f"  FETCH FAILED {url}: {type(exc).__name__}")
        cache[url] = None
    return cache[url]


def verify_file(path: Path, client: httpx.Client, cache: dict[str, str | None]) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    checked = failed = 0
    for entry in data["entries"]:
        for source in entry.get("sources", []):
            checked += 1
            text = fetch(client, source["url"], cache)
            ok = text is not None and normalise(source["excerpt"]) in text
            if not ok:
                failed += 1
                print(f"  FAIL {entry['id']}: excerpt not found at {source['url']}")
    print(f"{path.name}: {checked - failed}/{checked} sources verified")
    return checked, failed


def main(argv: list[str]) -> int:
    targets: list[Path] = []
    for arg in argv or [str(DATA_DIR)]:
        path = Path(arg)
        targets.extend(sorted(path.glob("*.json")) if path.is_dir() else [path])
    headers = {"User-Agent": get_settings().wikimedia_user_agent}
    cache: dict[str, str | None] = {}
    total = failed = 0
    with httpx.Client(headers=headers, timeout=30) as client:
        for path in targets:
            checked, bad = verify_file(path, client, cache)
            total += checked
            failed += bad
    print(f"TOTAL {total - failed}/{total} verified")
    return 0 if failed == 0 and total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
