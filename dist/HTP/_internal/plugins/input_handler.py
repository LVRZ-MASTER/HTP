import time
from typing import Any, Dict, Optional

import dxcam
import numpy as np


class InputHandlerPlugin:
    """
    Plugin de captura de imagen.

    Responsabilidades:
    - Usar DXcam (Desktop Duplication API) para capturar la pantalla completa.
    - Recortar el frame al rectángulo SharedState["window_rect"] si está definido.
    - Actualizar:
        - state["frame"]       : numpy.ndarray (BGR)
        - state["frame_timestamp"] : float (time.time())
    - Cooperar con self_check_plugin/errores para diagnóstico de pantalla negra, etc.

    Notas:
    - capture_method se lee desde config["capture_method"] (por ahora soportado: "dxcam").
    - En el futuro se podrían añadir otros métodos ("hdmi", "obs", etc.).
    """

    def __init__(self) -> None:
        self.capture_method: str = "dxcam"
        self.camera: Optional[dxcam.DXCamera] = None
        self.started: bool = False
        self.target_fps: float = 30.0

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        """
        Inicializa la cámara según config.
        """
        self.capture_method = config.get("capture_method", "dxcam")
        self.target_fps = float(config.get("fps_active", 30))

        if self.capture_method == "dxcam":
            try:
                self.camera = dxcam.create(output_color="BGR")
                self.camera.start(target_fps=int(self.target_fps))
                self.started = True
            except Exception:
                self.camera = None
                self.started = False
        else:
            # Otros métodos no implementados aún
            self.camera = None
            self.started = False

    def _recortar_a_window_rect(self, frame: np.ndarray, state: Dict[str, Any]) -> np.ndarray:
        """
        Recorta el frame al rectángulo SharedState["window_rect"] si existe.
        Si no hay rectángulo o es inválido, retorna el frame completo.
        """
        rect = state.get("window_rect")
        if not rect or frame is None:
            return frame

        try:
            x, y, w, h = rect
            h_img, w_img = frame.shape[:2]

            x1 = max(0, int(x))
            y1 = max(0, int(y))
            x2 = min(w_img, x1 + int(w))
            y2 = min(h_img, y1 + int(h))

            if x1 >= x2 or y1 >= y2:
                return frame

            return frame[y1:y2, x1:x2]
        except Exception:
            return frame

    def process(self, state: Dict[str, Any]) -> None:
        """
        Captura el frame más reciente y lo coloca en SharedState.
        """
        if not self.started or self.camera is None:
            return

        try:
            frame = self.camera.get_latest_frame()
        except Exception:
            frame = None

        if frame is None:
            # No actualizamos frame, pero dejamos que self_check/errores se encarguen
            return

        # Recortar al rectángulo de la mesa si está disponible
        frame = self._recortar_a_window_rect(frame, state)

        state["frame"] = frame
        state["frame_timestamp"] = time.time()
