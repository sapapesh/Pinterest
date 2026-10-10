# Pinterest autopilot for your books

Reads **catalog.csv**, makes Pinterest-ready pin images from your covers, plans a
30-day posting schedule, and either gives you bulk-upload files or posts for you
through the Pinterest API.

```
catalog.csv      one row per book  (this is the only thing you edit day to day)
covers/          front-cover images, one per book
samples/<id>/    optional: a real sample page per book (used for "peek inside" pins)
config.json      posts per day, posting times, boards, season rules
templates.json   wording for titles, descriptions and pin text, per category
out/             generated: schedule.csv, bulk-upload CSVs, pin images
state/queue.json the posting queue (what's scheduled / posted)
```

## 1. First-time setup

```
pip install -r requirements.txt
```

1. Put each book's **front cover** image in `covers/` (the front only, not the full
   KDP wrap). JPG or PNG.
2. Open `catalog.csv` and replace the sample rows with your real titles. Replace every
   `https://www.amazon.com/dp/XXXXXXXXXX` with the real link. **Pins with a placeholder
   link are never posted or exported.** The titles in the sample file were filled in
   from your project names, so check the spelling.
3. Run `python -m pinbot run`. It checks the catalog, builds the schedule and writes
   `out/schedule.csv`. Add `--preview` to include placeholder-link pins just to look.

## 2. Adding a new title later

Either:

```
python -m pinbot add --title "My New Book" --category mandala \
  --url "https://www.amazon.com/dp/B0XXXXXXX" --cover ~/Downloads/cover.jpg \
  --keywords "easter coloring book;spring mandalas;relaxing coloring" \
  --holiday 2027-03-28
python -m pinbot run
```

or copy the cover into `covers/`, add a row to `catalog.csv`, and run `python -m pinbot run`.
`python -m pinbot check` lists any cover without a row or row without a cover.

What the new title gets automatically:
- 8 pin images (4 layouts x 2 versions), colors taken from its own cover
- category-matched titles, descriptions and overlay text
- a boost (3x weight) for its first 21 days, then it joins the normal rotation
- if it has a `holiday`, it is promoted only in the 55 days before that date
  (`MM-DD` repeats every year; `YYYY-MM-DD` is a one-off, e.g. Easter)
- existing scheduled pins are never moved or duplicated

`category` must be one of: `logic`, `mandala`, `journal`, `mystery`, `wordsearch`.
Need another category? Add a block to `templates.json`, add its name to `CATEGORIES`
in `pinbot/catalog.py`, and give it a board and weight in `config.json`.

**Better "peek inside" pins:** drop a real page image into `samples/<book id>/`
(e.g. `samples/crown-logic-vol1/page.png`). Without one, mandala, logic, sudoku and
word-search books get a drawn stand-in in that style, and **journals get no peek-inside
pin at all**, because an invented page could misrepresent the product.

## 3. Two ways to publish

### A. Pinterest bulk upload (works today, no API approval)
Each month: run `python -m pinbot run`, then upload `out/pinterest_bulk_01.csv`
(`_02`, ... at 200 pins per file). The file itself carries the schedule: every row has a
**Publish date**, so Pinterest queues each pin for its own date and time. You do not schedule
pins one by one.

What Pinterest's own help page says (checked October 2026):
- Upload in the business account under Settings, "Import content" (bulk create) > CSV upload. Desktop only, up to 200 pins at a time.
- Required columns: Title (100 chars max), Media URL, Pinterest board. Also Description (500 max), Link, Publish date, Keywords. A board that doesn't exist yet is created automatically.
- **Media URL must be a public web link to the image.** A file on your computer will not work.
- **Publish date times are UTC.** The export already converts from your Central time.
- A future date schedules the pin; an empty date posts it immediately; a badly formatted date makes that pin fail.
- One Pinterest community thread reports future-dated bulk uploads failing for one account, so test with a small file first.

**Hosting the images (needed for the Media URL):**
1. Make a free **public** GitHub repo and push this folder to it. (Public is fine here; these are promo images.)
2. In `config.json` set `media_base_url` to
   `https://raw.githubusercontent.com/YOUR-NAME/YOUR-REPO/main/public`
3. `python -m pinbot export` copies each pin image into `public/` and writes working links.
   Push the `public/` folder, then upload the CSV to Pinterest.
Keep old images in `public/` until their pins have gone out.

### B. Fully automatic through the Pinterest API (GitHub Actions)
`.github/workflows/pinterest.yml` runs every 30 minutes, tops up the queue, posts whatever
is due, and saves the queue back to the repo.

1. Create a **private** GitHub repo and push this folder to it.
2. Create a Pinterest developer app and request API access. Read
   [Pinterest's access tiers](https://developers.pinterest.com/docs/key-concepts/access-tiers/).
   **Trial access is not enough to go public:** Pinterest states that Pins and boards created
   with Trial access are visible only to their creator (as sandbox items). Posting publicly
   needs Standard access. While you wait, Trial lets you test the whole pipeline.
   If your Trial app uses Pinterest's sandbox address, set a repo **variable**
   `PINTEREST_API_BASE` to it (check Pinterest's docs for the exact URL).
3. Get an access token with scopes `boards:read`, `pins:read`, `pins:write`,
   `user_accounts:read`. In the repo's Settings > Secrets and variables > Actions, add
   secrets `PINTEREST_ACCESS_TOKEN` and, so the bot can renew itself,
   `PINTEREST_REFRESH_TOKEN`, `PINTEREST_APP_ID`, `PINTEREST_APP_SECRET`.
4. Run locally once to get your board ids:
   `PINTEREST_ACCESS_TOKEN=... python -m pinbot boards`
   and paste the output into `"board_ids"` in `config.json`.
5. Test without posting: `python -m pinbot post` (dry run). When happy, press
   **Run workflow** on the Actions tab, or just wait for the schedule.

Notes: GitHub's scheduler can run a few minutes late and pauses scheduled workflows in repos
with no activity for 60 days. A pin more than 12 hours overdue is marked `missed` instead of
being posted in a burst. Check on things with `python -m pinbot status`.

## 4. How the schedule is chosen

- **Volume:** 2 pins/day for the first 7 days, then 4/day (`pins_per_day`).
- **Times:** best-guess evening/midday slots in your time zone, nudged by up to 12 minutes.
  Pinterest timing advice varies, so treat these as a starting point and adjust
  `post_slots_priority` after you see your own analytics.
- **Mix:** a category is picked first (so 13 mystery volumes can't crowd out everything else),
  then a book inside it. Change the balance with `category_weights`.
- **Seasonal:** inside the promotion window, weight rises toward the holiday date.
- **No repeats:** same book not back to back; same image not reused for 21 days.
- Choices are seeded, so re-running gives the same plan. Change `seed` for a different shuffle.

## 5. Commands

| Command | What it does |
|---|---|
| `python -m pinbot run` | check + fill schedule + write export files (everyday command) |
| `python -m pinbot check` | validate catalog and covers |
| `python -m pinbot build [--book id] [--force]` | render pin images |
| `python -m pinbot status` | show queue and any problems |
| `python -m pinbot add ...` | add a new title |
| `python -m pinbot post [--live]` | post due pins (dry run unless `--live`) |
| `python -m pinbot boards` | list your Pinterest board ids |
