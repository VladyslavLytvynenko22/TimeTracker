import csv
import io
import json
import logging
import mimetypes
import os
import re
import threading
import time
import urllib.parse
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import summary as summ
from .db import KIND_COLORS, PROTECTED_CATEGORIES

log = logging.getLogger("tt.server")
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
KINDS = ("work", "nonwork", "afk")


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class App:
    def __init__(self, db, cat, tracker, notifier, data_dir, on_quit):
        self.db = db
        self.cat = cat
        self.tracker = tracker
        self.notifier = notifier
        self.data_dir = data_dir
        self.on_quit = on_quit
        self.started = time.time()

    def changed(self):
        self.cat.reload()

    def settings(self):
        return self.db.get_settings()

    def status(self):
        s = self.settings()
        st = dict(self.tracker.status)
        cur = self.tracker.current_event()
        c, source = self.cat.categorize(st["app"], st["title"], st["afk"], cur["id"] if cur else None, cur["call"] if cur else False)
        day, work = summ.work_seconds_today(self.db, self.cat, s["day_start"])
        return {
            "app": st["app"], "title": st["title"], "afk": st["afk"], "idle": st["idle"], "paused": self.tracker.paused,
            "skipped": bool(st.get("skipped")), "media": bool(st.get("media")),
            "call": bool(st.get("call")), "call_apps": st.get("call_apps") or [],
            "since": cur["start"] if cur else None, "category": c.path, "kind": c.kind, "source": source,
            "today": day.isoformat(), "work_today": work, "target_minutes": s["work_target_min"],
            "uptime": time.time() - self.started, "broken_rules": self.cat.broken, "data_dir": self.data_dir,
        }

    def summary(self, q):
        s = self.settings()
        kind = q.get("range", "day")
        if kind not in ("day", "week", "month"):
            kind = "day"
        d = q.get("date")
        if d:
            try:
                d = date.fromisoformat(d)
            except ValueError:
                raise ApiError("bad date")
        else:
            d = summ.logical_date(time.time(), s["day_start"])
        return summ.compute(self.db, self.cat, kind, d, s["day_start"], s["work_target_min"], s.get("workdays", [0, 1, 2, 3, 4]))

    def _range_args(self, q):
        s = self.settings()
        kind = q.get("range", "day")
        if kind not in ("day", "week", "month"):
            kind = "day"
        d = q.get("date")
        try:
            d = date.fromisoformat(d) if d else summ.logical_date(time.time(), s["day_start"])
        except ValueError:
            raise ApiError("bad date")
        return s, kind, d

    def export_csv(self, q):
        s, kind, d = self._range_args(q)
        mode = q.get("mode", "windows")
        buf = io.StringIO()
        wr = csv.writer(buf, lineterminator="\n")
        fmt_ts = lambda ts: datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        hms = lambda sec: "%d:%02d:%02d" % (int(sec) // 3600, (int(sec) % 3600) // 60, int(sec) % 60)
        if mode == "days":
            res = summ.compute(self.db, self.cat, kind, d, s["day_start"], s["work_target_min"], s.get("workdays", [0, 1, 2, 3, 4]))
            wr.writerow(["date", "work", "not_work", "away", "work_hours", "not_work_hours", "away_hours", "top_categories"])
            for day in res["days"]:
                top = "; ".join("%s %s" % (c["path"], hms(c["seconds"])) for c in day.get("categories", [])[:5])
                wr.writerow([day["date"], hms(day["work"]), hms(day["nonwork"]), hms(day["afk"]),
                             round(day["work"] / 3600, 2), round(day["nonwork"] / 3600, 2), round(day["afk"] / 3600, 2), top])
        elif mode == "segments":
            wr.writerow(["start", "end", "duration", "seconds", "app", "title", "category", "kind", "set_by", "on_call"])
            for sg in summ.segments(self.db, self.cat, kind, d, s["day_start"]):
                wr.writerow([fmt_ts(sg["start"]), fmt_ts(sg["end"]), hms(sg["end"] - sg["start"]), int(sg["end"] - sg["start"]),
                             sg["app"], sg["title"], sg["category"], sg["kind"], sg["source"], "yes" if sg["call"] else ""])
        else:
            res = summ.compute(self.db, self.cat, kind, d, s["day_start"], s["work_target_min"], s.get("workdays", [0, 1, 2, 3, 4]))
            wr.writerow(["app", "title", "category", "kind", "duration", "seconds", "segments", "first_seen", "last_seen", "set_by"])
            for it in sorted(res["items"], key=lambda x: -x["seconds"]):
                wr.writerow([it["app"], it["title"], it["category"], it["kind"], hms(it["seconds"]), int(it["seconds"]),
                             it["count"], fmt_ts(it["first"]), fmt_ts(it["last"]), it["source"]])
        name = "timetracker-%s-%s-%s.csv" % (kind, d.isoformat(), mode)
        return name, ("﻿" + buf.getvalue()).encode("utf-8")

    def item_events(self, q):
        try:
            start = float(q["from"])
            end = float(q["to"])
        except (KeyError, ValueError):
            raise ApiError("from/to required")
        app = q.get("app", "")
        title = q.get("title")
        rows = self.db.events_overlapping(start, end)
        out = []
        for r in rows:
            if r["app"] != app or (title is not None and r["title"] != title):
                continue
            c, source = self.cat.categorize(r["app"], r["title"], r["afk"], r["id"], r.get("call"))
            out.append({"id": r["id"], "start": max(r["start"], start), "end": min(r["end"], end), "title": r["title"],
                        "category_id": c.id, "category": c.path, "kind": c.kind, "source": source})
        return out[:2000]

    def save_category(self, body):
        path = " > ".join(p.strip() for p in str(body.get("path", "")).split(">") if p.strip())
        if not path:
            raise ApiError("name required")
        kind = body.get("kind", "work")
        if kind not in KINDS:
            raise ApiError("bad kind")
        color = body.get("color") or None
        if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ApiError("color must be #rrggbb")
        cid = body.get("id")
        if cid:
            old = self.db.query("SELECT path FROM categories WHERE id=?", (cid,))
            if not old:
                raise ApiError("not found", 404)
            if old[0]["path"] in PROTECTED_CATEGORIES and path != old[0]["path"]:
                raise ApiError("this category cannot be renamed")
            self.db.execute("UPDATE categories SET path=?, kind=?, color=? WHERE id=?", (path, kind, color, cid))
            if old[0]["path"] != path:
                prefix = old[0]["path"] + " > "
                for r in self.db.query("SELECT id, path FROM categories WHERE path LIKE ?", (prefix.replace("%", "\\%") + "%",)):
                    if r["path"].startswith(prefix):
                        self.db.execute("UPDATE categories SET path=? WHERE id=?", (path + " > " + r["path"][len(prefix):], r["id"]))
        else:
            if self.db.query("SELECT 1 FROM categories WHERE path=?", (path,)):
                raise ApiError("category already exists")
            cur = self.db.execute("INSERT INTO categories(path, kind, color) VALUES(?,?,?)", (path, kind, color))
            cid = cur.lastrowid
        self.changed()
        return {"id": cid}

    def delete_category(self, cid):
        row = self.db.query("SELECT path FROM categories WHERE id=?", (cid,))
        if not row:
            raise ApiError("not found", 404)
        if row[0]["path"] in PROTECTED_CATEGORIES:
            raise ApiError("this category cannot be deleted")
        self.db.execute("DELETE FROM categories WHERE id=?", (cid,))
        self.changed()
        return {"ok": True}

    def save_rule(self, body):
        pattern = str(body.get("pattern", "")).strip()
        if not pattern:
            raise ApiError("pattern required")
        try:
            re.compile(pattern)
        except re.error as e:
            raise ApiError("invalid regex: %s" % e)
        cid = body.get("category_id")
        if not self.db.query("SELECT 1 FROM categories WHERE id=?", (cid,)):
            raise ApiError("category not found")
        ic = 1 if body.get("ignore_case", True) else 0
        en = 1 if body.get("enabled", True) else 0
        rid = body.get("id")
        if rid:
            self.db.execute("UPDATE rules SET pattern=?, category_id=?, ignore_case=?, enabled=? WHERE id=?",
                            (pattern, cid, ic, en, rid))
        else:
            if body.get("position") == "top":
                self.db.shift_rules_down()
                prio = 0
            else:
                prio = self.db.next_rule_priority()
            cur = self.db.execute("INSERT INTO rules(category_id, pattern, ignore_case, priority, enabled) VALUES(?,?,?,?,?)",
                                  (cid, pattern, ic, prio, en))
            rid = cur.lastrowid
        self.changed()
        return {"id": rid}

    def delete_rule(self, rid):
        self.db.execute("DELETE FROM rules WHERE id=?", (rid,))
        self.changed()
        return {"ok": True}

    def reorder_rules(self, body):
        ids = body.get("ids") or []
        with self.db.lock:
            for i, rid in enumerate(ids):
                self.db.execute("UPDATE rules SET priority=? WHERE id=?", (i, rid))
        self.changed()
        return {"ok": True}

    def test_rule(self, body):
        pattern = str(body.get("pattern", ""))
        try:
            rx = re.compile(pattern, re.IGNORECASE if body.get("ignore_case", True) else 0)
        except re.error as e:
            return {"ok": False, "error": str(e)}
        texts = body.get("texts") or []
        return {"ok": True, "matches": [bool(rx.search(t.get("title", "")) or rx.search(t.get("app", ""))) for t in texts]}

    def save_override(self, body):
        app = body.get("app", "")
        title = body.get("title", "")
        cid = body.get("category_id")
        if cid is None:
            self.db.execute("DELETE FROM overrides WHERE app=? AND title=?", (app, title))
        else:
            if not self.db.query("SELECT 1 FROM categories WHERE id=?", (cid,)):
                raise ApiError("category not found")
            self.db.execute("INSERT INTO overrides(app, title, category_id) VALUES(?,?,?) "
                            "ON CONFLICT(app, title) DO UPDATE SET category_id=excluded.category_id", (app, title, cid))
        self.changed()
        return {"ok": True}

    def delete_override(self, oid):
        self.db.execute("DELETE FROM overrides WHERE id=?", (oid,))
        self.changed()
        return {"ok": True}

    def save_event_override(self, body):
        ids = [int(i) for i in body.get("ids") or []]
        cid = body.get("category_id")
        with self.db.lock:
            for eid in ids:
                if cid is None:
                    self.db.execute("DELETE FROM event_overrides WHERE event_id=?", (eid,))
                else:
                    self.db.execute("INSERT INTO event_overrides(event_id, category_id) VALUES(?,?) "
                                    "ON CONFLICT(event_id) DO UPDATE SET category_id=excluded.category_id", (eid, cid))
        self.changed()
        return {"ok": True}

    def save_settings(self, body):
        s = self.settings()
        if "day_start" in body:
            v = str(body["day_start"])
            if not re.fullmatch(r"\d{1,2}:\d{2}", v):
                raise ApiError("day start must be HH:MM")
            h, m = v.split(":")
            if int(h) > 23 or int(m) > 59:
                raise ApiError("day start must be HH:MM")
            self.db.set_setting("day_start", "%02d:%02d" % (int(h), int(m)))
        for key, lo, hi in (("afk_timeout_min", 1, 600), ("work_target_min", 1, 1440), ("port", 1024, 65535), ("poll_interval_sec", 1, 60)):
            if key in body:
                try:
                    v = int(body[key])
                except (TypeError, ValueError):
                    raise ApiError("%s must be a number" % key)
                if not lo <= v <= hi:
                    raise ApiError("%s must be between %d and %d" % (key, lo, hi))
                self.db.set_setting(key, v)
        if "media_keeps_active" in body:
            self.db.set_setting("media_keeps_active", bool(body["media_keeps_active"]))
        if "calls_category" in body:
            path = body["calls_category"] or ""
            if path and not self.db.query("SELECT 1 FROM categories WHERE path=?", (path,)):
                raise ApiError("calls category not found")
            self.db.set_setting("calls_category", path)
        if "weekly_summary" in body and isinstance(body["weekly_summary"], dict):
            ws = dict(s["weekly_summary"])
            b = body["weekly_summary"]
            if "enabled" in b:
                ws["enabled"] = bool(b["enabled"])
            if "weekday" in b:
                ws["weekday"] = min(6, max(0, int(b["weekday"])))
            if "time" in b:
                if not re.fullmatch(r"\d{2}:\d{2}", str(b["time"])):
                    raise ApiError("weekly summary time must be HH:MM")
                ws["time"] = str(b["time"])
            self.db.set_setting("weekly_summary", ws)
        if "private_windows" in body:
            if body["private_windows"] not in ("hide", "skip", "track"):
                raise ApiError("private_windows must be hide, skip or track")
            self.db.set_setting("private_windows", body["private_windows"])
        if "workdays" in body:
            try:
                days = sorted({int(x) for x in body["workdays"] if 0 <= int(x) <= 6})
            except (TypeError, ValueError):
                raise ApiError("workdays must be weekday numbers 0-6")
            self.db.set_setting("workdays", days)
        if "notifications" in body and isinstance(body["notifications"], dict):
            n = dict(s["notifications"])
            b = body["notifications"]
            for k in ("enabled", "at_end", "overtime"):
                if k in b:
                    n[k] = bool(b[k])
            if "overtime_every_min" in b:
                n["overtime_every_min"] = max(1, int(b["overtime_every_min"] or 1))
            if "before_end_min" in b:
                vals = b["before_end_min"]
                if isinstance(vals, str):
                    vals = [x for x in re.split(r"[,\s]+", vals) if x]
                n["before_end_min"] = sorted({int(x) for x in vals if int(x) > 0}, reverse=True)
            self.db.set_setting("notifications", n)
        self.tracker.reload_settings()
        self.changed()
        return self.settings()

    def import_aw(self, body):
        cats = body.get("categories") or []
        added = 0
        existing = {c["path"]: c["id"] for c in self.db.categories()}
        for c in sorted(cats, key=lambda x: -len(x.get("name") or [])):
            name = c.get("name") or []
            if not name:
                continue
            path = " > ".join(n.strip() for n in name)
            top = name[0].strip().lower()
            kind = "afk" if top == "afk" else ("nonwork" if top in ("other", "game", "games", "entertainment", "private") else "work")
            color = (c.get("data") or {}).get("color")
            if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                color = None
            cid = existing.get(path)
            if not cid:
                cid = self.db.execute("INSERT INTO categories(path, kind, color) VALUES(?,?,?)", (path, kind, color)).lastrowid
                existing[path] = cid
            rule = c.get("rule") or {}
            if rule.get("type") == "regex" and rule.get("regex"):
                if not self.db.query("SELECT 1 FROM rules WHERE category_id=? AND pattern=?", (cid, rule["regex"])):
                    self.db.execute("INSERT INTO rules(category_id, pattern, ignore_case, priority, enabled) VALUES(?,?,?,?,1)",
                                    (cid, rule["regex"], 1 if rule.get("ignore_case", True) else 0, self.db.next_rule_priority()))
                    added += 1
        self.changed()
        return {"ok": True, "rules_added": added}


class Handler(BaseHTTPRequestHandler):
    app = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.debug("%s " + fmt, self.address_string(), *args)

    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ApiError("invalid JSON body")

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        rel = os.path.normpath(path.lstrip("/"))
        full = os.path.join(STATIC_DIR, rel)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}
        app = self.app
        try:
            p = url.path
            if p == "/api/status":
                return self._json(app.status())
            if p == "/api/summary":
                return self._json(app.summary(q))
            if p == "/api/events":
                return self._json(app.item_events(q))
            if p == "/api/export.csv":
                name, data = app.export_csv(q)
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            if p == "/api/categorize":
                c, source = app.cat.categorize(q.get("app", ""), q.get("title", ""), False)
                return self._json({"category": c.path, "category_id": c.id, "kind": c.kind, "source": source})
            if p == "/api/categories":
                return self._json([{**c, "color": c["color"] or KIND_COLORS[c["kind"]], "protected": c["path"] in PROTECTED_CATEGORIES}
                                   for c in app.db.categories()])
            if p == "/api/rules":
                return self._json({"rules": app.db.rules(), "broken": app.cat.broken})
            if p == "/api/overrides":
                return self._json(app.db.overrides())
            if p == "/api/settings":
                return self._json({**app.settings(), "data_dir": app.data_dir})
            if p.startswith("/api/"):
                raise ApiError("not found", 404)
            return self._static(p)
        except ApiError as e:
            return self._json({"error": str(e)}, e.status)
        except Exception as e:
            log.exception("GET %s failed", self.path)
            return self._json({"error": "server error: %s" % e}, 500)

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        app = self.app
        try:
            body = self._body()
            p = url.path
            if p == "/api/categories":
                return self._json(app.save_category(body))
            if p == "/api/rules":
                return self._json(app.save_rule(body))
            if p == "/api/rules/reorder":
                return self._json(app.reorder_rules(body))
            if p == "/api/rules/test":
                return self._json(app.test_rule(body))
            if p == "/api/overrides":
                return self._json(app.save_override(body))
            if p == "/api/event-override":
                return self._json(app.save_event_override(body))
            if p == "/api/settings":
                return self._json(app.save_settings(body))
            if p == "/api/import-aw":
                return self._json(app.import_aw(body))
            if p == "/api/notify/test":
                ok = app.notifier.send("TimeTracker test", "Notifications are working. Worked %s today." % _fmt(app.status()["work_today"]))
                return self._json({"ok": ok})
            if p == "/api/pause":
                app.tracker.set_paused(body.get("paused", not app.tracker.paused))
                return self._json({"paused": app.tracker.paused})
            if p == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=app.on_quit, daemon=True).start()
                return
            raise ApiError("not found", 404)
        except ApiError as e:
            return self._json({"error": str(e)}, e.status)
        except Exception as e:
            log.exception("POST %s failed", self.path)
            return self._json({"error": "server error: %s" % e}, 500)

    def do_DELETE(self):
        url = urllib.parse.urlsplit(self.path)
        app = self.app
        try:
            m = re.fullmatch(r"/api/(categories|rules|overrides)/(\d+)", url.path)
            if not m:
                raise ApiError("not found", 404)
            what, oid = m.group(1), int(m.group(2))
            if what == "categories":
                return self._json(app.delete_category(oid))
            if what == "rules":
                return self._json(app.delete_rule(oid))
            return self._json(app.delete_override(oid))
        except ApiError as e:
            return self._json({"error": str(e)}, e.status)
        except Exception as e:
            log.exception("DELETE %s failed", self.path)
            return self._json({"error": "server error: %s" % e}, 500)


def _fmt(seconds):
    m = int(seconds // 60)
    return "%dh %02dm" % divmod(m, 60)


def serve(app, port):
    handler = type("BoundHandler", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    return httpd
