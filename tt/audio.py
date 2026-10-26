import ctypes
import ctypes.wintypes as w

from .win import GUID, _guid, process_name

ole32 = ctypes.WinDLL("ole32", use_last_error=True)
powrprof = ctypes.WinDLL("powrprof", use_last_error=True)

CLSID_MMDeviceEnumerator = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioSessionManager2 = _guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_IAudioSessionControl2 = _guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")
IID_IAudioMeterInformation = _guid("C02216F6-8C67-4B5B-9D00-D008E73E0064")
CLSCTX_ALL = 23
eRender = 0
eMultimedia = 1
AudioSessionStateActive = 1
ES_DISPLAY_REQUIRED = 0x2
SystemExecutionState = 16

ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, w.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
powrprof.CallNtPowerInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, w.ULONG, ctypes.c_void_p, w.ULONG]

_QI = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
_Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
_GetDefaultAudioEndpoint = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
_Activate = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), w.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_GetSessionEnumerator = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_GetCount = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
_GetSession = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
_GetState = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
_GetProcessId = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(w.DWORD))
_GetPeakValue = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float))


def _vt(p, i):
    vtbl = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    return vtbl[i]


def _release(p):
    if p:
        _Release(_vt(p, 2))(p)


def _qi(p, iid):
    out = ctypes.c_void_p()
    if _QI(_vt(p, 0))(p, ctypes.byref(iid), ctypes.byref(out)) != 0:
        return None
    return out


def display_required():
    state = w.ULONG(0)
    if powrprof.CallNtPowerInformation(SystemExecutionState, None, 0, ctypes.byref(state), 4) != 0:
        return False
    return bool(state.value & ES_DISPLAY_REQUIRED)


def audio_sessions():
    out = []
    enum = ctypes.c_void_p()
    if ole32.CoCreateInstance(ctypes.byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL, ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(enum)) != 0:
        return out
    device = ctypes.c_void_p()
    mgr = ctypes.c_void_p()
    sessions = ctypes.c_void_p()
    try:
        if _GetDefaultAudioEndpoint(_vt(enum, 4))(enum, eRender, eMultimedia, ctypes.byref(device)) != 0:
            return out
        if _Activate(_vt(device, 3))(device, ctypes.byref(IID_IAudioSessionManager2), CLSCTX_ALL, None, ctypes.byref(mgr)) != 0:
            return out
        if _GetSessionEnumerator(_vt(mgr, 5))(mgr, ctypes.byref(sessions)) != 0:
            return out
        count = ctypes.c_int(0)
        _GetCount(_vt(sessions, 3))(sessions, ctypes.byref(count))
        for i in range(count.value):
            ctl = ctypes.c_void_p()
            if _GetSession(_vt(sessions, 4))(sessions, i, ctypes.byref(ctl)) != 0 or not ctl:
                continue
            try:
                state = ctypes.c_int(0)
                _GetState(_vt(ctl, 3))(ctl, ctypes.byref(state))
                if state.value != AudioSessionStateActive:
                    continue
                ctl2 = _qi(ctl, IID_IAudioSessionControl2)
                meter = _qi(ctl, IID_IAudioMeterInformation)
                pid = w.DWORD(0)
                peak = ctypes.c_float(0)
                if ctl2:
                    _GetProcessId(_vt(ctl2, 14))(ctl2, ctypes.byref(pid))
                    _release(ctl2)
                if meter:
                    _GetPeakValue(_vt(meter, 3))(meter, ctypes.byref(peak))
                    _release(meter)
                out.append((pid.value, peak.value))
            finally:
                _release(ctl)
    finally:
        _release(sessions)
        _release(mgr)
        _release(device)
        _release(enum)
    return out


def playing_exes(threshold=0.001):
    names = set()
    for pid, peak in audio_sessions():
        if peak > threshold and pid:
            name = process_name(pid).lower()
            if name:
                names.add(name)
    return names


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    ole32.CoInitialize(None)
    print("display_required:", display_required())
    for pid, peak in audio_sessions():
        print("pid %6d %-28s peak %.4f" % (pid, process_name(pid), peak))
    print("playing:", playing_exes())
