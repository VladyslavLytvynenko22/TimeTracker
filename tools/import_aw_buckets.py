"""Import an ActivityWatch bucket export (aw-buckets-export.json) into TimeTracker.

Usage:  python tools/import_aw_buckets.py <export.json> [--data-dir DIR] [--dry-run]

Window events are clipped to the not-afk periods of the AFK bucket; AFK periods become
"AFK" events, lock-screen windows stay as LockApp.exe (away). Only time before the first
event TimeTracker recorded itself is imported, so nothing overlaps live data.
The database is backed up first; the imported id range is stored in settings key
"import_aw" so the import can be removed again with --undo.
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from tt.db import Database
from tt.tracker import AFK_APP, AFK_IDLE_TITLE, LOCK_APP, clean_title

CHUNK = 20000


def parse_ts(s):
    return datetime.fromisoformat(s).timestamp()


def merge_intervals(ivs):
    ivs.sort()
    out = []
    for s, e in ivs:
        if out and s <= out[-1][1] + 0.5:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def subtract(s, e, blocks, idx):
    """Yield parts of [s,e) not covered by sorted blocks; idx is a moving start index."""
    i = idx
    while i < len(blocks) and blocks[i][1] <= s:
        i += 1
    start_idx = i
    cur = s
    while i < len(blocks) and blocks[i][0] < e:
        bs, be = blocks[i]
        if bs > cur:
            yield cur, min(bs, e)
        cur = max(cur, be)
        i += 1
    if cur < e:
        yield cur, e
    return start_idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--data-dir", default=os.path.join(BASE, "data"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--undo", action="store_true")
    args = ap.parse_args()
    db = Database(os.path.join(args.data_dir, "tracker.db"))
    db.conn.execute("PRAGMA busy_timeout=30000")

    if args.undo:
        info = db.get_kv("import_aw")
        if not info:
            print("nothing to undo")
            return
        n = db.execute("DELETE FROM events WHERE id BETWEEN ? AND ?", (info["min_id"], info["max_id"])).rowcount
        db.execute("DELETE FROM settings WHERE key='import_aw'")
        print("removed", n, "imported events")
        return

    if not args.path:
        ap.error("path to aw-buckets-export.json required")
    if db.get_kv("import_aw"):
        print("an import already exists; run with --undo first")
        return

    row = db.execute("SELECT MIN(start) FROM events").fetchone()
    cutoff = row[0] or time.time()
    print("importing everything before", datetime.fromtimestamp(cutoff))

    t0 = time.time()
    with open(args.path, encoding="utf-8") as f:
        data = json.load(f)
    buckets = data.get("buckets", data)
    window = []
    afk = []
    for b in buckets.values():
        if b.get("type") == "currentwindow":
            for e in b["events"]:
                s = parse_ts(e["timestamp"])
                d = float(e.get("duration") or 0)
                if d > 0:
                    window.append((s, s + d, e["data"].get("app") or "unknown", e["data"].get("title") or ""))
        elif b.get("type") == "afkstatus":
            for e in b["events"]:
                if e["data"].get("status") == "afk":
                    s = parse_ts(e["timestamp"])
                    d = float(e.get("duration") or 0)
                    if d > 0:
                        afk.append([s, s + d])
    print("loaded %d window events, %d afk periods in %.1fs" % (len(window), len(afk), time.time() - t0))
    window.sort()
    afk = merge_intervals(afk)

    lock_blocks = merge_intervals([[s, e] for s, e, app, _ in window if app == LOCK_APP])
    out = []

    def emit(s, e, app, title, is_afk):
        if e - s < 0.5:
            return
        if out:
            ls, le, lapp, ltitle, lafk = out[-1]
            if lapp == app and ltitle == title and lafk == is_afk and s <= le + 1.0:
                out[-1] = (ls, max(le, e), app, title, is_afk)
                return
        out.append((s, e, app, title, is_afk))

    ai = 0
    for s, e, app, title in window:
        e = min(e, cutoff)
        if e <= s:
            continue
        if app == LOCK_APP:
            emit(s, e, LOCK_APP, "Windows Default Lock Screen", 1)
            continue
        while ai < len(afk) and afk[ai][1] <= s:
            ai += 1
        for ps, pe in subtract(s, e, afk, ai):
            emit(ps, pe, app, clean_title(title), 0)

    li = 0
    for s, e in afk:
        e = min(e, cutoff)
        if e <= s:
            continue
        while li < len(lock_blocks) and lock_blocks[li][1] <= s:
            li += 1
        for ps, pe in subtract(s, e, lock_blocks, li):
            out.append((ps, pe, AFK_APP, AFK_IDLE_TITLE, 1))

    out.sort()
    total_active = sum(e - s for s, e, _, _, a in out if not a)
    total_afk = sum(e - s for s, e, _, _, a in out if a)
    print("prepared %d events: %.1f h at the computer, %.1f h away" % (len(out), total_active / 3600, total_afk / 3600))
    if args.dry_run:
        return

    backup = os.path.join(args.data_dir, "tracker-before-aw-import.db")
    with sqlite3.connect(backup) as dst:
        db.conn.backup(dst)
    print("backup written to", backup)

    min_id = None
    max_id = None
    for i in range(0, len(out), CHUNK):
        chunk = out[i:i + CHUNK]
        with db.lock:
            db.conn.execute("BEGIN")
            db.conn.executemany("INSERT INTO events(start, end, app, title, afk, call) VALUES(?,?,?,?,?,0)", chunk)
            last = db.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.conn.execute("COMMIT")
        if min_id is None:
            min_id = last - len(chunk) + 1
        max_id = last
        print("  inserted %d / %d" % (min(i + CHUNK, len(out)), len(out)), end="\r")
    print()
    db.set_setting("import_aw", {"min_id": min_id, "max_id": max_id, "count": len(out), "cutoff": cutoff,
                                 "source": os.path.basename(args.path), "at": time.time()})
    print("done in %.1fs, ids %d..%d" % (time.time() - t0, min_id, max_id))


if __name__ == "__main__":
    main()
