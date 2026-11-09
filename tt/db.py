import json
import os
import sqlite3
import threading

DEFAULT_SETTINGS = {
    "day_start": "04:00",
    "afk_timeout_min": 30,
    "work_target_min": 480,
    "workdays": [0, 1, 2, 3, 4],
    "private_windows": "hide",
    "media_keeps_active": True,
    "calls_category": "Work > Chat & Calls",
    "weekly_summary": {"enabled": True, "weekday": 4, "time": "18:00"},
    "poll_interval_sec": 1,
    "port": 48411,
    "notifications": {
        "enabled": True,
        "before_end_min": [15],
        "at_end": True,
        "overtime": True,
        "overtime_every_min": 15,
    },
}

KIND_COLORS = {"work": "#3987e5", "nonwork": "#d95926", "afk": "#6b6b72"}

DEFAULT_CATEGORIES = [
    ("AFK", "afk", "#6b6b72", [r"LockApp|Windows Default Lock Screen"]),
    ("Entertainment", "nonwork", "#d95926", [
        r"аніме|anime|anitube|Серіал|серіал|serial|hdrezka|rezka|uakino|kinogo|netflix|youtube|twitch|фільм|\bfilm|movie|Xiaomi Camera Viewer|Modern Warfare 2|\bсерія\b|дивитися онлайн|сезон \d",
    ]),
    ("Games", "nonwork", "#d95926", [r"Grounded|Maine-Win64-Shipping|Steam|Epic Games"]),
    ("Shopping", "nonwork", "#d95926", [r"ROZETKA|rozetka|Prom\.ua|prom\.ua|\bOLX\b|AliExpress|Amazon|Епіцентр|EPICENTRK|Сільпо|Dreame|Dracar|Оформлення замовлення|Замовлення|Списки »|HOME FOOD|MTA - мережа|Google Maps|Google Карты|Google Карти|dnipro-?m|PlayStation|playstation\.com|^Sony\b|sony\.(?:com|ua)"]),
    ("Social & Messengers", "nonwork", "#d95926", [
        r"Facebook|Instagram|TikTok|Reddit|Twitter|Messenger|Telegram|Signal|WhatsApp|Discord|Viber",
    ]),
    ("Web search", "nonwork", "#d95926", [r"Google Search|Пошук Google|Поиск в Google"]),
    ("Work > System", "work", None, [
        r"PickerHost|CredentialUIBroker|Windows Security|SystemSettings|consent\.exe|ShellExperienceHost|ShellHost|StartMenuExperienceHost|"
        r"SearchHost|SearchApp|TextInputHost|ScreenClippingHost|^unknown$|^Taskbar$|^Desktop$|^Task switcher$|^Task view$|^Tray overflow$|^System overlay$|^Window switch$|"
        r"^chrome://|^edge://|Chrome Web Store|chromewebstore\.google\.com|^(?:Bookmarks|Extensions|Settings|History|Downloads|New Incognito tab) - (?:Google Chrome|Microsoft.*Edge)$|^Save As$|^Open$|^\(Chrome_WidgetWin_\d\)$",
    ]),
    ("Work > Development > Visual Studio Code", "work", None, [r"Code\.exe|Visual Studio Code"]),
    ("Work > Development > Visual Studio", "work", None, [r"devenv|Microsoft Visual Studio"]),
    ("Work > Development > SQL", "work", None, [r"SSMS|Ssms\.exe|SQL Server Management Studio|pgAdmin|Azure Data Studio|DBeaver|\.sql\b"]),
    ("Work > Development > Testing & Debugging", "work", None, [
        r"React App|localhost|127\.0\.0\.1(?!:48411)|DevTools|Playwright|Postman|Swagger|webhook\.site|"
        r"api\.nowcerts\.com|newtestapi\.nowcerts\.com|nc-public-api|nc-fusion-api|api\.momentumamp\.com|null-ref-express",
    ]),
    ("Work > Development > TeamCity", "work", None, [r"TeamCity|tcbld\.nowcerts\.com"]),
    ("Work > Development > Git & Code Review", "work", None, [
        r"\bgit\b|github\.com|bitbucket\.org|Bitbucket|GitHub|Gitlab|Sourcetree|TortoiseGit|GitExtensions|InsuranceGIG/|VladyslavLytvynenko",
    ]),
    ("Work > Development > AI & Terminal", "work", None, [r"Claude|claude\.ai|ChatGPT|WindowsTerminal|Windows Terminal|powershell|cmd\.exe"]),
    ("Work > Development", "work", None, [r"Stack Overflow|\bvim\b|Spyder|Ghidra|Nexus"]),
    ("Work > Chat & Calls", "work", None, [
        r"Google Chat|Gmail|Meet -|Mail -|mail\.google\.com|Outlook|ms-teams|meet\.google\.com|Microsoft Teams|Slack|Zoom|RingCentral|\bChat\b",
    ]),
    ("Work > Monitoring & Logs", "work", None, [
        r"Elastic|Grafana|Kibana|Prometheus|Hyperping|hyperping|HetrixTools|StatusCake|OpenSearch|Log Stream|esl2?\.nowcerts\.com|esc\.nowcerts\.com",
    ]),
    ("Work > Planning & Admin", "work", None, [
        r"Jira|atlassian\.net/browse|Clockify|clockify\.me|Lano|lano\.io|insightful\.io|wisestamp\.com|Google Calendar|Google Tasks|Google Password|1Password|1password\.com|ActivityWatch|TimeTracker|Vanta|BitLocker",
    ]),
    ("Work > Infrastructure", "work", None, [
        r"Microsoft Azure|portal\.azure\.com|Kudu|Key Vault|Internet Information Services \(IIS\) Manager|Remote Desktop Connection|mstsc|S3 File|"
        r"sched\.nowcerts\.com|scheduler\.nowcerts\.com|nc-kafka-management|id\.ionos\.com|onetimesecret\.com",
    ]),
    ("Work > Documentation", "work", None, [
        r"notepad|Notepad|Confluence|atlassian\.net/wiki|Google Docs|docs\.google\.com|WINWORD|\.docx|Ant Design|\bAPI\b|Webhook|ElevenLabs|Accord|ACORD",
    ]),
    ("Work > Office & Files", "work", None, [
        r"libreoffice|ReText|explorer|Taskmgr|Task Manager|Adobe Acrobat|Acrobat\.exe|ShareX|Excel|EXCEL\.EXE|Google Sheets|Google Перекладач",
    ]),
    ("Work > Momentum Products", "work", None, [
        r"NowCerts|nowcerts|Momentum|momentum|momentumamp|Insurance Agency Management System|PORTAL|Insurance Agency AI|InsuranceGIG|\bMAC\b|Toolbox|All workflows|Twilio|Lightspeed|Spoke Phone|Communicator Web|EIS - |\bSMS\b",
    ]),
    ("Web search", "nonwork", "#d95926", [r"^New Tab - Google Chrome$|^Untitled - Google Chrome$"]),
    ("Work", "work", "#3987e5", []),
    ("Uncategorized", "nonwork", "#d45bb5", []),
]

PRIVATE_TITLE = "Private window (Incognito / InPrivate)"
EXTRA_CATEGORIES = [
    ("Private browsing", "nonwork", "#d95926", [r"^Private window \(Incognito / InPrivate\)$"]),
]

PROTECTED_CATEGORIES = ("Uncategorized", "AFK")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY,
    start REAL NOT NULL,
    end REAL NOT NULL,
    app TEXT NOT NULL,
    title TEXT NOT NULL,
    afk INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_events_start ON events(start);
CREATE INDEX IF NOT EXISTS ix_events_end ON events(end);
CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'work',
    color TEXT
);
CREATE TABLE IF NOT EXISTS rules(
    id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    pattern TEXT NOT NULL,
    ignore_case INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS overrides(
    id INTEGER PRIMARY KEY,
    app TEXT NOT NULL,
    title TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    UNIQUE(app, title)
);
CREATE TABLE IF NOT EXISTS event_overrides(
    event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self._seed()

    def _migrate(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(events)").fetchall()}
        if "call" not in cols:
            self.conn.execute("ALTER TABLE events ADD COLUMN call INTEGER NOT NULL DEFAULT 0")
        if "url" not in cols:
            self.conn.execute("ALTER TABLE events ADD COLUMN url TEXT NOT NULL DEFAULT ''")
        ccols = {r[1] for r in self.conn.execute("PRAGMA table_info(categories)").fetchall()}
        if "target_min" not in ccols:
            self.conn.execute("ALTER TABLE categories ADD COLUMN target_min INTEGER NOT NULL DEFAULT 0")

    def _seed(self):
        with self.lock:
            if self.conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
                prio = 0
                for path, kind, color, patterns in DEFAULT_CATEGORIES:
                    row = self.conn.execute("SELECT id FROM categories WHERE path=?", (path,)).fetchone()
                    if row:
                        cid = row[0]
                    else:
                        cid = self.conn.execute(
                            "INSERT INTO categories(path, kind, color) VALUES(?,?,?)", (path, kind, color)).lastrowid
                    for p in patterns:
                        self.conn.execute(
                            "INSERT INTO rules(category_id, pattern, ignore_case, priority, enabled) VALUES(?,?,1,?,1)",
                            (cid, p, prio))
                        prio += 1
            for path, kind, color, patterns in EXTRA_CATEGORIES:
                if self.conn.execute("SELECT 1 FROM categories WHERE path=?", (path,)).fetchone():
                    continue
                cur = self.conn.execute("INSERT INTO categories(path, kind, color) VALUES(?,?,?)", (path, kind, color))
                for p in patterns:
                    self.conn.execute("UPDATE rules SET priority = priority + 1")
                    self.conn.execute(
                        "INSERT INTO rules(category_id, pattern, ignore_case, priority, enabled) VALUES(?,?,1,0,1)",
                        (cur.lastrowid, p))

    def execute(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params)

    def query(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def get_settings(self):
        rows = self.query("SELECT key, value FROM settings")
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        for r in rows:
            try:
                v = json.loads(r["value"])
            except ValueError:
                continue
            if r["key"] in ("notifications", "weekly_summary") and isinstance(v, dict):
                s[r["key"]].update(v)
            else:
                s[r["key"]] = v
        return s

    def set_setting(self, key, value):
        self.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value)))

    def get_kv(self, key, default=None):
        rows = self.query("SELECT value FROM settings WHERE key=?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except ValueError:
            return default

    def categories(self):
        return self.query("SELECT id, path, kind, color, target_min FROM categories ORDER BY path")

    def rules(self):
        return self.query(
            "SELECT r.id, r.category_id, r.pattern, r.ignore_case, r.priority, r.enabled, c.path, c.kind "
            "FROM rules r JOIN categories c ON c.id=r.category_id ORDER BY r.priority, r.id")

    def overrides(self):
        return self.query(
            "SELECT o.id, o.app, o.title, o.category_id, c.path, c.kind FROM overrides o JOIN categories c ON c.id=o.category_id")

    def event_overrides(self):
        return self.query("SELECT event_id, category_id FROM event_overrides")

    def events_overlapping(self, start, end):
        return self.query(
            "SELECT id, start, end, app, title, afk, call, url FROM events WHERE end > ? AND start < ? ORDER BY start",
            (start, end))

    def recent_events(self, limit):
        return self.query(
            "SELECT id, start, end, app, title, afk, call, url FROM events ORDER BY start DESC LIMIT ?", (limit,))

    def insert_event(self, start, end, app, title, afk, call=False, url=""):
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO events(start, end, app, title, afk, call, url) VALUES(?,?,?,?,?,?,?)",
                (start, end, app, title, 1 if afk else 0, 1 if call else 0, url or ""))
            return cur.lastrowid

    def update_event_end(self, event_id, end):
        self.execute("UPDATE events SET end=? WHERE id=?", (end, event_id))

    def update_event_url(self, event_id, url):
        self.execute("UPDATE events SET url=? WHERE id=?", (url, event_id))

    def delete_event(self, event_id):
        self.execute("DELETE FROM events WHERE id=?", (event_id,))

    def trim_after(self, t):
        with self.lock:
            self.conn.execute("DELETE FROM events WHERE start >= ?", (t,))
            self.conn.execute("UPDATE events SET end=? WHERE end > ? AND start < ?", (t, t, t))

    def next_rule_priority(self):
        row = self.execute("SELECT COALESCE(MAX(priority), -1) + 1 FROM rules").fetchone()
        return row[0]

    def shift_rules_down(self):
        self.execute("UPDATE rules SET priority = priority + 1")
