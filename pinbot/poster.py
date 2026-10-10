"""Posts due pins through the Pinterest API v5.

Secrets come from environment variables (GitHub Actions secrets):
  PINTEREST_ACCESS_TOKEN                      required
  PINTEREST_REFRESH_TOKEN, PINTEREST_APP_ID,
  PINTEREST_APP_SECRET                        optional, lets the bot renew an expired token
  PINTEREST_API_BASE                          optional, defaults to the production API.
                                              Trial-access apps may need Pinterest's
                                              sandbox URL instead; see README.

Pinterest's API has no "publish later" option that I could confirm, so this
runs every ~30 minutes and posts whatever has come due.
"""
import base64
import os
import time
from datetime import datetime

import requests

from .catalog import is_placeholder
from .config import load_config
from .factory import ensure_image
from .scheduler import load_queue, save_queue

DEFAULT_BASE = "https://api.pinterest.com/v5"


class PinterestError(Exception):
    pass


class Client:
    def __init__(self):
        self.base = os.environ.get("PINTEREST_API_BASE", DEFAULT_BASE).rstrip("/")
        self.token = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
        if not self.token and not os.environ.get("PINTEREST_REFRESH_TOKEN"):
            raise PinterestError("Set PINTEREST_ACCESS_TOKEN (see README).")

    def refresh(self):
        rt = os.environ.get("PINTEREST_REFRESH_TOKEN")
        app, secret = os.environ.get("PINTEREST_APP_ID"), os.environ.get("PINTEREST_APP_SECRET")
        if not (rt and app and secret):
            raise PinterestError("Token rejected and no refresh credentials are set.")
        r = requests.post(f"{self.base}/oauth/token", auth=(app, secret), timeout=30,
                          data={"grant_type": "refresh_token", "refresh_token": rt})
        if r.status_code != 200:
            raise PinterestError(f"Token refresh failed: {r.status_code} {r.text[:200]}")
        j = r.json()
        self.token = j["access_token"]
        if j.get("refresh_token") and j["refresh_token"] != rt:
            print("NOTICE: Pinterest issued a new refresh token. Update the "
                  "PINTEREST_REFRESH_TOKEN secret if posting starts failing.")

    def request(self, method, path, **kw):
        if not self.token:
            self.refresh()
        for attempt in (1, 2):
            r = requests.request(method, f"{self.base}{path}", timeout=60,
                                 headers={"Authorization": f"Bearer {self.token}"}, **kw)
            if r.status_code == 401 and attempt == 1:
                self.refresh()
                continue
            return r

    def boards(self):
        out, bookmark = [], None
        while True:
            params = {"page_size": 100}
            if bookmark:
                params["bookmark"] = bookmark
            r = self.request("GET", "/boards", params=params)
            if r.status_code != 200:
                raise PinterestError(f"boards: {r.status_code} {r.text[:200]}")
            j = r.json()
            out += [(b["id"], b["name"]) for b in j.get("items", [])]
            bookmark = j.get("bookmark")
            if not bookmark:
                return out

    def create_pin(self, board_id, title, description, link, image_path, alt_text=""):
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        body = {
            "board_id": board_id,
            "title": title[:100],
            "description": description[:800],
            "link": link,
            "alt_text": alt_text[:500],
            "media_source": {"source_type": "image_base64", "content_type": "image/jpeg", "data": data},
        }
        r = self.request("POST", "/pins", json=body)
        return r


def post_due(books, live=False, max_posts=None, now=None):
    cfg = load_config()
    by_id = {b.id: b for b in books}
    now = now or datetime.now().astimezone()
    queue = load_queue()
    limit = max_posts or cfg["max_posts_per_run"]
    due = [e for e in queue if e["status"] == "scheduled" and datetime.fromisoformat(e["when"]) <= now]
    if not due:
        print("Nothing due right now.")
        return 0
    client = Client() if live else None
    posted = 0
    for e in due:
        late_h = (now - datetime.fromisoformat(e["when"])).total_seconds() / 3600
        if late_h > cfg["max_late_hours"]:
            e["status"] = "missed"
            print(f"missed (>{cfg['max_late_hours']}h late): {e['slot']} {e['book_id']}")
            continue
        if posted >= limit:
            break
        book = by_id.get(e["book_id"])
        if not book or not book.cover_path.exists():
            e["status"] = "skipped"
            e["error"] = "book or cover no longer in catalog"
            continue
        if is_placeholder(book.amazon_url):
            e["error"] = "amazon_url in catalog.csv is still a placeholder"
            print("HELD (placeholder Amazon link):", e["slot"], e["book_id"])
            continue
        e["link"] = book.amazon_url  # catalog.csv is the source of truth for links
        board_id = os.environ.get("PINTEREST_BOARD_" + "".join(c if c.isalnum() else "_" for c in e["board"]).upper()) \
            or cfg.get("board_ids", {}).get(e["board"])
        label = f"{e['slot']} | {e['book_id']} | {e['image_key']} -> {e['board']}"
        if not live:
            print("[dry run] would post:", label, "|", e["title"])
            posted += 1
            continue
        if not board_id:
            print(f"no board id for '{e['board']}' - run `python -m pinbot boards` and fill config.json")
            e["error"] = "missing board id"
            continue
        img = ensure_image(book, e["image_key"])
        r = client.create_pin(board_id, e["title"], e["description"], e["link"], img, e.get("alt_text", ""))
        if r.status_code in (200, 201):
            e["status"] = "posted"
            e["pin_id"] = r.json().get("id", "")
            e["posted_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            e.pop("error", None)
            posted += 1
            print("posted:", label)
            time.sleep(3)
        elif r.status_code == 429:
            print("Rate limited by Pinterest; stopping this run, will retry next time.")
            break
        else:
            e["error"] = f"{r.status_code} {r.text[:200]}"
            print("FAILED:", label, e["error"])
            if r.status_code in (400, 403) and "board" not in r.text.lower():
                e["status"] = "failed"
    if live:
        save_queue(queue)
    return posted
