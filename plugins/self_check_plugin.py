import time
from typing import Any, Dict

import numpy as np


class SelfCheckPlugin:
    """
    Plugin de autodiagnóstico básico.

    Responsabilidades:
    - Marcar state["system_checked"] una vez realizado el chequeo inicial.
    - Estimar si la captura es válida o pantalla negra:
        - Usa el último frame de state["frame"] (cuando exista).
        - Calcula brillo promedio y desviación estándar.
        - Marca state["vision_ok"] = True/False.
    - Puede ejecutarse cada cierto intervalo para actualizar el estado de salud.
    """

    def __init__(self) -> None:
        self.last_check: float = 0.0
        self.check_interval: float = 3.0  # segundos
        self.black_threshold: float = 5.0 # brillo y desviación

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        interval = config.get("self_check_interval")
        if isinstance(interval, (int, float)) and interval > 0:
            self.check_interval = float(interval)

    def process(self, state: Dict[str, Any]) -> None:
        now = time.time()
        if now - self.last_check < self.check_interval:
            return
        self.last_check = now

        frame = state.get("frame")
        if frame is None:
            # Si no hay frame, no sabemos; lo marcamos como no OK de momento
            state["vision_ok"] = False
            if not state.get("system_checked", False):
                state["system_checked"] = True
            return

        try:
            brillo = float(np.mean(frame))
            desviacion = float(np.std(frame))
        except Exception:
            brillo = 0.0
            desviacion = 0.0

        if brillo < self.black_threshold and desviacion < self.black_threshold:
            # Pantalla prácticamente negra
            state["vision_ok"] = False
        else:
            state["vision_ok"] = True

        if not state.get("system_checked", False):
            state["system_checked"] = True
