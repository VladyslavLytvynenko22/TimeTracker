import ctypes
import ctypes.wintypes as w
import math
import os
import struct

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]


user32.GetForegroundWindow.restype = w.HWND
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user32.GetWindowThreadProcessId.restype = w.DWORD
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
user32.OpenInputDesktop.restype = w.HANDLE
user32.CloseDesktop.argtypes = [w.HANDLE]
user32.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
kernel32.OpenProcess.restype = w.HANDLE
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.GetTickCount.restype = w.DWORD

WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
user32.EnumChildWindows.argtypes = [w.HWND, WNDENUMPROC, w.LPARAM]


def idle_seconds():
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    now = kernel32.GetTickCount()
    return ((now - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def process_name(pid):
    if not pid:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = w.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_pid(hwnd):
    pid = w.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def uwp_child_pid(hwnd, frame_pid):
    found = []

    def cb(child, _):
        p = window_pid(child)
        if p and p != frame_pid:
            found.append(p)
            return False
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return found[0] if found else None


def foreground():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", "", 0
    pid = window_pid(hwnd)
    exe = process_name(pid)
    if exe.lower() == "applicationframehost.exe":
        real = uwp_child_pid(hwnd, pid)
        if real:
            exe = process_name(real) or exe
    return exe, window_title(hwnd), hwnd


oleacc = ctypes.WinDLL("oleacc", use_last_error=True)
oleaut32 = ctypes.WinDLL("oleaut32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]


def _guid(s):
    p = s.strip("{}").split("-")
    g = GUID()
    g.d1, g.d2, g.d3 = int(p[0], 16), int(p[1], 16), int(p[2], 16)
    tail = bytes.fromhex(p[3] + p[4])
    for i in range(8):
        g.d4[i] = tail[i]
    return g


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_uint16), ("r1", ctypes.c_uint16), ("r2", ctypes.c_uint16), ("r3", ctypes.c_uint16),
                ("lVal", ctypes.c_int64), ("pad", ctypes.c_int64)]


IID_IAccessible = _guid("618736E0-3C3D-11CF-810C-00AA00389B71")
OBJID_CLIENT = 0xFFFFFFFC
VT_I4 = 3
oleacc.AccessibleObjectFromWindow.argtypes = [w.HWND, w.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
_GetAccName = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, VARIANT, ctypes.POINTER(ctypes.c_void_p))
_Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)


def com_init():
    ole32.CoInitialize(None)


def accessible_name(hwnd):
    p = ctypes.c_void_p()
    hr = oleacc.AccessibleObjectFromWindow(hwnd, OBJID_CLIENT, ctypes.byref(IID_IAccessible), ctypes.byref(p))
    if hr != 0 or not p:
        return ""
    vtbl = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    get_name = _GetAccName(vtbl[10])
    release = _Release(vtbl[2])
    v = VARIANT()
    v.vt = VT_I4
    bstr = ctypes.c_void_p()
    try:
        hr = get_name(p, v, ctypes.byref(bstr))
        if hr == 0 and bstr:
            return ctypes.wstring_at(bstr)
        return ""
    finally:
        if bstr:
            oleaut32.SysFreeString(bstr)
        release(p)


def is_locked():
    h = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not h:
        return True
    try:
        buf = ctypes.create_unicode_buffer(256)
        needed = w.DWORD(0)
        if user32.GetUserObjectInformationW(h, UOI_NAME, buf, 512, ctypes.byref(needed)):
            return buf.value.lower() == "winlogon"
        return False
    finally:
        user32.CloseDesktop(h)


def write_icon(path, rgb=(0x39, 0x87, 0xE5)):
    sizes = [16, 32, 48]
    images = []
    for s in sizes:
        px = bytearray()
        c = (s - 1) / 2.0
        r = s / 2.0
        for y in range(s - 1, -1, -1):
            for x in range(s):
                d = math.hypot(x - c, y - c)
                a = max(0.0, min(1.0, r - d))
                hand_v = abs(x - c) <= s * 0.045 and c - r * 0.58 <= y <= c + s * 0.03
                hand_h = abs(y - c) <= s * 0.045 and c - s * 0.03 <= x <= c + r * 0.42
                if a > 0 and (hand_v or hand_h):
                    col = (255, 255, 255)
                else:
                    col = rgb
                px += bytes((col[2], col[1], col[0], int(a * 255)))
        row_bytes = ((s + 31) // 32) * 4
        mask = bytes(row_bytes * s)
        header = struct.pack("<IiiHHIIiiII", 40, s, s * 2, 1, 32, 0, len(px) + len(mask), 0, 0, 0, 0)
        images.append((s, header + bytes(px) + mask))
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    for s, data in images:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in images:
        out += data
    with open(path, "wb") as f:
        f.write(out)
