import argparse
import csv
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from .catalog import CATEGORIES, FIELDS, load_catalog, validate
from .config import CATALOG, COVERS, load_config
from . import factory, exporter, poster, scheduler


def _books(only=None, quiet=False):
    books = load_catalog()
    errors, warnings = validate(books)
    bad = {e.split("]")[0].lstrip("[") for e in errors if e.startswith("[")}
    if not quiet:
        ph = [w for w in warnings if "placeholder" in w]
        for w in warnings:
            if w not in ph:
                print("  warning:", w)
        if ph:
            print(f"  warning: {len(ph)} book(s) still have the placeholder Amazon link "
                  f"(they will be held back from posting and bulk export until you fill it in)")
        for e in errors:
            print("  ERROR:", e)
    good = [b for b in books if b.id not in bad]
    if only:
        good = [b for b in good if b.id in only]
    return books, good, errors, warnings


def cmd_check(a):
    books, good, errors, warnings = _books()
    print(f"{len(books)} books in catalog, {len(good)} ready to build, "
          f"{len(errors)} error(s), {len(warnings)} warning(s).")
    return 1 if errors and a.strict else 0


def cmd_build(a):
    _, good, _, _ = _books(a.book)
    total = 0
    for b in good:
        n = factory.build_book(b, force=a.force)
        total += n
        print(f"  {b.id}: {n} image(s) {'built' if n else 'up to date'}")
    print(f"Built {total} image(s) into out/pins/.")


def cmd_schedule(a):
    _, good, _, _ = _books(quiet=True)
    scheduler.schedule(good, days=a.days)


def cmd_export(a):
    _, good, _, _ = _books(quiet=True)
    exporter.export(good, preview=a.preview)


def cmd_post(a):
    _, good, _, _ = _books(quiet=True)
    poster.post_due(good, live=a.live, max_posts=a.max)


def cmd_run(a):
    """The everyday command: check, fill the queue, write the files."""
    books, good, errors, _ = _books()
    print(f"{len(good)} of {len(books)} books ready.")
    scheduler.schedule(good)
    exporter.export(good, preview=a.preview)


def cmd_ci(a):
    """What GitHub Actions runs every ~30 minutes."""
    _, good, _, _ = _books(quiet=True)
    scheduler.schedule(good, verbose=False)
    poster.post_due(good, live=True)


def cmd_status(a):
    q = scheduler.load_queue()
    c = Counter(e["status"] for e in q)
    print("Queue:", dict(c) or "empty")
    up = [e for e in q if e["status"] == "scheduled"][:12]
    if up:
        print("\nNext up:")
        for e in up:
            print(f"  {e['when'][:16].replace('T', ' ')}  {e['book_id']:<28} {e['image_key']:<9} -> {e['board']}")
    err = [e for e in q if e.get("error")]
    if err:
        print("\nProblems:")
        for e in err[-5:]:
            print(f"  {e['slot']} {e['book_id']}: {e['error']}")


def cmd_boards(a):
    cl = poster.Client()
    print("Paste these into config.json under \"board_ids\":\n")
    import json
    print(json.dumps({name: bid for bid, name in cl.boards()}, indent=2))


def cmd_add(a):
    """Add a new title in one command: copies the cover and appends a catalog row."""
    if a.category not in CATEGORIES:
        sys.exit(f"category must be one of {sorted(CATEGORIES)}")
    src = Path(a.cover)
    if not src.exists():
        sys.exit(f"cover not found: {src}")
    bid = a.id or "".join(c if c.isalnum() else "-" for c in a.title.lower()).strip("-")
    dest = COVERS / (bid + src.suffix.lower())
    COVERS.mkdir(exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy(src, dest)
    row = {k: "" for k in FIELDS}
    row.update(id=bid, title=a.title, subtitle=a.subtitle or "", category=a.category,
               amazon_url=a.url, cover_file=dest.name, keywords=a.keywords or "",
               board=a.board or "", holiday=a.holiday or "",
               added=datetime.now().date().isoformat(), tagline=a.tagline or "")
    with open(CATALOG, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)
    print(f"Added '{a.title}' as {bid}. Run `python -m pinbot run` to build and schedule it.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m pinbot", description="Pinterest autopilot for your book catalog")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("check", help="validate catalog.csv and covers")
    s.add_argument("--strict", action="store_true", help="exit with an error if anything is wrong")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("build", help="render pin images")
    s.add_argument("--book", nargs="*", help="only these book ids")
    s.add_argument("--force", action="store_true", help="re-render even if up to date")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("schedule", help="fill the posting queue")
    s.add_argument("--days", type=int, help="how many days ahead (default from config)")
    s.set_defaults(fn=cmd_schedule)

    s = sub.add_parser("export", help="write out/schedule.csv and Pinterest bulk-upload CSVs")
    s.add_argument("--preview", action="store_true", help="include pins with placeholder links (for looking only)")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("run", help="check + schedule + export (everyday command)")
    s.add_argument("--preview", action="store_true", help="include pins with placeholder links (for looking only)")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("post", help="post due pins via the Pinterest API (dry run unless --live)")
    s.add_argument("--live", action="store_true")
    s.add_argument("--max", type=int)
    s.set_defaults(fn=cmd_post)

    s = sub.add_parser("ci", help="schedule + post live (used by GitHub Actions)")
    s.set_defaults(fn=cmd_ci)

    s = sub.add_parser("status", help="show the queue")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("boards", help="list your Pinterest boards and their ids")
    s.set_defaults(fn=cmd_boards)

    s = sub.add_parser("add", help="add a new title")
    s.add_argument("--title", required=True)
    s.add_argument("--category", required=True, help="/".join(sorted(CATEGORIES)))
    s.add_argument("--url", required=True, help="Amazon link")
    s.add_argument("--cover", required=True, help="path to the front-cover image")
    s.add_argument("--subtitle")
    s.add_argument("--keywords", help="semicolon-separated")
    s.add_argument("--holiday", help="MM-DD (yearly) or YYYY-MM-DD (one-off); blank = evergreen")
    s.add_argument("--tagline")
    s.add_argument("--board")
    s.add_argument("--id")
    s.set_defaults(fn=cmd_add)

    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
