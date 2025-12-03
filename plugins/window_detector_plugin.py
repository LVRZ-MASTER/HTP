import time
import os
import ctypes
import threading
from typing import Any, Dict, List, Tuple, Optional

# Intentamos usar pygetwindow y psutil si están disponibles para obtener más info.
try:
    import pygetwindow as gw  # type: ignore
except Exception:
    gw = None

try:
    import psutil
except Exception:
    psutil = None

from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_RESTORE = 9


def _enum_windows() -> List[Tuple[int, str]]:
    """
    Enumera ventanas top-level visibles y devuelve lista de (hwnd, title).
    Usa pygetwindow si está; si no, usa EnumWindows (Win32).
    """
    results: List[Tuple[int, str]] = []
    if gw is not None:
        try:
            for w in gw.getAllWindows():
                try:
                    title = (getattr(w, "title", "") or "").strip()
                    hwnd = getattr(w, "_hWnd", None)
                    if hwnd is None:
                        continue
                    # Filtrar ventanas sin título
                    if not title:
                        continue
                    results.append((int(hwnd), title))
                except Exception:
                    continue
            return results
        except Exception:
            # caemos al fallback nativo
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


def _get_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    """
    Devuelve (left, top, right, bottom) en coordenadas de pantalla.
    """
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _is_window_minimized(hwnd: int) -> bool:
    """
    Comprueba si la ventana está minimizada (IsIconic).
    """
    try:
        return bool(user32.IsIconic(hwnd))
    except Exception:
        return False


def _restore_window(hwnd: int) -> None:
    """
    Restaura la ventana si está minimizada.
    """
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
    except Exception:
        pass


def _get_process_name_for_hwnd(hwnd: int) -> Optional[str]:
    """
    Intenta obtener el proceso asociado a la ventana (sólo en Windows).
    Requiere psutil; si no está, devuelve None.
    """
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
    return None


class WindowDetectorPlugin:
    """
    Plugin encargado de detectar la ventana del cliente de poker y publicar
    state['window_rect'] = (x, y, w, h) en coordenadas de pantalla.

    Config (config/config.json):
    - window_title_candidates: list of substrings to match in window title (case-insensitive)
    - window_process_candidates: list of process names to match (e.g. ["GGnet.exe"])
    - restore_window: boolean (if True, attempt to restore minimized windows)
    - window_detection_interval: seconds between detection attempts (default 1.0)
    - allow_partial_match: boolean (default True)
    """

    def __init__(self) -> None:
        self.last_check = 0.0
        self.interval = 1.0
        self.restore_window = False
        self.candidates: List[str] = ["GGPoker", "GG", "Poker"]
        self.process_candidates: List[str] = []
        self.allow_partial_match = True
        self._state = None
        self._lock = threading.Lock()

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        """
        Inicializa el plugin con la configuración disponible.
        """
        self._state = state
        conf_cands = config.get("window_title_candidates")
        if isinstance(conf_cands, list) and conf_cands:
            self.candidates = [str(x) for x in conf_cands]
        else:
            # also accept comma separated string
            conf_str = config.get("window_title_candidates")
            if isinstance(conf_str, str) and conf_str.strip():
                self.candidates = [s.strip() for s in conf_str.split(",") if s.strip()]

        proc_cands = config.get("window_process_candidates")
        if isinstance(proc_cands, list) and proc_cands:
            self.process_candidates = [str(x) for x in proc_cands]
        else:
            proc_str = config.get("window_process_candidates")
            if isinstance(proc_str, str) and proc_str.strip():
                self.process_candidates = [s.strip() for s in proc_str.split(",") if s.strip()]

        self.restore_window = bool(config.get("restore_window", False))
        try:
            self.interval = float(config.get("window_detection_interval", 1.0))
        except Exception:
            self.interval = 1.0

        self.allow_partial_match = bool(config.get("allow_partial_match", True))

        debug = state.setdefault("debug", {})
        debug.setdefault("window_last_error", "")
        debug.setdefault("detected_window_title", "")
        debug.setdefault("detected_window_rect", None)
        debug.setdefault("available_windows", [])
        debug.setdefault("window_dpi_scale", 1.0)
        debug.setdefault("window_process_candidates", self.process_candidates)
        state["debug"] = debug

    def _append_error(self, state: Dict[str, Any], msg: str) -> None:
        errs = state.get("errors", [])
        # Evitar duplicados seguidos
        if not errs or errs[-1] != msg:
            errs.append(msg)
        state["errors"] = errs[-200:]

    def _match_title(self, title: str) -> bool:
        """
        Comprueba si 'title' coincide con alguna de las candidates usando partial match o exact.
        """
        if not title:
            return False
        t = title.lower()
        for cand in self.candidates:
            c = cand.lower()
            if self.allow_partial_match:
                if c in t:
                    return True
            else:
                if c == t:
                    return True
        return False

    def _match_process(self, proc_name: Optional[str]) -> bool:
        """
        Comprueba si el nombre del proceso coincide con alguno de process_candidates.
        """
        if not proc_name:
            return False
        pn = proc_name.lower()
        for p in self.process_candidates:
            if p.lower() == pn:
                return True
        return False

    def process(self, state: Dict[str, Any]) -> None:
        """
        Ejecuta la detección periódica de la ventana. Actualiza:
          - state['window_rect'] = (x, y, w, h) o None
          - state['window_title'] = title or ""
          - state['debug'] con campos útiles (available_windows, detected_window_rect, etc.)
        """
        # Protegemos contra concurrencia si algún otro hilo consulta state
        with self._lock:
            now = time.time()
            if now - self.last_check < self.interval:
                return
            self.last_check = now

            debug = state.setdefault("debug", {})
            debug.setdefault("window_last_error", "")
            debug.setdefault("detected_window_title", "")
            debug.setdefault("detected_window_rect", None)
            debug.setdefault("available_windows", [])
            debug.setdefault("window_dpi_scale", 1.0)
            debug.setdefault("window_process_candidates", self.process_candidates)

            # Enumerar ventanas disponibles para debug y ayudar a usuario
            try:
                windows = _enum_windows()
                avail = []
                for hwnd, title in windows[:200]:
                    proc = _get_process_name_for_hwnd(hwnd)
                    avail.append({"hwnd": int(hwnd), "title": title, "process": proc})
                debug["available_windows"] = avail
            except Exception as e:
                debug["available_windows"] = []
                debug["window_last_error"] = f"Error enumerando ventanas: {e}"
                state["debug"] = debug
                # No abortamos; seguimos intentando con lo que tengamos
            # Buscar coincidencias por título y/o proceso
            matches: List[Tuple[int, str]] = []
            try:
                for hwnd, title in windows:
                    try:
                        proc = _get_process_name_for_hwnd(hwnd)
                        title_match = self._match_title(title)
                        proc_match = self._match_process(proc)
                        if title_match or proc_match:
                            matches.append((hwnd, title))
                    except Exception:
                        continue
            except Exception:
                matches = []

            if not matches:
                msg = f"No se encontraron ventanas que coincidan con títulos {self.candidates} ni procesos {self.process_candidates}"
                debug["window_last_error"] = msg
                debug["detected_window_title"] = ""
                debug["detected_window_rect"] = None
                state["window_rect"] = None
                state["window_title"] = ""
                # Añadir error no repetido
                self._append_error(state, msg)
                state["debug"] = debug
                return

            # Priorizar la primera ventana visible y no minimizada
            chosen_hwnd = None
            chosen_title = ""
            for hwnd, title in matches:
                try:
                    if not bool(user32.IsWindowVisible(hwnd)):
                        continue
                except Exception:
                    pass
                chosen_hwnd = hwnd
                chosen_title = title
                break

            if not chosen_hwnd:
                chosen_hwnd, chosen_title = matches[0]

            # Si ventana minimizada, comportamiento configurable
            if _is_window_minimized(chosen_hwnd):
                msg = f"Ventana '{chosen_title}' detectada pero está minimizada."
                debug["window_last_error"] = msg
                debug["detected_window_title"] = chosen_title
                debug["detected_window_rect"] = None
                state["window_rect"] = None
                state["window_title"] = chosen_title
                if self.restore_window:
                    try:
                        _restore_window(chosen_hwnd)
                        time.sleep(0.15)
                        # intentar obtener rect de nuevo más abajo
                    except Exception:
                        pass
                else:
                    # registrar error si no estaba ya al final
                    self._append_error(state, msg)
                    state["debug"] = debug
                    return

            # Obtener rect y validar
            try:
                left, top, right, bottom = _get_window_rect(chosen_hwnd)
                width = max(0, right - left)
                height = max(0, bottom - top)

                # Detectar rect inválido (coordenadas extremas)
                if left <= -30000 or top <= -30000 or width <= 0 or height <= 0:
                    msg = f"Rect inválido detectado para '{chosen_title}': {(left, top, width, height)}"
                    debug["window_last_error"] = msg
                    debug["detected_window_title"] = chosen_title
                    debug["detected_window_rect"] = None
                    state["window_rect"] = None
                    state["window_title"] = chosen_title
                    self._append_error(state, msg)
                    state["debug"] = debug
                    return

                # Intento de obtener DPI scale (si falla, dejar 1.0)
                scale = 1.0
                try:
                    GetDpiForWindow = getattr(user32, "GetDpiForWindow", None)
                    if GetDpiForWindow:
                        dpi = GetDpiForWindow(chosen_hwnd)
                        scale = float(dpi) / 96.0
                except Exception:
                    try:
                        hdc = user32.GetDC(0)
                        LOGPIXELSX = 88
                        gdi32 = ctypes.windll.gdi32
                        dpi_x = gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
                        user32.ReleaseDC(0, hdc)
                        if dpi_x and dpi_x > 0:
                            scale = float(dpi_x) / 96.0
                    except Exception:
                        scale = 1.0

                debug["detected_window_title"] = chosen_title
                debug["detected_window_rect"] = (left, top, width, height)
                debug["window_dpi_scale"] = scale

                # Guardar en state en formato (x, y, w, h) que usa el pipeline
                state["window_rect"] = (left, top, width, height)
                state["window_title"] = chosen_title

                # limpiar errores previos
                debug["window_last_error"] = ""
                state["debug"] = debug

            except Exception as e:
                msg = f"Excepción al obtener rect de ventana '{chosen_title}': {e}"
                debug["window_last_error"] = msg
                state["window_rect"] = None
                state["window_title"] = ""
                self._append_error(state, msg)
                state["debug"] = debug
                return
