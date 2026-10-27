# TimeTracker

A personal work-time tracker for Windows 11. It watches which window is in front, splits the day
into **Work**, **Not work** and **Away**, and shows it on a dark dashboard at
<http://127.0.0.1:48411/>. No dependencies beyond Python 3 (uses only the standard library and Win32).

## Start it

1. Open PowerShell in this folder and run:

   ```powershell
   .\install.ps1
   ```

   This creates a shortcut in your Startup folder (so it starts at every Windows login),
   starts the tracker now, and opens the dashboard.

2. Look for the blue clock icon in the tray (it may be in the hidden overflow area behind the `^` arrow;
   drag it onto the taskbar if you want it visible). Left-click opens the dashboard,
   right-click gives Pause / Quit.

Manual start without the shortcut: double-click `start.cmd`, or run
`pythonw.exe tracker.py` in this folder.

To stop it and remove the autostart: `.\uninstall.ps1` (your data stays in `data\`).

## How time is classified

- **Away**: the Windows lock screen (`LockApp.exe` / "Windows Default Lock Screen"), the computer being
  asleep, or no mouse/keyboard input for 10 minutes (configurable). When the timeout passes, the whole
  idle period is re-labelled as away, so thinking at your desk for a few minutes still counts as work.
- **Watching a video** in the front window (sound coming from that app) keeps you "at the computer", so a
  film in Chrome stays in its own category instead of becoming away. Muted videos are not detected.
- **Calls**: while any app uses the microphone (Meet in Chrome, Teams, Slack, Zoom) you are never away, and
  the time is counted as *Work > Chat & Calls* regardless of what is on screen (Settings → calls).
- **Incognito / InPrivate windows** are detected through the window's accessibility name; by default the
  time is recorded with the title hidden ("Private window") under the *Private browsing* category.
- Everything else goes through the rules on the *Rules* page, top to bottom. The first regular expression
  that matches the window title or the app name wins. Each category counts as work, not work or away.
  Windows that match no rule go to **Uncategorized** (amber, counts as not work). Use the *Needs a rule*
  filter on the Review page to find the biggest uncategorized windows and give them a rule.
- On the *Review* page you can change the category of any window by hand (this beats the rules), click a
  title to change single segments, or press **Rule** to turn a window into a new rule. Rules created there
  go to the top of the list.
- On the day timeline, click a block to re-label just that block.

The default rules were built from your ActivityWatch export, plus categories for entertainment (anime,
series, streaming), shopping, social and games. You can import another ActivityWatch category export with
**Import ActivityWatch JSON** on the Rules page.

## Notifications

Settings page:

- warn N minutes before the daily work target (several values allowed, e.g. `30, 15, 5`)
- tell you when the target is reached
- remind you about overtime every N minutes of extra work (only fires while work time keeps growing)

- weekly summary toast (Friday 18:00 by default): hours worked against the week target, not-work time and
  the top three work categories

Toasts show as "TimeTracker" and clicking one opens the dashboard.

## Targets, day boundary, export

Days start at 04:00 by default (Settings → Day starts at), so a late night belongs to the day it started.
Week = Monday to Sunday, month = calendar month, both built from those logical days. The week and month
targets are the daily target times the work days you tick in Settings (Mon–Fri = 40h a week).

A category can have its own daily target (Rules → Categories → Edit). The Overview category list then
shows progress against it, multiplied by the work days for week and month views.

Away time between the day start and the first activity of a day counts as sleep and is left out of the
Away total and the timeline. Parent categories that only group others (such as "Work") are hidden from
the pickers.

The Week and Month charts can be switched to "By category" (top 7 categories stacked, the rest as Other).
"Export CSV" in the range bar downloads the current range as windows, per-day totals, or every segment.

## Where things live

| What | Where |
|---|---|
| Database (SQLite) | `data\tracker.db` |
| Log | `data\tracker.log` |
| Dashboard | <http://127.0.0.1:48411/> (change the port in Settings, restart to apply) |
| Startup shortcut | `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TimeTracker.lnk` |

Keyboard: ← / → move the day, week or month on the Overview and Review pages.

Environment overrides for testing: `TT_DATA_DIR` (data folder) and `TT_PORT`.

## Importing ActivityWatch history

`python tools\import_aw_buckets.py path\to\aw-buckets-export.json` imports the window and AFK buckets
(use `--dry-run` to see counts first, `--undo` to remove the import again). Only time before TimeTracker's
own first record is imported, a backup of the database is written next to it, and the imported rows follow
the current rules like everything else.
