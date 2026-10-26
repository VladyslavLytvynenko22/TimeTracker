import os
import winreg

BASE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def _friendly(name):
    if "#" in name:
        return os.path.basename(name.replace("#", "\\"))
    return name.split("_")[0]


def _scan(path):
    out = []
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        return out
    with key:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
            except OSError:
                break
            i += 1
            if name == "NonPackaged":
                continue
            try:
                with winreg.OpenKey(key, name) as sub:
                    start, _ = winreg.QueryValueEx(sub, "LastUsedTimeStart")
                    stop, _ = winreg.QueryValueEx(sub, "LastUsedTimeStop")
            except OSError:
                continue
            if start and not stop:
                out.append(_friendly(name))
    return out


def mic_apps():
    return _scan(BASE) + _scan(BASE + r"\NonPackaged")


if __name__ == "__main__":
    print(mic_apps())
