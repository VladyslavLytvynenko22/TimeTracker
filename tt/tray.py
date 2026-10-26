import ctypes
import ctypes.wintypes as w
import logging
import threading

log = logging.getLogger("tt.tray")

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAY = WM_USER + 1
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_NULL = 0x0000
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10
NIIF_INFO = 0x01
NOTIFYICON_VERSION_4 = 4
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
WS_OVERLAPPED = 0
CW_USEDEFAULT = 0x80000000 - 0x100000000

ID_OPEN = 1001
ID_PAUSE = 1002
ID_QUIT = 1003

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", w.HINSTANCE), ("hIcon", w.HICON), ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT), ("uCallbackMessage", w.UINT),
                ("hIcon", w.HICON), ("szTip", w.WCHAR * 128), ("dwState", w.DWORD), ("dwStateMask", w.DWORD),
                ("szInfo", w.WCHAR * 256), ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", w.HICON)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.CreateWindowExW.restype = w.HWND
user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.LoadImageW.restype = w.HANDLE
user32.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
user32.CreatePopupMenu.restype = w.HMENU
user32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
user32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.LPVOID]
user32.DestroyMenu.argtypes = [w.HMENU]
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
shell32.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = w.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]


class Tray(threading.Thread):
    def __init__(self, icon_path, on_open, on_pause, on_quit, is_paused):
        super().__init__(name="tray", daemon=True)
        self.icon_path = icon_path
        self.on_open = on_open
        self.on_pause = on_pause
        self.on_quit = on_quit
        self.is_paused = is_paused
        self.hwnd = None
        self.hicon = None
        self.ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)
        self._tip = "TimeTracker"

    def run(self):
        try:
            self._create()
        except Exception as e:
            log.error("tray init failed: %s", e)
            self.ready.set()
            return
        self.ready.set()
        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._remove()

    def _create(self):
        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW()
        cls.lpfnWndProc = self._proc
        cls.hInstance = hinst
        cls.lpszClassName = "TimeTrackerTray"
        if not user32.RegisterClassW(ctypes.byref(cls)):
            err = ctypes.get_last_error()
            if err != 1410:
                raise ctypes.WinError(err)
        self.hwnd = user32.CreateWindowExW(0, "TimeTrackerTray", "TimeTracker", WS_OVERLAPPED, 0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hicon = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self._tip
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        nid.uVersion = NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))

    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _remove(self):
        if self.hwnd:
            nid = self._nid()
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    def set_tip(self, text):
        self._tip = text[:127]
        if not self.hwnd:
            return
        nid = self._nid()
        nid.uFlags = NIF_TIP
        nid.szTip = self._tip
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def balloon(self, title, body):
        if not self.hwnd:
            raise RuntimeError("tray not available")
        nid = self._nid()
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = body[:255]
        nid.dwInfoFlags = NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, ID_OPEN, "Open dashboard")
        user32.AppendMenuW(menu, MF_STRING, ID_PAUSE, "Resume tracking" if self.is_paused() else "Pause tracking")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "Quit TimeTracker")
        pt = w.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN, pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_TRAY:
                ev = lp & 0xFFFF
                if ev in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.on_open()
                elif ev == WM_RBUTTONUP:
                    self._menu()
                return 0
            if msg == WM_COMMAND:
                cmd = wp & 0xFFFF
                if cmd == ID_OPEN:
                    self.on_open()
                elif cmd == ID_PAUSE:
                    self.on_pause()
                elif cmd == ID_QUIT:
                    self.on_quit()
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self._remove()
                self.hwnd = None
                user32.PostQuitMessage(0)
                return 0
        except Exception as e:
            log.error("tray wndproc error: %s", e)
        return user32.DefWindowProcW(hwnd, msg, wp, lp)
