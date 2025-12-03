@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ======================================================
REM Instalador básico de estructura para HTP
REM Crea carpetas y archivos mínimos sin tocar dependencias
REM Directorio raíz esperado: C:\HTP (puedes cambiar ROOT_DIR)
REM ======================================================

set "ROOT_DIR=C:\HTP"

echo.
echo =========================================
echo   Instalador de estructura HTP
echo   Directorio raiz: %ROOT_DIR%
echo =========================================
echo.

REM Crear estructura de directorios principal
echo [1/6] Creando directorios base...

mkdir "%ROOT_DIR%" 2>nul
mkdir "%ROOT_DIR%\logs" 2>nul
mkdir "%ROOT_DIR%\config" 2>nul
mkdir "%ROOT_DIR%\plugins" 2>nul
mkdir "%ROOT_DIR%\errores" 2>nul

REM Subcarpetas opcionales para futuro (core/capture/analysis/interface)
mkdir "%ROOT_DIR%\plugins\core" 2>nul
mkdir "%ROOT_DIR%\plugins\capture" 2>nul
mkdir "%ROOT_DIR%\plugins\analysis" 2>nul
mkdir "%ROOT_DIR%\plugins\interface" 2>nul

echo [OK] Directorios creados.
echo.

REM Crear __init__.py para que plugins sea un paquete Python
echo [2/6] Creando __init__.py en plugins...

if not exist "%ROOT_DIR%\plugins\__init__.py" (
    > "%ROOT_DIR%\plugins\__init__.py" echo # Paquete de plugins HTP
)

if not exist "%ROOT_DIR%\plugins\core\__init__.py" (
    > "%ROOT_DIR%\plugins\core\__init__.py" echo # Paquete core de plugins HTP
)

if not exist "%ROOT_DIR%\plugins\capture\__init__.py" (
    > "%ROOT_DIR%\plugins\capture\__init__.py" echo # Paquete capture de plugins HTP
)

if not exist "%ROOT_DIR%\plugins\analysis\__init__.py" (
    > "%ROOT_DIR%\plugins\analysis\__init__.py" echo # Paquete analysis de plugins HTP
)

if not exist "%ROOT_DIR%\plugins\interface\__init__.py" (
    > "%ROOT_DIR%\plugins\interface\__init__.py" echo # Paquete interface de plugins HTP
)

echo [OK] __init__.py creados.
echo.

REM Crear esqueleto de config.json si no existe
echo [3/6] Creando config\config.json basico (si no existe)...

if not exist "%ROOT_DIR%\config\config.json" (
    > "%ROOT_DIR%\config\config.json" (
        echo {
        echo   "fps_idle": 5,
        echo   "fps_active": 30,
        echo   "debug_mode": false,
        echo   "save_errors": true,
        echo   "capture_method": "dxcam",
        echo   "yolo_model_path": "C:\\HTP\\yoloDS\\runs\\detect\\HTP_v11_final\\weights\\best_openvino_model",
        echo   "host": "0.0.0.0",
        echo   "port": 8000
        echo }
    )
    echo [OK] config.json creado.
) else (
    echo [SKIP] config.json ya existe, no se modifica.
)

echo.

REM Crear esqueletos de plugins principales si no existen
echo [4/6] Creando esqueletos de plugins (solo si faltan)...

REM self_check_plugin.py
if not exist "%ROOT_DIR%\plugins\self_check_plugin.py" (
    > "%ROOT_DIR%\plugins\self_check_plugin.py" (
        echo import time
        echo import cv2
        echo import numpy as np
        echo import dxcam
        echo.
        echo class SelfCheckPlugin:
        echo ^    """
        echo ^    Plugin de autodiagnostico. Marca vision_ok y system_checked en SharedState.
        echo ^    Puede usar verificar_vision() u otras rutinas de prueba.
        echo ^    """
        echo.
        echo ^    def setup(self, state, config):
        echo ^        self.last_check = 0.0
        echo.
        echo ^    def process(self, state):
        echo ^        # Por ahora, marcamos system_checked=True la primera vez
        echo ^        if not state.get("system_checked", False):
        echo ^            state["system_checked"] = True
        echo ^        # vision_ok debera ser actualizado por otros modulos (input_handler/vision_core)
        echo ^        return
    )
    echo [OK] self_check_plugin.py creado.
) else (
    echo [SKIP] self_check_plugin.py ya existe.
)

REM window_detector_plugin.py
if not exist "%ROOT_DIR%\plugins\window_detector_plugin.py" (
    > "%ROOT_DIR%\plugins\window_detector_plugin.py" (
        echo import time
        echo try:
        echo ^    import pygetwindow as gw
        echo except ImportError:
        echo ^    gw = None
        echo.
        echo class WindowDetectorPlugin:
        echo ^    """
        echo ^    Detecta la ventana de poker (titulo, rect) y actualiza SharedState["window_rect"]
        echo ^    y SharedState["window_title"].
        echo ^    """
        echo.
        echo ^    def setup(self, state, config):
        echo ^        self.last_scan = 0.0
        echo ^        self.scan_interval = 2.0  # segundos
        echo.
        echo ^    def process(self, state):
        echo ^        if gw is None:
        echo ^            return
        echo ^        now = time.time()
        echo ^        if now - self.last_scan ^< self.scan_interval:
        echo ^            return
        echo ^        self.last_scan = now
        echo.
        echo ^        # TODO: aplicar filtros de titulo, regex, etc.
        echo ^        try:
        echo ^            titles = gw.getAllTitles()
        echo ^        except Exception:
        echo ^            return
        echo.
        echo ^        for t in titles:
        echo ^            if not t:
        echo ^                continue
        echo ^            # Heuristica simple inicial: buscar palabras clave
        echo ^            lower = t.lower()
        echo ^            if "holdem" in lower or "mesa" in lower or "table" in lower:
        echo ^                try:
        echo ^                    w = gw.getWindowsWithTitle(t)[0]
        echo ^                    state["window_title"] = t
        echo ^                    state["window_rect"] = (w.left, w.top, w.width, w.height)
        echo ^                    break
        echo ^                except Exception:
        echo ^                    continue
    )
    echo [OK] window_detector_plugin.py creado.
) else (
    echo [SKIP] window_detector_plugin.py ya existe.
)

REM input_handler.py
if not exist "%ROOT_DIR%\plugins\input_handler.py" (
    > "%ROOT_DIR%\plugins\input_handler.py" (
        echo import time
        echo import dxcam
        echo.
        echo class InputHandlerPlugin:
        echo ^    """
        echo ^    Captura de pantalla usando dxcam.
        echo ^    - Lee capture_method desde config (de momento solo 'dxcam')
        echo ^    - Recorta al rectangulo SharedState["window_rect"] si esta definido
        echo ^    - Actualiza SharedState["frame"] y ["frame_timestamp"]
        echo ^    """
        echo.
        echo ^    def setup(self, state, config):
        echo ^        self.capture_method = config.get("capture_method", "dxcam")
        echo ^        self.camera = None
        echo ^        if self.capture_method == "dxcam":
        echo ^            self.camera = dxcam.create(output_color="BGR")
        echo ^            self.camera.start(target_fps=config.get("fps_active", 30))
        echo.
        echo ^    def process(self, state):
        echo ^        if self.camera is None:
        echo ^            return
        echo ^        frame = self.camera.get_latest_frame()
        echo ^        if frame is None:
        echo ^            return
        echo.
        echo ^        rect = state.get("window_rect")
        echo ^        if rect:
        echo ^            x, y, w, h = rect
        echo ^            h_img, w_img = frame.shape[:2]
        echo ^            x1 = max(0, int(x)); y1 = max(0, int(y))
        echo ^            x2 = min(w_img, x1 + int(w)); y2 = min(h_img, y1 + int(h))
        echo ^            frame = frame[y1:y2, x1:x2]
        echo.
        echo ^        state["frame"] = frame
        echo ^        state["frame_timestamp"] = time.time()
    )
    echo [OK] input_handler.py creado.
) else (
    echo [SKIP] input_handler.py ya existe.
)

REM vision_core.py
if not exist "%ROOT_DIR%\plugins\vision_core.py" (
    > "%ROOT_DIR%\plugins\vision_core.py" (
        echo import math
        echo import time
        echo from ultralytics import YOLO
        echo.
        echo # Zonas exclusivas para 9-max (normalizadas 0..1)
        echo ZONAS_EXCLUSIVAS_9MAX = [
        echo ^    (0.12, 0.65, 0.22, 0.85),
        echo ^    (0.78, 0.65, 0.88, 0.85),
        echo ]
        echo.
        echo class VisionCorePlugin:
        echo ^    """
        echo ^    Ejecuta YOLO sobre el frame actual y llena SharedState["detections"],
        echo ^    detecta hero_active, dealer_pos, table_size, etc.
        echo ^    """
        echo.
        echo ^    def setup(self, state, config):
        echo ^        model_path = config.get("yolo_model_path", "")
        echo ^        if not model_path:
        echo ^            self.model = None
        echo ^            return
        echo ^        try:
        echo ^            self.model = YOLO(model_path, task="detect")
        echo ^        except Exception:
        echo ^            self.model = None
        echo.
        echo ^    def _detectar_formato_mesa(self, puntos, w, h):
        echo ^        for x, y in puntos:
        echo ^            xn, yn = x / w, y / h
        echo ^            for (x1, y1, x2, y2) in ZONAS_EXCLUSIVAS_9MAX:
        echo ^                if x1 ^< xn ^< x2 and y1 ^< yn ^< y2:
        echo ^                    return 9
        echo ^        return 6
        echo.
        echo ^    def process(self, state):
        echo ^        if self.model is None:
        echo ^            return
        echo ^        frame = state.get("frame")
        echo ^        if frame is None:
        echo ^            return
        echo.
        echo ^        h, w = frame.shape[:2]
        echo ^        detections = []
        echo ^        hero_active = False
        echo ^        dealer_pos = None
        echo ^        stack_centers = []
        echo.
        echo ^        results = self.model(frame, stream=True, conf=0.45, iou=0.6)
        echo ^        for r in results:
        echo ^            for box in r.boxes:
        echo ^                cls_id = int(box.cls[0])
        echo ^                label = self.model.names[cls_id]
        echo ^                x1, y1, x2, y2 = box.xyxy[0].tolist()
        echo ^                detections.append({
        echo ^                    "label": label,
        echo ^                    "conf": float(box.conf[0]),
        echo ^                    "box": [x1, y1, x2, y2],
        echo ^                })
        echo ^                cx = (x1 + x2) / 2
        echo ^                cy = (y1 + y2) / 2
        echo ^                if label == "hero_active":
        echo ^                    hero_active = True
        echo ^                elif label == "dealer":
        echo ^                    dealer_pos = (cx, cy)
        echo ^                elif label == "stack_text":
        echo ^                    stack_centers.append((cx, cy))
        echo.
        echo ^        state["detections"] = detections
        echo ^        state["hero_active"] = hero_active
        echo ^        state["dealer_pos"] = dealer_pos
        echo.
        echo ^        if stack_centers:
        echo ^            size = self._detectar_formato_mesa(stack_centers, w, h)
        echo ^            state["table_size"] = size
    )
    echo [OK] vision_core.py creado.
) else (
    echo [SKIP] vision_core.py ya existe.
)

REM advanced_ocr_plugin.py (esqueleto muy básico)
if not exist "%ROOT_DIR%\plugins\advanced_ocr_plugin.py" (
    > "%ROOT_DIR%\plugins\advanced_ocr_plugin.py" (
        echo import numpy as np
        echo import cv2
        echo import re
        echo import easyocr
        echo.
        echo class AdvancedOCRPlugin:
        echo ^    """
        echo ^    Lee valores num^ericos (bote, stacks, apuestas) usando EasyOCR y
        echo ^    smoothing con buffer_ocr. Escribe resultados en state["ocr_data"].
        echo ^    """
        echo.
        echo ^    def setup(self, state, config):
        echo ^        self.reader = easyocr.Reader(['en'], gpu=False)
        echo ^        self.buffer_ocr = {}
        echo.
        echo ^    def _preprocesar_imagen_dinero(self, recorte):
        echo ^        if recorte is None or recorte.size == 0:
        echo ^            return None
        echo ^        h, w = recorte.shape[:2]
        echo ^        img = cv2.resize(recorte, (w*3, h*3), interpolation=cv2.INTER_CUBIC)
        echo ^        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        echo ^        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY ^| cv2.THRESH_OTSU)
        echo ^        if cv2.countNonZero(binary) ^< (binary.size / 2):
        echo ^            binary = cv2.bitwise_not(binary)
        echo ^        binary = cv2.copyMakeBorder(binary, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        echo ^        return binary
        echo.
        echo ^    def _limpiar_texto_dinero(self, texto_crudo):
        echo ^        if not texto_crudo:
        echo ^            return 0.0
        echo ^        texto = texto_crudo.lower().replace(' ', '').replace('o', '0').replace('l', '1')
        echo ^        mult = 1.0
        echo ^        if 'k' in texto:
        echo ^            mult = 1000.0; texto = texto.replace('k', '')
        echo ^        elif 'm' in texto:
        echo ^            mult = 1000000.0; texto = texto.replace('m', '')
        echo ^        match = re.search(r"(\d+(?:[\.,]\d+)?)", texto)
        echo ^        if not match:
        echo ^            return 0.0
        echo ^        num = match.group(1)
        echo ^        if ',' in num and '.' in num:
        echo ^            num = num.replace(',', '')
        echo ^        elif ',' in num:
        echo ^            num = num.replace(',', '.')
        echo ^        try:
        echo ^            return float(num) * mult
        echo ^        except Exception:
        echo ^            return 0.0
        echo.
        echo ^    def _leer_dinero_robusto(self, frame, coords):
        echo ^        x1, y1, x2, y2 = map(int, coords)
        echo ^        h_img, w_img = frame.shape[:2]
        echo ^        x1 = max(0, x1); y1 = max(0, y1)
        echo ^        x2 = min(w_img, x2); y2 = min(h_img, y2)
        echo ^        recorte = frame[y1:y2, x1:x2]
        echo ^        img = self._preprocesar_imagen_dinero(recorte)
        echo ^        if img is None:
        echo ^            return 0.0
        echo ^        res = self.reader.readtext(img, allowlist='0123456789.,$kKmMBb', detail=0)
        echo ^        if not res:
        echo ^            return 0.0
        echo ^        return self._limpiar_texto_dinero(res[0])
        echo.
        echo ^    def process(self, state):
        echo ^        frame = state.get("frame")
        echo ^        detections = state.get("detections", [])
        echo ^        if frame is None or not detections:
        echo ^            return
        echo ^        pot = 0.0
        echo ^        stacks = {}
        echo ^        bets = {}
        echo ^        for det in detections:
        echo ^            label = det.get("label")
        echo ^            box = det.get("box", [])
        echo ^            if not box or label not in ("pot_text", "stack_text", "bet_text"):
        echo ^                continue
        echo ^            raw_val = self._leer_dinero_robusto(frame, box)
        echo ^            x1, y1, x2, y2 = box
        echo ^            obj_id = f"{label}_{int(x1/50)}_{int(y1/50)}"
        echo ^            buf = self.buffer_ocr.setdefault(obj_id, [])
        echo ^            buf.append(raw_val)
        echo ^            if len(buf) ^> 5:
        echo ^                buf.pop(0)
        echo ^            val = float(np.median(buf))
        echo ^            if label == "pot_text":
        echo ^                pot = val
        echo ^        ocr = state.get("ocr_data", {})
        echo ^        ocr["pot"] = pot
        echo ^        ocr["stacks"] = stacks
        echo ^        ocr["bets"] = bets
        echo ^        state["ocr_data"] = ocr
    )
    echo [OK] advanced_ocr_plugin.py creado.
) else (
    echo [SKIP] advanced_ocr_plugin.py ya existe.
)

echo.
echo [5/6] Recuerda copiar/colocar htp.py en %ROOT_DIR% si aún no lo hiciste.
echo         Y tu modelo YOLO OpenVINO en la ruta configurada en config.json.
echo.

REM Crear README básico si no existe
echo [6/6] Creando README.txt basico (si no existe)...

if not exist "%ROOT_DIR%\README.txt" (
    > "%ROOT_DIR%\README.txt" (
        echo HTP - High Tech Player
        echo ======================
        echo.
        echo Estructura creada por instalar.bat.
        echo.
        echo Archivos clave:
        echo - htp.py: orquestador principal (no creado por este script).
        echo - config\config.json: configuracion global.
        echo - plugins\*.py: plugins modulares (input_handler, vision_core, etc.).
        echo.
        echo Para ejecutar:
        echo 1) Asegurate de tener Python 3.x y dependencias instaladas.
        echo 2) Coloca htp.py en C:\HTP.
        echo 3) Ejecuta:  python htp.py
    )
    echo [OK] README.txt creado.
) else (
    echo [SKIP] README.txt ya existe.
)

echo.
echo =========================================
echo   Instalacion de estructura HTP completada
echo   Raiz: %ROOT_DIR%
echo =========================================
echo.
pause
endlocal
