import time
import ctypes
from typing import Any, Dict, Tuple

try:
    import dxcam
except Exception:
    dxcam = None

try:
    import numpy as np
except Exception:
    np = None

# Intentamos importar Pillow como fallback para capturas si dxcam falla
try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None


class InputHandlerPlugin:
    """
    Captura la ventana de la mesa.

    Mejoras frente a la versión anterior:
    - Valida y clampa la región antes de llamar a dxcam.
    - Si dxcam falla por "Invalid Region", intenta corregirla automáticamente
      usando las dimensiones de la pantalla.
    - Si dxcam no está disponible o sigue fallando, intenta fallback con
      Pillow ImageGrab (si está instalado).
    - Reporta errores y notas en state['debug']['input_last_error'] y en
      state['errors'] (para que la GUI pueda mostrarlos).
    """

    def __init__(self) -> None:
        self.method: str = "dxcam"
        self.camera = None
        self.last_time: float = 0.0
        self.target_fps: float = 30.0
        self.screen_size: Tuple[int, int] | None = None

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        self.method = config.get("capture_method", "dxcam")
        try:
            self.target_fps = float(config.get("fps_active", 30))
        except Exception:
            self.target_fps = 30.0

        debug = state.setdefault("debug", {})
        debug.setdefault("input_last_error", "")

        # Crear cámara dxcam si está disponible
        if self.method == "dxcam" and dxcam is not None:
            try:
                # output_color BGR es lo que espera el pipeline
                self.camera = dxcam.create(output_color="BGR")
                debug["input_last_error"] = ""
            except Exception as e:
                debug["input_last_error"] = f"Error creando cámara DXCam: {e}"
                self.camera = None
        else:
            # No usamos dxcam
            if dxcam is None and self.method == "dxcam":
                debug["input_last_error"] = "dxcam no disponible en el entorno."
            else:
                debug["input_last_error"] = "Método de captura no soportado."
            self.camera = None

        # Obtener tamaño de pantalla (fallback con ctypes)
        try:
            self.screen_size = self._get_screen_size()
        except Exception:
            self.screen_size = None

        state["debug"] = debug

    def _get_screen_size(self) -> Tuple[int, int]:
        """
        Devuelve (width, height) de la pantalla principal.
        Usa dxcam si está disponible, si no usa GetSystemMetrics de Win32.
        """
        # dxcam puede proporcionar info más fiable en multi-monitor
        if self.camera is not None:
            try:
                # Algunas versiones de dxcam exponen .screensize
                size = getattr(self.camera, "screensize", None)
                if size and isinstance(size, tuple) and len(size) == 2:
                    return (int(size[0]), int(size[1]))
            except Exception:
                pass

        # Fallback Win32
        try:
            user32 = ctypes.windll.user32
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            return (int(width), int(height))
        except Exception:
            # Último recurso: valores razonables
            return (1920, 1080)

    def _append_error(self, state: Dict[str, Any], msg: str) -> None:
        errs = state.get("errors", [])
        errs.append(msg)
        state["errors"] = errs[-200:]

    def _clamp_region(self, rect: Tuple[float, float, float, float]) -> Tuple[int, int, int, int, str]:
        """
        Valida y clampa la región contra screen_size.
        Entrada rect: (x, y, w, h) en píxeles (posibles floats).
        Retorna (x, y, w, h, note) con valores enteros y una nota si fue ajustado.
        """
        note = ""
        try:
            sx, sy = self.screen_size if self.screen_size else self._get_screen_size()
        except Exception:
            sx, sy = (1920, 1080)

        try:
            x, y, w, h = rect
            x = int(round(x))
            y = int(round(y))
            w = int(round(w))
            h = int(round(h))
        except Exception:
            # Rect malformado -> devolver pantalla completa
            return 0, 0, sx, sy, "region malformada; usando pantalla completa"

        # Clamp x,y
        if x < 0:
            note += f"x ajustado {x}->0; "
            x = 0
        if y < 0:
            note += f"y ajustado {y}->0; "
            y = 0

        # Clamp w,h para que no salgan del screen
        if w <= 0 or h <= 0:
            # invalid dims -> full width/height from that point
            w = max(1, sx - x)
            h = max(1, sy - y)
            note += "dimensiones inválidas; ajustadas; "

        if x + w > sx:
            old_w = w
            w = max(1, sx - x)
            note += f"w ajustado {old_w}->{w}; "

        if y + h > sy:
            old_h = h
            h = max(1, sy - y)
            note += f"h ajustado {old_h}->{h}; "

        return x, y, w, h, note.strip()

    def _frame_from_pillow(self, bbox: Tuple[int, int, int, int]):
        """
        Captura con Pillow (ImageGrab) y devuelve ndarray BGR si numpy está disponible.
        bbox = (x1, y1, x2, y2)
        """
        if ImageGrab is None or np is None:
            raise RuntimeError("Pillow or numpy not available for fallback capture.")
        img = ImageGrab.grab(bbox=bbox)  # PIL Image RGB
        arr = np.array(img)  # H x W x 3 RGB
        # Convertir RGB -> BGR
        arr = arr[:, :, ::-1].copy()
        return arr

    def process(self, state: Dict[str, Any]) -> None:
        """
        Intenta capturar region = state['window_rect'].
        Si falla por region inválida, intenta clamp y reintentar.
        Si dxcam no está disponible o sigue fallando, intenta fallback con Pillow.
        Actualiza:
          - state['frame'] = ndarray BGR o None
          - state['fps_current']
          - state['debug']['input_last_error']
          - state['errors'] (mensajes importantes)
        """
        now = time.time()
        # Control básico de FPS
        if self.last_time > 0 and (now - self.last_time) < (1.0 / max(1, self.target_fps)):
            return

        self.last_time = now
        debug = state.setdefault("debug", {})
        debug.setdefault("input_last_error", "")

        rect = state.get("window_rect")
        if rect is None:
            debug["input_last_error"] = "window_rect es None; no se ha detectado ventana aún."
            state["frame"] = None
            state["debug"] = debug
            return

        # Normalizar rect (esperamos tupla/lista 4: x,y,w,h)
        if not (isinstance(rect, (list, tuple)) and len(rect) == 4):
            debug["input_last_error"] = "window_rect malformado; debe ser [x,y,w,h]."
            state["frame"] = None
            state["debug"] = debug
            return

        # Obtener screen size si no la tenemos
        if self.screen_size is None:
            try:
                self.screen_size = self._get_screen_size()
            except Exception:
                self.screen_size = (1920, 1080)

        # Clamp region para que quede dentro de pantalla
        x, y, w, h, note = self._clamp_region(rect)
        if note:
            # Si hubo ajuste, añadir mensaje al debug y al log de errores
            msg = f"Nota ajuste region: {note}"
            debug["input_last_error"] = msg
            self._append_error(state, msg)

        # Intentar captura con dxcam si está disponible
        frame = None
        if self.camera is not None:
            try:
                # dxcam espera region como (left, top, right, bottom)
                region = (x, y, x + w, y + h)
                frame = self.camera.grab(region=region)
            except Exception as e:
                # Captura fallida con dxcam: registrar y probar fallback
                err = f"DXCam grab error: {e}"
                debug["input_last_error"] = f"Excepción capturando frame: {e}"
                self._append_error(state, debug["input_last_error"])
                frame = None

        # Si no tenemos frame aún, intentar fallback con Pillow si está disponible
        if frame is None:
            if ImageGrab is not None and np is not None:
                try:
                    bbox = (x, y, x + w, y + h)
                    frame = self._frame_from_pillow(bbox)
                    debug["input_last_error"] = ""  # éxito fallback
                    # anotar que usamos fallback
                    self._append_error(state, f"Captura fallback con Pillow usada para bbox={bbox}")
                except Exception as e:
                    err = f"Pillow fallback failed: {e}"
                    debug["input_last_error"] = f"Excepción fallback captura: {e}"
                    self._append_error(state, debug["input_last_error"])
                    frame = None
            else:
                # No hay fallback posible
                if self.camera is None:
                    debug["input_last_error"] = "No hay método de captura funcional (dxcam ausente y Pillow no disponible)."
                else:
                    # camera presente pero frame None: error ya registrado arriba
                    pass

        # Actualizar estado final
        if frame is None:
            state["frame"] = None
            # dejar fps si no hay frame (no actualizar)
        else:
            state["frame"] = frame
            # Actualizar fps simple
            # dt puede ser muy pequeño; evitamos div por cero
            prev = state.get("fps_current", 0.0)
            dt = now - (self.last_time if self.last_time else now)
            # Calculamos fps con el tiempo entre frames (mejorado)
            try:
                # Usamos la propia marca now y last_time (last_time ya actualizado)
                # Para estabilidad, calculamos fps como 1 / (time since previous capture)
                fps = 1.0 / max(1e-6, now - (self.last_time - (1.0 / max(1, self.target_fps))))
                # No sobreescribimos con valores absurdos:
                if 0 < fps < 1000:
                    state["fps_current"] = fps
            except Exception:
                # fallback sencillo
                state["fps_current"] = prev

        # Guardar debug
        state["debug"] = debug
