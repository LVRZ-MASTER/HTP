import re
import time
import threading
from typing import Any, Dict, List, Tuple, Optional

try:
    import cv2
    import numpy as np
    # EasyOCR es pesado, lo cargamos solo si está disponible
    import easyocr
except ImportError:
    cv2 = None
    np = None
    easyocr = None

class AdvancedOCRPlugin:
    """
    Plugin de OCR Avanzado.
    Responsabilidades:
    1. Leer el Bote Total (Pot).
    2. Leer el Stack del Hero.
    3. NUEVO: Leer ciegas desde el título de la ventana.
    4. NUEVO: Leer 'Amount to Call' desde los botones de acción.
    """

    def __init__(self) -> None:
        self.reader = None
        self.active = True
        self.model_loaded = False
        self.lock = threading.Lock()
        # Cache para no leer ciegas en cada frame (el título cambia poco)
        self.cached_blinds = {"sb": 0.0, "bb": 0.0}
        self.last_blinds_check = 0

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        """
        Inicializa el modelo EasyOCR en un hilo separado para no congelar el arranque.
        """
        ocr_conf = config.get("ocr", {})
        langs = ocr_conf.get("languages", ["en"])
        use_gpu = ocr_conf.get("gpu", False)

        def _load_model():
            if easyocr:
                try:
                    print("   [OCR] Cargando modelo EasyOCR en memoria...")
                    self.reader = easyocr.Reader(langs, gpu=use_gpu, verbose=False)
                    self.model_loaded = True
                    print("   [OCR] Modelo cargado correctamente.")
                except Exception as e:
                    print(f"   [OCR] Error cargando EasyOCR: {e}")
            else:
                print("   [OCR] EasyOCR no instalado. Funcionalidad limitada.")

        threading.Thread(target=_load_model, daemon=True).start()

    def process(self, state: Dict[str, Any]) -> None:
        """
        Ciclo principal de procesamiento OCR.
        """
        if not self.model_loaded or not self.active:
            return

        frame = state.get("frame")
        if frame is None or frame.size == 0:
            return

        # Configuración de regiones
        config = state.get("config", {})
        layout_name = config.get("active_table_layout", "default_6max_1080p")
        layouts = config.get("table_layouts", {})
        regions = config.get("ocr_regions", {})

        current_layout = layouts.get(layout_name, {})

        # Datos a rellenar
        ocr_results = state.get("ocr_data", {})

        # 1. LEER CIEGAS (Desde el título de la ventana)
        # Hacemos esto cada 2 segundos para ahorrar CPU
        if time.time() - self.last_blinds_check > 2.0:
            win_title = state.get("window_title", "")
            self._parse_blinds_from_title(win_title)
            self.last_blinds_check = time.time()

        ocr_results["sb"] = self.cached_blinds["sb"]
        ocr_results["bb"] = self.cached_blinds["bb"]

        # 2. LEER BOTE (POT)
        pot_reg_conf = regions.get("pot_text", {}).get(layout_name)
        if pot_reg_conf:
            pot_val = self._read_numeric_region(frame, pot_reg_conf, allow_decimals=True)
            # Filtrado básico: el bote no puede ser menor que las ciegas si hay juego
            if pot_val > 0:
                ocr_results["pot_value"] = pot_val
                ocr_results["pot"] = pot_val # Alias compatible

        # 3. LEER STACK HERO
        stack_reg_conf = regions.get("hero_stack", {}).get(layout_name)
        if stack_reg_conf:
            stack_val = self._read_numeric_region(frame, stack_reg_conf, allow_decimals=True)
            if stack_val > 0:
                ocr_results["hero_stack"] = stack_val

        # 4. LEER APUESTA (CALL AMOUNT) DESDE BOTONES
        # Usamos la region 'action_buttons_region' definida en el layout
        btn_reg_conf = current_layout.get("action_buttons_region")
        if btn_reg_conf:
            # Buscamos texto tipo "Call 0.50"
            call_val = self._read_call_button(frame, btn_reg_conf)
            ocr_results["call_amount"] = call_val

        # Guardar todo en el estado compartido
        state["ocr_data"] = ocr_results

    # ----------------------------------------------------------------
    # MÉTODOS PRIVADOS DE AYUDA
    # ----------------------------------------------------------------

    def _parse_blinds_from_title(self, title: str) -> None:
        """
        Busca patrones como "$0.01/$0.02" o "0.5/1" en el título.
        """
        if not title: return

        # Regex robusta para encontrar "numero / numero" con simbolos opcionales
        # Ej: $0.01 / $0.02  o  €0.50/€1.00
        match = re.search(r'[$€£¥]?(\d+(?:[.,]\d+)?)\s*/\s*[$€£¥]?(\d+(?:[.,]\d+)?)', title)

        if match:
            try:
                sb_str = match.group(1).replace(',', '.')
                bb_str = match.group(2).replace(',', '.')
                self.cached_blinds["sb"] = float(sb_str)
                self.cached_blinds["bb"] = float(bb_str)
            except:
                pass

    def _crop_region(self, frame: np.ndarray, rel_rect: List[float]) -> Optional[np.ndarray]:
        """
        Recorta una región relativa [x1, y1, x2, y2] (0.0-1.0).
        """
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = rel_rect

        ix1, iy1 = int(x1 * w), int(y1 * h)
        ix2, iy2 = int(x2 * w), int(y2 * h)

        # Validar coordenadas
        if ix1 < 0 or iy1 < 0 or ix2 > w or iy2 > h or ix1 >= ix2 or iy1 >= iy2:
            return None

        return frame[iy1:iy2, ix1:ix2]

    def _preprocess_for_ocr(self, img: np.ndarray) -> np.ndarray:
        """
        Convierte a escala de grises y aumenta contraste.
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Threshold simple para texto blanco sobre fondo oscuro (común en poker)
        # Se puede ajustar o usar adaptiveThreshold
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        return thresh

    def _read_numeric_region(self, frame: np.ndarray, rect: List[float], allow_decimals: bool = True) -> float:
        """
        Recorta y lee un número. Retorna 0.0 si falla.
        """
        crop = self._crop_region(frame, rect)
        if crop is None: return 0.0

        # Preprocesar
        processed = self._preprocess_for_ocr(crop)

        try:
            # allowlist optimiza OCR para buscar solo numeros y puntos
            allow = '0123456789.,' if allow_decimals else '0123456789'
            results = self.reader.readtext(processed, allowlist=allow, detail=0)

            text = " ".join(results)
            # Limpiar texto: dejar solo digitos y el primer punto
            clean = text.replace(',', '.')

            # Extraer el primer float valido
            match = re.search(r'(\d+\.?\d*)', clean)
            if match:
                return float(match.group(1))
        except Exception:
            pass

        return 0.0

    def _read_call_button(self, frame: np.ndarray, rect: List[float]) -> float:
        """
        Busca la palabra "Call" o "Pagar" y el número asociado.
        """
        crop = self._crop_region(frame, rect)
        if crop is None: return 0.0

        # No usamos threshold binario agresivo aquí porque los botones pueden tener colores
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        try:
            # Leemos todo el texto en la zona de botones
            results = self.reader.readtext(gray, detail=0)
            full_text = " ".join(results).lower()

            # Buscar patrones: "call 2.50", "c 2.50", "pay 2.50"
            # A veces OCR lee "Call" como "Ca11" o "Coll"

            if "call" in full_text or "pagar" in full_text or "match" in full_text or "see" in full_text:
                # Buscar el número que acompaña
                match = re.search(r'(\d+(?:[.,]\d+)?)', full_text)
                if match:
                    val = float(match.group(1).replace(',', '.'))
                    return val

            # Si solo hay un número aislado y estamos en la zona de botones derecha,
            # podría ser el call amount implícito
            # (Lógica arriesgada, mejor ser conservador y retornar 0 si no estamos seguros)

        except Exception:
            pass

        return 0.0
