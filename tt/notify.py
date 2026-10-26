import base64
import logging
import os
import subprocess
import winreg
from xml.sax.saxutils import escape

log = logging.getLogger("tt.notify")

AUMID = "TimeTracker.Local"
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def register_aumid(icon_path):
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\AppUserModelId\%s" % AUMID)
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "TimeTracker")
        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, icon_path)
        winreg.CloseKey(key)
    except OSError as e:
        log.warning("AUMID registration failed: %s", e)


class Notifier:
    def __init__(self, url, tray=None):
        self.url = url
        self.tray = tray

    def send(self, title, body):
        log.info("notify: %s - %s", title, body)
        if self._toast(title, body):
            return True
        if self.tray:
            try:
                self.tray.balloon(title, body)
                return True
            except Exception as e:
                log.warning("balloon failed: %s", e)
        return False

    def _toast(self, title, body):
        xml = ('<toast activationType="protocol" launch="%s" duration="short">'
               '<visual><binding template="ToastGeneric"><text>%s</text><text>%s</text></binding></visual>'
               '<audio src="ms-winsoundevent:Notification.Default"/></toast>') % (escape(self.url), escape(title), escape(body))
        script = (
            "$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]\n"
            "$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]\n"
            "$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
            "$x.LoadXml('%s')\n"
            "$t = [Windows.UI.Notifications.ToastNotification]::new($x)\n"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('%s').Show($t)\n"
        ) % (xml.replace("'", "''"), AUMID)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            r = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                                "-EncodedCommand", encoded],
                               capture_output=True, timeout=20, startupinfo=si,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode != 0:
                log.warning("toast failed rc=%s: %s", r.returncode, r.stderr.decode("utf-8", "ignore")[:400])
                return False
            return True
        except Exception as e:
            log.warning("toast error: %s", e)
            return False
