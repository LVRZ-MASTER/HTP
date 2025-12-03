import numpy as np
import cv2
import time
from typing import Any, Dict

class VisionGuardPlugin:
    """
    Plugin de seguridad visual (Vision Guard).
    Valida la integridad del frame antes de pasarlo a la IA.
    Guarda una imagen de prueba si detecta oscuridad total.
    """

    def __init__(self) -> None:
        self.active = True
        self.last_save_time = 0

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        pass

    def process(self, state: Dict[str, Any]) -> None:
        frame = state.get("frame")

        # 1. Verificar si el frame existe
        if frame is None or frame.size == 0:
            return

        try:
            # Usamos slicing para calcular rápido el brillo promedio
            mean_brightness = np.mean(frame[::4, ::4])

            # UMBRAL DE SEGURIDAD (Ajustable)
            # Si es menor a 5, es prácticamente negro absoluto.
            threshold = 5.0

            # --- DIAGNÓSTICO EN CONSOLA ---
            # Si quieres ver el brillo en tiempo real descomenta la siguiente línea:
            # print(f"DEBUG BRILLO: {mean_brightness:.2f}")

            if mean_brightness < threshold:
                msg = f"⚠️ PANTALLA NEGRA DETECTADA (Brillo: {mean_brightness:.2f}). Anulando frame."
                print(msg) # Imprimir en consola directamente

                # Registrar en GUI
                errs = state.get("errors", [])
                if not errs or errs[-1] != msg:
                    errs.append(msg)
                    state["errors"] = errs[-200:]

                # --- GUARDAR EVIDENCIA VISUAL ---
                # Guarda una foto cada 5 segundos si sigue negra, para que verifiques
                if time.time() - self.last_save_time > 5.0:
                    cv2.imwrite("C:\\HTP\\debug_black_screen.png", frame)
                    print("📸 Guardada imagen de prueba en C:\\HTP\\debug_black_screen.png")
                    self.last_save_time = time.time()

                # ACCIÓN CRÍTICA: Borrar frame para que YOLO no procese basura
                state["frame"] = None

        except Exception as e:
            print(f"Error en VisionGuard: {e}")
