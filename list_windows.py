# lista ventanas top-level visibles y (si es posible) su proceso asociado
# Uso:
#   pip install pygetwindow psutil
#   python list_windows.py
#
# Si pygetwindow/psutil no están instalados, el script usa EnumWindows nativo.

import sys
import ctypes
from ctypes import wintypes
import traceback

try:
    import pygetwindow as gw  # type: ignore
except Exception:
    gw = None

try:
    import psutil
except Exception:
    psutil = None

user32 = ctypes.windll.user32

def enum_windows_with_titles():
    results = []
    if gw is not None:
        try:
            for w in gw.getAllWindows():
                try:
                    title = (getattr(w, "title", "") or "").strip()
                    hwnd = getattr(w, "_hWnd", None)
                    if hwnd and title:
                        results.append((int(hwnd), title))
                except Exception:
                    continue
            return results
        except Exception:
            pass

    # Fallback Win32 EnumWindows
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    GetWindowTextLength = user32.GetWindowTextLengthW
    GetWindowText = user32.GetWindowTextW
    IsWindowVisible = user32.IsWindowVisible

    results = []
    def _enum_proc(hwnd, lParam):
        try:
            if not IsWindowVisible(hwnd):
                return True
            length = GetWindowTextLength(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            GetWindowText(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title:
                results.append((int(hwnd), title))
        except Exception:
            pass
        return True

    EnumWindows(EnumWindowsProc(_enum_proc), 0)
    return results

def get_process_name_for_hwnd(hwnd):
    # GetWindowThreadProcessId
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            if psutil:
                try:
                    p = psutil.Process(pid.value)
                    return p.name()
                except Exception:
                    return str(pid.value)
            else:
                return str(pid.value)
    except Exception:
        pass
    return ""

def main():
    try:
        wins = enum_windows_with_titles()
        print("Ventanas detectadas (hwnd, título, proceso/pid):\n")
        for hwnd, title in wins:
            proc = get_process_name_for_hwnd(hwnd)
            print(f"{hwnd}\t| {title} \t| {proc}")
        if not wins:
            print("No se detectaron ventanas visibles.")
    except Exception:
        print("Error inesperado al listar ventanas:")
        traceback.print_exc()

if __name__ == '__main__':
    main()
