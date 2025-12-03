import os
import time
from typing import Any, Dict, List, Optional, Tuple

from ultralytics import YOLO

try:
    from htp import logger as core_logger
except Exception:
    core_logger = None


class VisionCorePlugin:
    """
    Plugin de visión principal.

    - Carga modelo YOLO (PT/ONNX/OpenVINO).
    - Ejecuta inferencia sobre state["frame"].
    - Actualiza:
        - state["detections"] (filtradas por conf)
        - state["vision_ok"]
        - state["debug"]["vision_core_loaded"]
        - state["debug"]["vision_last_error"]
        - state["debug"]["last_detection_count"]
        - state["debug"]["yolo_class_names"]
        - state["debug"]["last_raw_detections"]
        - state["errors"] (mensajes importantes)
    """

    def __init__(self) -> None:
        self.model: Optional[YOLO] = None
        self.model_path: str = ""
        self.confidence_threshold: float = 0.4
        self.last_run: float = 0.0
        self.min_interval: float = 0.05  # Máx ~20 FPS inferencia
        self._load_failed: bool = False

    def _log(self, msg: str) -> None:
        if core_logger is not None:
            core_logger.info(f"[VisionCore] {msg}")
        else:
            print(f"[VisionCore] {msg}")

    def _append_error(self, state: Dict[str, Any], msg: str) -> None:
        errs = state.get("errors", [])
        errs.append(msg)
        state["errors"] = errs[-50:]

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        debug = state.setdefault("debug", {})
        debug["vision_core_loaded"] = False
        debug["vision_last_error"] = ""
        debug["yolo_class_names"] = []
        debug["last_raw_detections"] = []

        self.model_path = config.get("yolo_model_path", "").strip()
        self.confidence_threshold = float(config.get("yolo_conf_threshold", 0.4))

        if not self.model_path:
            msg = "yolo_model_path no definido en config.json, visión desactivada."
            self._log(msg)
            debug["vision_last_error"] = msg
            self._load_failed = True
            self._append_error(state, msg)
            return

        if not os.path.exists(self.model_path):
            msg = f"Ruta de modelo no existe: {self.model_path}"
            self._log(msg)
            debug["vision_last_error"] = msg
            self._load_failed = True
            self._append_error(state, msg)
            return

        # Intento principal: path directo (ideal carpeta OpenVINO)
        try:
            self._log(f"Cargando modelo YOLO desde: {self.model_path}")
            self.model = YOLO(self.model_path, task="detect")
            self._log(f"Modelo YOLO cargado correctamente: {self.model_path}")
            debug["vision_core_loaded"] = True

            names = getattr(self.model, "names", None)
            if isinstance(names, dict):
                debug["yolo_class_names"] = [names[k] for k in sorted(names.keys())]
            elif isinstance(names, list):
                debug["yolo_class_names"] = names
            else:
                debug["yolo_class_names"] = []

            self._append_error(
                state,
                f"Modelo YOLO cargado. Clases: {', '.join(debug['yolo_class_names'])}",
            )

        except Exception as e:
            self._log(f"Primer intento de carga falló: {e}")
            debug["vision_last_error"] = str(e)
            self._append_error(
                state,
                f"Fallo inicial cargando modelo YOLO desde {self.model_path}: {e}",
            )

            if self.model_path.lower().endswith(".xml"):
                try:
                    openvino_dir = os.path.dirname(self.model_path)
                    self._log(
                        f"Reintentando carga como OpenVINO desde carpeta: {openvino_dir}"
                    )
                    self.model = YOLO(openvino_dir, task="detect")
                    self._log(
                        f"Modelo OpenVINO cargado desde carpeta: {openvino_dir}"
                    )
                    debug["vision_core_loaded"] = True
                    debug["vision_last_error"] = ""

                    names = getattr(self.model, "names", None)
                    if isinstance(names, dict):
                        debug["yolo_class_names"] = [
                            names[k] for k in sorted(names.keys())
                        ]
                    elif isinstance(names, list):
                        debug["yolo_class_names"] = names
                    else:
                        debug["yolo_class_names"] = []

                    self._append_error(
                        state,
                        "Modelo OpenVINO cargado desde carpeta "
                        f"{openvino_dir}. Clases: "
                        f"{', '.join(debug['yolo_class_names'])}",
                    )

                except Exception as e2:
                    msg2 = f"No se pudo cargar modelo OpenVINO: {e2}"
                    self._log(msg2)
                    debug["vision_last_error"] = msg2
                    self._load_failed = True
                    self._append_error(state, msg2)
            else:
                self._load_failed = True

        if self._load_failed:
            msg = (
                "Fallo al cargar el modelo YOLO. Revisa yolo_model_path o el formato. "
                f"Último error: {debug.get('vision_last_error', '')}"
            )
            self._log(msg)
            self._append_error(state, msg)

    def _postprocess(
        self,
        results,
        frame_shape: Tuple[int, int, int],
    ) -> List[Dict[str, Any]]:
        """
        Convierte resultados de Ultralytics a una lista de detecciones:
        [
          {
            "label": "Algo",
            "conf": 0.92,
            "box": [x1, y1, x2, y2],
          },
          ...
        ]
        """
        detections: List[Dict[str, Any]] = []
        if not results:
            return detections

        r = results[0]
        boxes = getattr(r, "boxes", None)
        names = getattr(r, "names", {})

        if boxes is None:
            return detections

        for box in boxes:
            try:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
            except Exception:
                continue

            label = names.get(cls_id, str(cls_id))

            detections.append(
                {
                    "label": str(label),
                    "conf": conf,
                    "box": [float(x1), float(y1), float(x2), float(y2)],
                }
            )

        return detections

    def process(self, state: Dict[str, Any]) -> None:
        debug = state.setdefault("debug", {})
        if self._load_failed or self.model is None:
            return

        frame = state.get("frame")
        if frame is None:
            debug["vision_last_error"] = (
                "frame es None; input_handler no está capturando."
            )
            return

        now = time.time()
        if now - self.last_run < self.min_interval:
            return
        self.last_run = now

        try:
            results = self.model(frame, verbose=False)
        except Exception as e:
            msg = f"Error ejecutando inferencia YOLO: {e}"
            self._log(msg)
            debug["vision_last_error"] = msg
            self._append_error(state, msg)
            return

        raw_dets = self._postprocess(results, frame.shape)
        debug["last_raw_detections"] = [
            {"label": d["label"], "conf": round(d["conf"], 3)}
            for d in raw_dets[:20]
        ]

        filtered = [
            d for d in raw_dets if d["conf"] >= self.confidence_threshold
        ]

        state["detections"] = filtered
        debug["last_detection_count"] = len(filtered)

        if filtered:
            debug["vision_last_error"] = ""
        else:
            debug["vision_last_error"] = (
                "YOLO no devolvió detecciones sobre el umbral "
                f"(umbral={self.confidence_threshold}, raw={len(raw_dets)})."
            )

        state["vision_ok"] = True
