"""Reads catalog.csv, validates it, and works out seasonal windows."""
import csv
import re
from dataclasses import dataclass
from datetime import date, timedelta

from .config import CATALOG, COVERS

FIELDS = ["id", "title", "subtitle", "category", "amazon_url", "cover_file",
          "keywords", "board", "holiday", "added", "tagline"]
CATEGORIES = {"logic", "mandala", "journal", "mystery", "wordsearch"}


@dataclass
class Book:
    id: str
    title: str
    subtitle: str
    category: str
    amazon_url: str
    cover_file: str
    keywords: list
    board: str
    holiday: str
    added: str
    tagline: str

    @property
    def cover_path(self):
        return COVERS / self.cover_file

    @property
    def added_date(self):
        try:
            return date.fromisoformat(self.added)
        except ValueError:
            return None

    def holiday_dates(self, year):
        """Holiday date(s) to consider for a given calendar year.
        'MM-DD' repeats every year; 'YYYY-MM-DD' is a single one-off date."""
        h = self.holiday.strip()
        if not h:
            return []
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", h):
            return [date.fromisoformat(h)]
        m = re.fullmatch(r"(\d{2})-(\d{2})", h)
        if not m:
            return []
        try:
            return [date(year, int(m.group(1)), int(m.group(2)))]
        except ValueError:
            return []

    def days_to_holiday(self, day, lead):
        """Days until the holiday if `day` falls inside its promotion window,
        else None. Evergreen books (no holiday) return -1 (always active)."""
        if not self.holiday.strip():
            return -1
        for y in (day.year, day.year + 1):
            for hd in self.holiday_dates(y):
                delta = (hd - day).days
                if 0 <= delta <= lead:
                    return delta
        return None


def is_placeholder(url):
    return (not url) or "XXXXXXXXXX" in url


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def load_catalog(path=CATALOG):
    books = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = (row.get("title") or "").strip()
            if not title or (row.get("id") or "").strip().startswith("#"):
                continue
            bid = (row.get("id") or "").strip() or _slug(title)
            kws = [k.strip() for k in (row.get("keywords") or "").split(";") if k.strip()]
            books.append(Book(
                id=bid,
                title=title,
                subtitle=(row.get("subtitle") or "").strip(),
                category=(row.get("category") or "").strip().lower(),
                amazon_url=(row.get("amazon_url") or "").strip(),
                cover_file=(row.get("cover_file") or "").strip(),
                keywords=kws,
                board=(row.get("board") or "").strip(),
                holiday=(row.get("holiday") or "").strip(),
                added=(row.get("added") or "").strip(),
                tagline=(row.get("tagline") or "").strip(),
            ))
    return books


def validate(books):
    """Returns (errors, warnings). Errors block building a book's pins."""
    errors, warnings = [], []
    seen = set()
    for b in books:
        tag = f"[{b.id}]"
        if b.id in seen:
            errors.append(f"{tag} duplicate id")
        seen.add(b.id)
        if b.category not in CATEGORIES:
            errors.append(f"{tag} category '{b.category}' must be one of {sorted(CATEGORIES)}")
        if not b.cover_file:
            errors.append(f"{tag} no cover_file given")
        elif not b.cover_path.exists():
            errors.append(f"{tag} cover not found: covers/{b.cover_file}")
        if not b.amazon_url.startswith("http"):
            errors.append(f"{tag} amazon_url missing or not a link")
        elif "XXXXXXXXXX" in b.amazon_url:
            warnings.append(f"{tag} amazon_url is still the placeholder")
        if b.holiday and not (re.fullmatch(r"\d{2}-\d{2}", b.holiday) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", b.holiday)):
            errors.append(f"{tag} holiday '{b.holiday}' must be MM-DD or YYYY-MM-DD")
        if b.added and b.added_date is None:
            errors.append(f"{tag} added '{b.added}' must be YYYY-MM-DD")
        if len(b.keywords) < 3:
            warnings.append(f"{tag} fewer than 3 keywords; category defaults will fill in")
    # covers with no catalog row
    if COVERS.exists():
        known = {b.cover_file for b in books}
        for p in sorted(COVERS.iterdir()):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.name not in known:
                warnings.append(f"covers/{p.name} has no row in catalog.csv")
    return errors, warnings
