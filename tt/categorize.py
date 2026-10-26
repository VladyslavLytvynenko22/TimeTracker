import re
import threading

from .db import KIND_COLORS


class Category:
    __slots__ = ("id", "path", "kind", "color")

    def __init__(self, id, path, kind, color):
        self.id = id
        self.path = path
        self.kind = kind
        self.color = color or KIND_COLORS.get(kind, KIND_COLORS["work"])

    def as_dict(self):
        return {"id": self.id, "path": self.path, "kind": self.kind, "color": self.color}


class Categorizer:
    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.reload()

    def reload(self):
        cats = {}
        for r in self.db.categories():
            cats[r["id"]] = Category(r["id"], r["path"], r["kind"], r["color"])
        rules = []
        broken = []
        for r in self.db.rules():
            if not r["enabled"]:
                continue
            try:
                rx = re.compile(r["pattern"], re.IGNORECASE if r["ignore_case"] else 0)
            except re.error as e:
                broken.append({"id": r["id"], "pattern": r["pattern"], "error": str(e)})
                continue
            rules.append((rx, r["category_id"], r["id"]))
        overrides = {(o["app"], o["title"]): o["category_id"] for o in self.db.overrides()}
        event_overrides = {o["event_id"]: o["category_id"] for o in self.db.event_overrides()}
        uncategorized = next((c for c in cats.values() if c.path == "Uncategorized"), None)
        afk = next((c for c in cats.values() if c.path == "AFK"), None)
        call_path = self.db.get_kv("calls_category", "Work > Chat & Calls") or ""
        call_cat = next((c for c in cats.values() if c.path == call_path), None)
        with self.lock:
            self.cats = cats
            self.rules = rules
            self.broken = broken
            self.overrides = overrides
            self.event_overrides = event_overrides
            self.uncategorized = uncategorized or Category(0, "Uncategorized", "work", None)
            self.afk = afk or Category(-1, "AFK", "afk", None)
            self.call_cat = call_cat
            self.cache = {}

    def category(self, cat_id):
        return self.cats.get(cat_id)

    def categorize(self, app, title, afk, event_id=None, call=False):
        if event_id is not None:
            cid = self.event_overrides.get(event_id)
            if cid in self.cats:
                return self.cats[cid], "block"
        if afk:
            return self.afk, "afk"
        if call and self.call_cat is not None:
            return self.call_cat, "call"
        key = (app, title)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        cid = self.overrides.get(key)
        if cid in self.cats:
            res = (self.cats[cid], "manual")
        else:
            res = None
            for rx, rcid, rid in self.rules:
                if rx.search(title) or rx.search(app):
                    cat = self.cats.get(rcid)
                    if cat:
                        res = (cat, "rule:%d" % rid)
                        break
            if res is None:
                res = (self.uncategorized, "default")
        if len(self.cache) > 20000:
            self.cache.clear()
        self.cache[key] = res
        return res
