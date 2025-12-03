import os
import time
import json
from typing import Any, Dict

import cv2


class ErroresPlugin:
    """
    Plugin para gestión simple de errores y capturas de diagnóstico.
    """

    def __init__(self) -> None:
        self.last_dump: float = 0.0
        self.dump_interval: float = 10.0  # segundos
        self.errores_dir: str = "errores"

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.errores_dir = os.path.join(base_dir, "errores")
        os.makedirs(self.errores_dir, exist_ok=True)

        interval = config.get("error_dump_interval")
        if isinstance(interval, (int, float)) and interval > 0:
            self.dump_interval = float(interval)

    def _dump_errors(self, state: Dict[str, Any]) -> None:
        errores = state.get("errors", [])
        if not errores:
            return

        ts = int(time.time())
        ruta = os.path.join(self.errores_dir, f"errors_{ts}.json")
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(errores, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _guardar_captura(self, frame) -> None:
        if frame is None:
            return
        ts = int(time.time())
        ruta = os.path.join(self.errores_dir, f"fail_{ts}.jpg")
        try:
            cv2.imwrite(ruta, frame)
        except Exception:
            pass

    def process(self, state: Dict[str, Any]) -> None:
        now = time.time()
        cfg = state.get("config", {})
        save_errors = cfg.get("save_errors", True)

        if save_errors and now - self.last_dump > self.dump_interval:
            self._dump_errors(state)
            self.last_dump = now

        # Aquí podrías escuchar un comando de la GUI para guardar una captura puntual.
        # Ejemplo:
        # if state.get("command") == "save_debug_screenshot":
        #     self._guardar_captura(state.get("frame"))
