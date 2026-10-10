"""Fills the posting queue (state/queue.json) with the next N days of pins.

Rules, in plain words:
  * 2 pins/day for the first week (warm-up), then pins_per_day, at the best
    posting times from config.json, nudged a few minutes so it isn't robotic.
  * Pick a category first (so 13 mystery books can't crowd out everything
    else), then a book inside it.
  * Seasonal books only appear inside their promotion window
    (holiday minus seasonal_lead_days) and get heavier the closer it gets.
  * New titles get a boost for their first few weeks.
  * A book isn't repeated back to back, and an image isn't reused until its
    cooldown has passed.
  * Re-running never moves or duplicates anything already in the queue; it
    only fills empty slots. Choices are seeded, so they are reproducible.
"""
import json
import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import STATE, load_config
from .factory import copy_for, image_keys
from .catalog import is_placeholder

DONE = {"posted"}


def load_queue():
    if STATE.exists():
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_queue(q):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    q.sort(key=lambda e: e["when"])
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=1, ensure_ascii=False)


def _tz(cfg):
    return ZoneInfo(cfg["timezone"])


def pins_for_day(cfg, day, first_day):
    if (day - first_day).days < cfg["warmup_days"]:
        return min(cfg["warmup_pins_per_day"], cfg["pins_per_day"])
    return cfg["pins_per_day"]


def book_weight(cfg, book, day):
    """0 means 'not eligible today'."""
    d = book.days_to_holiday(day, cfg["seasonal_lead_days"])
    if d is None:
        return 0.0
    w = 1.0
    if d >= 0:  # seasonal and inside window: ramps up toward the holiday
        ramp = 1 - d / max(cfg["seasonal_lead_days"], 1)
        w += cfg["seasonal_boost"] * ramp
    added = book.added_date
    if added and 0 <= (day - added).days <= cfg["new_title_days"]:
        w *= cfg["new_title_boost"]
    return w


def schedule(books, days=None, now=None, verbose=True):
    cfg = load_config()
    tz = _tz(cfg)
    now = now or datetime.now(tz)
    horizon = days or cfg["horizon_days"]
    queue = load_queue()
    by_id = {b.id: b for b in books}
    keys = image_keys()

    taken = {e["slot"] for e in queue}
    last_book_day, last_key_day = {}, {}
    for e in queue:
        d = date.fromisoformat(e["when"][:10])
        last_book_day[e["book_id"]] = max(last_book_day.get(e["book_id"], d), d)
        kk = (e["book_id"], e["image_key"])
        last_key_day[kk] = max(last_key_day.get(kk, d), d)

    active = [e for e in queue if e["status"] == "scheduled"]
    first_day = min([date.fromisoformat(e["when"][:10]) for e in queue] + [now.date()])
    added = 0
    prev_book = queue[-1]["book_id"] if queue else None
    slots_pri = cfg["post_slots_priority"]

    for offset in range(horizon):
        day = now.date() + timedelta(days=offset)
        n = pins_for_day(cfg, day, first_day)
        todays = sorted(slots_pri[:n])
        used_today = {e["book_id"] for e in queue if e["when"][:10] == day.isoformat()}
        for slot in todays:
            slot_id = f"{day.isoformat()}#{slot}"
            if slot_id in taken:
                continue
            hh, mm = map(int, slot.split(":"))
            rng = random.Random(f"{cfg['seed']}|{slot_id}")
            jitter = rng.randint(-cfg["slot_jitter_minutes"], cfg["slot_jitter_minutes"])
            when = datetime.combine(day, time(hh, mm), tzinfo=tz) + timedelta(minutes=jitter)
            if when <= now + timedelta(minutes=20):
                continue

            # --- choose a book
            cands = []
            for b in books:
                if not b.cover_path.exists():
                    continue
                w = book_weight(cfg, b, day)
                if w <= 0 or b.id == prev_book:
                    continue
                if b.id in used_today:
                    continue
                last = last_book_day.get(b.id)
                if last and (day - last).days < cfg["book_cooldown_days"]:
                    w *= 0.08
                cands.append((b, w))
            if not cands:
                continue
            cat_w = {}
            for b, w in cands:
                cat_w.setdefault(b.category, 0)
                cat_w[b.category] = cfg["category_weights"].get(b.category, 1.0)
            cats = list(cat_w)
            cat = rng.choices(cats, weights=[cat_w[c] for c in cats])[0]
            pool = [(b, w) for b, w in cands if b.category == cat]
            book = rng.choices([b for b, _ in pool], weights=[w for _, w in pool])[0]

            # --- choose an image: the one unused for longest, ties random
            def age(k):
                l = last_key_day.get((book.id, k))
                return (day - l).days if l else 10**6
            ordered = sorted(image_keys(book), key=lambda k: (-age(k), rng.random()))
            ok = [k for k in ordered if age(k) >= cfg["image_cooldown_days"]]
            key = (ok or ordered)[0]

            cp = copy_for(book, key)
            board = book.board or cfg["boards"].get(book.category, "")
            queue.append({
                "slot": slot_id,
                "when": when.isoformat(),
                "book_id": book.id,
                "image_key": key,
                "board": board,
                "title": cp["title"],
                "description": cp["description"],
                "alt_text": cp["alt_text"],
                "link": book.amazon_url,
                "status": "scheduled",
            })
            taken.add(slot_id)
            used_today.add(book.id)
            last_book_day[book.id] = day
            last_key_day[(book.id, key)] = day
            prev_book = book.id
            added += 1
    save_queue(queue)
    if verbose:
        print(f"Scheduled {added} new pins. Queue now holds "
              f"{sum(1 for e in queue if e['status'] == 'scheduled')} upcoming pins.")
    return added
