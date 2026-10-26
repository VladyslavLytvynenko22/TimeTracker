import logging
import logging.handlers
import os
import sys
import threading
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("TT_DATA_DIR") or os.path.join(BASE, "data")
sys.path.insert(0, BASE)

from tt.db import Database
from tt.categorize import Categorizer
from tt.tracker import Tracker
from tt.notify import Notifier, register_aumid
from tt.tray import Tray
from tt.server import App, serve
from tt import win


def setup_logging():
    os.makedirs(DATA_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(os.path.join(DATA_DIR, "tracker.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    if sys.stdout is not None and sys.stdout.isatty():
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)


def main():
    setup_logging()
    log = logging.getLogger("tt")
    db = Database(os.path.join(DATA_DIR, "tracker.db"))
    settings = db.get_settings()
    port = int(os.environ.get("TT_PORT") or settings.get("port", 48411))
    url = "http://127.0.0.1:%d/" % port
    icon_path = os.path.join(DATA_DIR, "tracker.ico")
    if not os.path.exists(icon_path):
        win.write_icon(icon_path)
    register_aumid(icon_path)

    cat = Categorizer(db)
    stop_evt = threading.Event()
    state = {"tracker": None, "httpd": None, "tray": None}

    def open_dashboard():
        webbrowser.open(url)

    def toggle_pause():
        t = state["tracker"]
        t.set_paused(not t.paused)

    def quit_app():
        if stop_evt.is_set():
            return
        stop_evt.set()

    tray = Tray(icon_path, open_dashboard, toggle_pause, quit_app, lambda: state["tracker"].paused if state["tracker"] else False)
    tray.start()
    tray.ready.wait(5)
    notifier = Notifier(url, tray if tray.hwnd else None)
    tracker = Tracker(db, cat, notifier, tray if tray.hwnd else None)
    state["tracker"] = tracker
    app = App(db, cat, tracker, notifier, DATA_DIR, quit_app)
    try:
        httpd = serve(app, port)
    except OSError as e:
        log.error("port %d is busy (%s); another TimeTracker is probably running", port, e)
        tray.stop()
        webbrowser.open(url)
        return 1
    state["httpd"] = httpd
    tracker.start()
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    log.info("TimeTracker running at %s", url)
    if "--open" in sys.argv:
        open_dashboard()
    try:
        while not stop_evt.wait(1.0):
            if not tracker.is_alive():
                log.error("tracker thread died, exiting")
                break
    except KeyboardInterrupt:
        pass
    log.info("shutting down")
    tracker.stop()
    tracker.join(10)
    httpd.shutdown()
    tray.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
