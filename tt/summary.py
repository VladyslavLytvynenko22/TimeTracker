import calendar
from datetime import datetime, date, time, timedelta


def parse_day_start(s):
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return time(4, 0)


def day_bounds(d, day_start):
    ds = parse_day_start(day_start)
    start = datetime.combine(d, ds)
    end = datetime.combine(d + timedelta(days=1), ds)
    return start.timestamp(), end.timestamp()


def logical_date(ts, day_start):
    ds = parse_day_start(day_start)
    dt = datetime.fromtimestamp(ts)
    if dt.time() < ds:
        dt -= timedelta(days=1)
    return dt.date()


def range_bounds(kind, d, day_start):
    if kind == "week":
        first = d - timedelta(days=d.weekday())
        last = first + timedelta(days=6)
    elif kind == "month":
        first = d.replace(day=1)
        last = d.replace(day=calendar.monthrange(d.year, d.month)[1])
    else:
        first = last = d
    start, _ = day_bounds(first, day_start)
    _, end = day_bounds(last, day_start)
    return first, last, start, end


def _split_by_day(s, e, day_start):
    out = []
    cur = s
    while cur < e:
        d = logical_date(cur, day_start)
        _, dend = day_bounds(d, day_start)
        seg_end = min(e, dend)
        out.append((d, cur, seg_end))
        cur = seg_end
    return out


def work_between(db, cat, start, end):
    total = 0.0
    for r in db.events_overlapping(start, end):
        s = max(r["start"], start)
        e = min(r["end"], end)
        if e <= s:
            continue
        c, _ = cat.categorize(r["app"], r["title"], r["afk"], r["id"], r.get("call"))
        if c.kind == "work":
            total += e - s
    return total


def workday_count(first, last, workdays):
    n = 0
    cur = first
    while cur <= last:
        if cur.weekday() in workdays:
            n += 1
        cur += timedelta(days=1)
    return n


def compute(db, cat, kind, d, day_start, target_min, workdays=(0, 1, 2, 3, 4), now=None):
    now = now or datetime.now().timestamp()
    first, last, start, end = range_bounds(kind, d, day_start)
    workdays = set(workdays)
    day_target = target_min * 60
    wk_first, wk_last, wk_start, wk_end = range_bounds("week", d, day_start)
    week_target = day_target * workday_count(wk_first, wk_last, workdays)
    targets = {"day": day_target, "week": week_target,
               "range": day_target * workday_count(first, last, workdays) if kind != "day" else day_target}
    week_work = work_between(db, cat, wk_start, wk_end) if kind == "day" else None
    rows = db.events_overlapping(start, end)
    days = {}
    day_cats = {}
    cur = first
    while cur <= last:
        days[cur] = {"date": cur.isoformat(), "work": 0.0, "nonwork": 0.0, "afk": 0.0}
        day_cats[cur] = {}
        cur += timedelta(days=1)
    totals = {"work": 0.0, "nonwork": 0.0, "afk": 0.0}
    categories = {}
    items = {}
    timeline = []
    tracked = 0.0
    for r in rows:
        s = max(r["start"], start)
        e = min(r["end"], end)
        if e <= s:
            continue
        c, source = cat.categorize(r["app"], r["title"], r["afk"], r["id"], r.get("call"))
        dur = e - s
        tracked += dur
        totals[c.kind] += dur
        for dd, ss, ee in _split_by_day(s, e, day_start):
            if dd in days:
                days[dd][c.kind] += ee - ss
                dc = day_cats[dd]
                dc[c.id] = dc.get(c.id, 0.0) + (ee - ss)
        categories[c.id] = categories.get(c.id, 0.0) + dur
        key = (r["app"], r["title"])
        it = items.get(key)
        if it is None:
            it = {"app": r["app"], "title": r["title"], "seconds": 0.0, "count": 0,
                  "category_id": c.id, "category": c.path, "kind": c.kind, "source": source, "first": s, "last": e}
            items[key] = it
        it["seconds"] += dur
        it["count"] += 1
        it["last"] = max(it["last"], e)
        it["first"] = min(it["first"], s)
        if source == "block" and it["source"] != "block":
            it["source"] = "mixed"
        if kind == "day":
            blk = timeline[-1] if timeline else None
            if blk and blk["category_id"] == c.id and s - blk["end"] <= 2.0 and blk["app"] == r["app"]:
                blk["end"] = e
                blk["ids"].append(r["id"])
                blk["titles"][r["title"]] = blk["titles"].get(r["title"], 0.0) + dur
            else:
                timeline.append({"start": s, "end": e, "category_id": c.id, "category": c.path, "kind": c.kind,
                                 "color": c.color, "app": r["app"], "ids": [r["id"]], "titles": {r["title"]: dur}})
    for blk in timeline:
        top = sorted(blk["titles"].items(), key=lambda kv: -kv[1])[:4]
        blk["titles"] = [{"title": t, "seconds": sec} for t, sec in top]
        blk["seconds"] = blk["end"] - blk["start"]
    cat_list = []
    for cid, secs in categories.items():
        c = cat.category(cid) or cat.uncategorized
        cat_list.append({"id": c.id, "path": c.path, "kind": c.kind, "color": c.color, "seconds": secs})
    cat_list.sort(key=lambda x: -x["seconds"])
    for dd, dc in day_cats.items():
        lst = []
        for cid, secs in dc.items():
            c = cat.category(cid) or cat.uncategorized
            lst.append({"id": c.id, "path": c.path, "kind": c.kind, "seconds": secs})
        lst.sort(key=lambda x: -x["seconds"])
        days[dd]["categories"] = lst
    item_list = sorted(items.values(), key=lambda x: -x["seconds"])
    span_end = min(end, now)
    elapsed = max(0.0, span_end - start)
    day_count = (last - first).days + 1
    return {
        "range": {"kind": kind, "date": d.isoformat(), "first": first.isoformat(), "last": last.isoformat(),
                  "start": start, "end": end, "day_start": day_start, "days": day_count},
        "totals": {**totals, "active": totals["work"] + totals["nonwork"], "tracked": tracked,
                   "untracked": max(0.0, elapsed - tracked)},
        "target_minutes": target_min,
        "targets": targets,
        "workdays": sorted(workdays),
        "week": {"first": wk_first.isoformat(), "last": wk_last.isoformat(), "work": week_work},
        "days": [days[k] for k in sorted(days)],
        "categories": cat_list,
        "items": item_list[:400],
        "item_count": len(item_list),
        "timeline": timeline,
        "now": now,
    }


def segments(db, cat, kind, d, day_start):
    first, last, start, end = range_bounds(kind, d, day_start)
    out = []
    for r in db.events_overlapping(start, end):
        s = max(r["start"], start)
        e = min(r["end"], end)
        if e <= s:
            continue
        c, source = cat.categorize(r["app"], r["title"], r["afk"], r["id"], r.get("call"))
        out.append({"start": s, "end": e, "app": r["app"], "title": r["title"], "category": c.path, "kind": c.kind,
                    "source": source, "call": bool(r.get("call"))})
    return out


def work_seconds_today(db, cat, day_start, now=None):
    now = now or datetime.now().timestamp()
    d = logical_date(now, day_start)
    start, end = day_bounds(d, day_start)
    total = 0.0
    for r in db.events_overlapping(start, end):
        s = max(r["start"], start)
        e = min(r["end"], min(end, now))
        if e <= s:
            continue
        c, _ = cat.categorize(r["app"], r["title"], r["afk"], r["id"], r.get("call"))
        if c.kind == "work":
            total += e - s
    return d, total
