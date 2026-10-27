import logging
import threading
import time
import unicodedata

import re

from . import audio, mic, win
from .db import PRIVATE_TITLE
from .summary import compute, logical_date, work_seconds_today
from datetime import datetime

PRIVATE_RX = re.compile(r"\(Incognito\)|InPrivate|Private Browsing", re.IGNORECASE)
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "chromium.exe"}


class PrivateWindowDetector:
    def __init__(self):
        self.cache = {}

    def is_private(self, exe, title, hwnd):
        if PRIVATE_RX.search(title):
            return True
        if exe.lower() not in BROWSERS or not hwnd:
            return False
        key = (hwnd, exe)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        try:
            name = win.accessible_name(hwnd)
        except Exception:
            name = ""
        res = bool(PRIVATE_RX.search(name))
        if len(self.cache) > 500:
            self.cache.clear()
        self.cache[key] = res
        return res

log = logging.getLogger("tt.tracker")

LOCK_APP = "LockApp.exe"
LOCK_TITLE = "Windows Default Lock Screen"
AFK_APP = "AFK"
AFK_IDLE_TITLE = "No mouse or keyboard input"
AFK_SLEEP_TITLE = "Computer asleep or tracker stopped"
GAP_SECONDS = 120


def clean_title(title):
    i = 0
    n = len(title)
    while i < n and (title[i].isspace() or unicodedata.category(title[i]).startswith("S")):
        i += 1
    return title[i:].strip()


def fmt_minutes(seconds):
    m = int(round(seconds / 60))
    h, m = divmod(m, 60)
    if h and m:
        return "%dh %02dm" % (h, m)
    if h:
        return "%dh" % h
    return "%dm" % m


class Tracker(threading.Thread):
    def __init__(self, db, cat, notifier, tray=None):
        super().__init__(name="tracker", daemon=True)
        self.db = db
        self.cat = cat
        self.notifier = notifier
        self.tray = tray
        self.stop_evt = threading.Event()
        self.paused = False
        self.cur = None
        self.idle_marked = False
        self.last_tick = None
        self.last_notif_check = 0.0
        self.settings = db.get_settings()
        self.notif_state = db.get_kv("notif_state", {"day": None, "fired": []})
        self.status = {"app": "", "title": "", "afk": False, "idle": 0.0, "paused": False, "since": time.time()}
        self.lock = threading.Lock()
        self.private = PrivateWindowDetector()
        self.last_media_seen = 0.0

    def reload_settings(self):
        self.settings = self.db.get_settings()

    def set_paused(self, paused):
        self.paused = bool(paused)
        self.status["paused"] = self.paused
        if self.paused:
            self._close_current(time.time())

    def stop(self):
        self.stop_evt.set()

    def run(self):
        log.info("tracker started")
        try:
            win.com_init()
        except Exception:
            log.exception("CoInitialize failed")
        self.last_tick = time.time()
        while not self.stop_evt.is_set():
            now = time.time()
            try:
                self._tick(now)
            except Exception:
                log.exception("tick failed")
            self.last_tick = now
            interval = max(0.5, float(self.settings.get("poll_interval_sec", 1)))
            self.stop_evt.wait(interval)
        self._close_current(time.time())
        log.info("tracker stopped")

    def _tick(self, now):
        if self.paused:
            return
        if self.last_tick is not None and now - self.last_tick > GAP_SECONDS:
            gap_start = self.last_tick
            log.info("gap of %.0fs detected, marking as AFK", now - gap_start)
            self._close_current(gap_start)
            self.db.insert_event(gap_start, now, AFK_APP, AFK_SLEEP_TITLE, 1)
            self.idle_marked = False

        idle = win.idle_seconds()
        afk_timeout = float(self.settings.get("afk_timeout_min", 30)) * 60
        locked = win.is_locked()
        exe, title, hwnd = ("", "", 0) if locked else win.foreground()

        media = False
        call_apps = []
        if not locked:
            try:
                call_apps = mic.mic_apps()
            except Exception:
                log.exception("mic check failed")
            if call_apps:
                self.last_media_seen = now
        if not locked and idle >= 60 and self.settings.get("media_keeps_active", True):
            try:
                media = audio.display_required() or (exe or "").lower() in audio.playing_exes()
            except Exception:
                log.exception("media check failed")
            if media:
                self.last_media_seen = now
        if self.last_media_seen:
            idle = min(idle, now - self.last_media_seen)

        if locked or exe == LOCK_APP or title == LOCK_TITLE:
            sample = (LOCK_APP, LOCK_TITLE, True, False)
            self.idle_marked = False
        elif idle >= afk_timeout:
            sample = (AFK_APP, AFK_IDLE_TITLE, True, False)
            if not self.idle_marked:
                last_input = now - idle
                log.info("idle %.0fs, rewriting since %.0f as AFK", idle, last_input)
                self._close_current(last_input)
                self.db.trim_after(last_input)
                self.cur = None
                self._open(last_input, *sample)
                self.idle_marked = True
        else:
            self.idle_marked = False
            title = clean_title(title or "")
            mode = self.settings.get("private_windows", "hide")
            if mode != "track" and self.private.is_private(exe or "", title, hwnd):
                if mode == "skip":
                    self._close_current(now)
                    with self.lock:
                        self.status.update({"app": exe or "unknown", "title": PRIVATE_TITLE, "afk": False, "idle": idle, "skipped": True})
                    return
                title = PRIVATE_TITLE
            sample = (exe or "unknown", title, False, bool(call_apps))

        with self.lock:
            self.status["skipped"] = False
            self.status["media"] = media
            self.status["call"] = bool(call_apps)
            self.status["call_apps"] = call_apps
            self.status.update({"app": sample[0], "title": sample[1], "afk": sample[2], "idle": idle})
        cur = self.cur
        if cur and (cur["app"], cur["title"], cur["afk"], cur["call"]) == sample:
            cur["end"] = now
            if now - cur["flushed"] >= 10:
                self.db.update_event_end(cur["id"], now)
                cur["flushed"] = now
        else:
            self._close_current(now)
            self._open(now, *sample)

        if now - self.last_notif_check >= 60:
            self.last_notif_check = now
            try:
                self._check_notifications(now)
            except Exception:
                log.exception("notification check failed")

    def _open(self, start, app, title, afk, call=False):
        eid = self.db.insert_event(start, start, app, title, afk, call)
        self.cur = {"id": eid, "start": start, "end": start, "app": app, "title": title, "afk": afk, "call": call, "flushed": start}
        self.status["since"] = start

    def _close_current(self, end):
        cur = self.cur
        if not cur:
            return
        if end <= cur["start"] + 0.001:
            self.db.delete_event(cur["id"])
        else:
            self.db.update_event_end(cur["id"], end)
        self.cur = None

    def current_event(self):
        cur = self.cur
        if not cur:
            return None
        return dict(cur)

    def _fire(self, key, title, body):
        self.notif_state["fired"].append(key)
        self.db.set_setting("notif_state", self.notif_state)
        self.notifier.send(title, body)

    def _weekly_summary(self, now):
        s = self.settings
        ws = s.get("weekly_summary") or {}
        if not ws.get("enabled", True):
            return
        dt = datetime.fromtimestamp(now)
        if dt.weekday() != int(ws.get("weekday", 4)) or dt.strftime("%H:%M") < str(ws.get("time", "18:00")):
            return
        iso = dt.isocalendar()
        key = "%d-W%02d" % (iso[0], iso[1])
        if self.db.get_kv("weekly_summary_sent") == key:
            return
        d = logical_date(now, s.get("day_start", "04:00"))
        res = compute(self.db, self.cat, "week", d, s.get("day_start", "04:00"), s.get("work_target_min", 480),
                      s.get("workdays", [0, 1, 2, 3, 4]), now)
        work = res["totals"]["work"]
        target = res["targets"]["range"]
        if work >= target:
            line = "%s worked, %s over the %s target." % (fmt_minutes(work), fmt_minutes(work - target), fmt_minutes(target))
        else:
            line = "%s worked, %s short of the %s target." % (fmt_minutes(work), fmt_minutes(target - work), fmt_minutes(target))
        self.db.set_setting("weekly_summary_sent", key)
        top = [c for c in res["categories"] if c["kind"] == "work"][:3]
        top_line = ""
        if top:
            top_line = " Top: " + ", ".join("%s %s" % (c["path"].split(" > ")[-1], fmt_minutes(c["seconds"])) for c in top) + "."
        self.notifier.send("Your week in numbers",
                           "%s Not work: %s.%s" % (line, fmt_minutes(res["totals"]["nonwork"]), top_line))

    def _check_notifications(self, now):
        s = self.settings
        n = s.get("notifications", {})
        day, work = work_seconds_today(self.db, self.cat, s.get("day_start", "04:00"), now)
        if self.tray:
            self.tray.set_tip("TimeTracker - worked %s today" % fmt_minutes(work))
        if not n.get("enabled", True):
            return
        try:
            self._weekly_summary(now)
        except Exception:
            log.exception("weekly summary failed")
        day_key = day.isoformat()
        if self.notif_state.get("day") != day_key:
            self.notif_state = {"day": day_key, "fired": []}
            self.db.set_setting("notif_state", self.notif_state)
        fired = set(self.notif_state["fired"])
        target = float(s.get("work_target_min", 480)) * 60
        remaining = target - work
        for m in sorted(n.get("before_end_min", []) or [], reverse=True):
            try:
                m = int(m)
            except (TypeError, ValueError):
                continue
            key = "before:%d" % m
            if 0 < remaining <= m * 60 and key not in fired:
                self._fire(key, "%s of work time left" % fmt_minutes(remaining),
                           "Worked %s of %s today." % (fmt_minutes(work), fmt_minutes(target)))
                fired.add(key)
                break
        if work >= target:
            if n.get("at_end", True) and "end" not in fired:
                self._fire("end", "Work time is over",
                           "You reached %s today. Time to wrap up." % fmt_minutes(target))
                fired.add("end")
            every = int(n.get("overtime_every_min", 15) or 0)
            if n.get("overtime", True) and every > 0:
                k = int((work - target) // (every * 60))
                if k >= 1:
                    key = "overtime:%d" % k
                    if key not in fired:
                        self._fire(key, "Overtime: +%s" % fmt_minutes(work - target),
                                   "Worked %s today, target is %s." % (fmt_minutes(work), fmt_minutes(target)))
                        for i in range(1, k + 1):
                            fired.add("overtime:%d" % i)
                        self.notif_state["fired"] = sorted(fired)
                        self.db.set_setting("notif_state", self.notif_state)
