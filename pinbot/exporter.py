"""Writes human-readable and Pinterest-bulk-upload versions of the queue."""
import csv
import shutil
from datetime import datetime, timedelta, timezone

from .config import OUT, PUBLIC, load_config
from .catalog import is_placeholder
from .factory import ensure_image
from .scheduler import load_queue


def export(books, verbose=True, preview=False):
    """preview=True keeps pins whose Amazon link is still a placeholder (for looking only)."""
    cfg = load_config()
    by_id = {b.id: b for b in books}
    q = [e for e in load_queue() if e["status"] == "scheduled" and e["book_id"] in by_id]
    OUT.mkdir(parents=True, exist_ok=True)

    # 1) schedule overview for you to read
    with open(OUT / "schedule.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["when", "book", "board", "title", "image", "link"])
        for e in q:
            w.writerow([e["when"][:16].replace("T", " "), e["book_id"], e["board"], e["title"],
                        f"pins/{e['book_id']}/{e['image_key']}.jpg", e["link"]])

    # 2) Pinterest bulk-upload CSVs (only the next bulk_horizon_days, 200 rows per file)
    base = cfg.get("media_base_url", "").rstrip("/")
    cutoff = datetime.now().astimezone() + timedelta(days=cfg["bulk_horizon_days"])
    rows, held = [], 0
    for e in q:
        when = datetime.fromisoformat(e["when"])
        if when > cutoff:
            continue
        book = by_id[e["book_id"]]
        if is_placeholder(book.amazon_url) and not preview:
            held += 1
            continue
        img = ensure_image(book, e["image_key"])
        rel = f"{e['book_id']}/{e['image_key']}.jpg"
        (PUBLIC / e["book_id"]).mkdir(parents=True, exist_ok=True)
        shutil.copy(img, PUBLIC / rel)
        media = f"{base}/{rel}" if base else f"public/{rel}"
        rows.append([e["title"], media, e["board"], "", e["description"], book.amazon_url,
                     when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), ""])
    for old in OUT.glob("pinterest_bulk_*.csv"):
        old.unlink()
    per = cfg["bulk_rows_per_file"]
    files = 0
    for i in range(0, len(rows), per):
        files += 1
        with open(OUT / f"pinterest_bulk_{files:02d}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Title", "Media URL", "Pinterest board", "Thumbnail", "Description",
                        "Link", "Publish date", "Keywords"])
            w.writerows(rows[i:i + per])
    if verbose:
        print(f"Wrote out/schedule.csv ({len(q)} pins) and {files} bulk file(s) "
              f"covering {len(rows)} pins in the next {cfg['bulk_horizon_days']} days.")
        if held:
            print(f"  Held back {held} pin(s) whose Amazon link is still a placeholder "
                  f"(fix catalog.csv, or use --preview to include them for looking only).")
        if rows and not base:
            print("  Note: media_base_url is empty, so 'Media URL' holds local paths. "
                  "See README ('Bulk upload') before uploading.")
    return len(rows)
