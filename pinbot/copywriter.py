"""Builds titles, descriptions and overlay text from templates.json.

Everything is deterministic: the same book + image key always gets the same
words, so re-running a build never changes pins that were already scheduled.
"""
import hashlib

from .config import load_templates

_T = None


def templates():
    global _T
    if _T is None:
        _T = load_templates()
    return _T


def _h(s):
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)


def category_tpl(book):
    cats = templates()["categories"]
    return cats.get(book.category) or cats["logic"]


def _pick(lst, book, idx, salt=0):
    return lst[(_h(book.id) + idx * (1 + salt)) % len(lst)]


def _keywords(book):
    tpl = category_tpl(book)
    kws = [k for k in book.keywords if k.lower() != book.title.lower()]
    for k in tpl["default_keywords"]:
        if k not in kws:
            kws.append(k)
    return kws


def _fmt(text, book, idx):
    kws = _keywords(book)
    n = len(kws)
    tagline = book.tagline or category_tpl(book)["default_tagline"]
    return (text.format(
        title=book.title,
        subtitle=book.subtitle,
        kw1=kws[idx % n],
        kw2=kws[(idx + 1) % n],
        kw3=kws[(idx + 2) % n],
        tagline=tagline,
    )).replace("  ", " ").strip()


def _trim(text, limit):
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-|") + "…"


def sentence_case_first(s):
    return s[:1].upper() + s[1:] if s else s


def make_copy(book, variant, version, idx, has_sample=False):
    """idx = position of this image among all image keys (0..N-1)."""
    tpl = category_tpl(book)
    tt = templates()
    title = _trim(sentence_case_first(_fmt(_pick(tpl["titles"], book, idx), book, idx)), 100)
    body = _fmt(_pick(tpl["descriptions"], book, idx, 2), book, idx)
    kws = _keywords(book)
    kw_line = ", ".join(kws[(idx + j) % len(kws)] for j in range(3))
    desc = _trim(f"{body} {kw_line}.", 480)
    bullets = []
    pool = tpl["bullets"]
    start = (_h(book.id) + idx * 2) % len(pool)
    for i in range(3):
        bullets.append(pool[(start + i) % len(pool)])
    return {
        "title": title,
        "description": desc,
        "kicker": tpl["kicker"],
        "headline": _pick(tpl["headlines"], book, version - 1 + (_h(variant) % 3)),
        "bullets": bullets,
        "quote": _pick(tpl["quotes"], book, version - 1 + (_h(variant) % 5), 1),
        "teaser_head": _pick(tpl["sample_heads"] if has_sample and tpl.get("sample_heads")
                             else tpl["teaser_heads"], book, version - 1, 1),
        "cta": _pick(tt["cta"], book, idx),
        "alt_text": _trim(f"{book.title} - {tpl['label']} cover. {book.subtitle}".strip(), 480),
    }
