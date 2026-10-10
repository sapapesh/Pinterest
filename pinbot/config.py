"""Loads config.json / templates.json and defines project paths."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog.csv"
COVERS = ROOT / "covers"
SAMPLES = ROOT / "samples"
OUT = ROOT / "out"
PUBLIC = ROOT / "public"
PINS = OUT / "pins"
STATE = ROOT / "state" / "queue.json"


def load_config():
    with open(ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


def load_templates():
    with open(ROOT / "templates.json", encoding="utf-8") as f:
        return json.load(f)
