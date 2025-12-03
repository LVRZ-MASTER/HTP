#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTP - High Tech Player v3.5 (Updated)
Sistema avanzado de análisis visual para poker online
Integración: CameraStream + WindowTracker (Hardware Splitter)
"""

import os
import sys
import json
import time
import random
import threading
import subprocess
import tempfile
import importlib.util
import pkgutil
import inspect
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging
import importlib

# --- NUEVOS IMPORTS PARA HARDWARE ---
try:
    from plugins.camera import CameraStream
    from plugins.track_window import WindowTracker
except ImportError:
    print("⚠️ Error importando plugins de hardware. Asegúrate de que existen 'plugins/camera.py' y 'plugins/track_window.py'")

# -------------------------------------------------------------------
# Configuración básica de logging global
# -------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('htp_system.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('HTP')

# Agregar ruta de plugins al sistema
plugins_path = Path(__file__).parent / 'plugins'
sys.path.insert(0, str(plugins_path))

try:
    import cv2
    import numpy as np
except ImportError:
    logger.warning("⚠️ cv2 o numpy no encontrados. Algunas funciones de visión pueden fallar.")


# -------------------------------------------------------------------
# Utilidad para encontrar la clase Plugin en un módulo
# -------------------------------------------------------------------

def safe_get_plugin_class(module, default_name_suffix: str = "Plugin"):
    """
    Devuelve la primera clase en el módulo cuyo nombre termine en `default_name_suffix`.
    """
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and attr.__name__.endswith(default_name_suffix):
            return attr
    return None


# -------------------------------------------------------------------
# Loader de plugins
# -------------------------------------------------------------------

class PluginLoader:
    """
    Carga los plugins desde la carpeta `plugins/` siguiendo un orden fijo.
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self.plugins_dir = os.path.join(base_dir, "plugins")
        self.plugins: Dict[str, Any] = {}

        # Orden en que se ejecutan en el bucle principal
        self.load_order: List[str] = [
            "self_check_plugin",
            "window_detector_plugin",
            "input_handler",
            # "vision_core",          # DESACTIVADO: La captura ahora la hace el loop principal por Hardware
            "vision_guard_plugin",  # 2. Verifica si es negra/valida y filtra

            "detectar_mesa",        # 3. Detecta tamaño de mesa (TableSizer)

            "card_detector_plugin", # 4. Detecta cartas (lee el tamaño detectado)
            "advanced_ocr_plugin",
            "main_player_decisions",
            "HTPGUI",
            "blinds_detector",
            "errores",
        ]

    def discover_and_load(self) -> Dict[str, Any]:
        """
        Carga y construye instancias de plugins en base al load_order.
        """
        if not os.path.isdir(self.plugins_dir):
            logger.warning(f"⚠️ Carpeta de plugins no encontrada: {self.plugins_dir}")
            return self.plugins

        if self.base_dir not in sys.path:
            sys.path.insert(0, self.base_dir)

        for name in self.load_order:
            module_path = os.path.join(self.plugins_dir, f"{name}.py")
            if not os.path.isfile(module_path):
                # Algunos plugins pueden ser opcionales
                if name not in ["vision_guard_plugin", "detectar_mesa"]:
                    logger.warning(f"⚠️ Plugin no encontrado: {module_path} (se omite)")
                continue

            try:
                module = importlib.import_module(f"plugins.{name}")
                plugin_class = safe_get_plugin_class(module, "Plugin")
                if plugin_class is None:
                    logger.warning(
                        f"⚠️ No se encontró clase *Plugin en plugins.{name}"
                    )
                    continue

                instance = plugin_class()
                self.plugins[name] = instance
                logger.info(
                    f"✅ Plugin activo: {name} -> {plugin_class.__name__}"
                )
            except Exception as e:
                logger.exception(f"❌ Error cargando plugin '{name}': {e}")

        return self.plugins


# -------------------------------------------------------------------
# Orquestador principal
# -------------------------------------------------------------------

class HTPOrchestrator:
    """
    Orquestador principal del motor HTP.
    - Gestiona Hardware (Cámara + Tracker).
    - Ejecuta bucle principal.
    """

    def __init__(self) -> None:
        self.base_dir = os.path.abspath(os.path.dirname(__file__))
        self.config_path = os.path.join(self.base_dir, "config", "config.json")
        self.config: Dict[str, Any] = self._load_config()

        logger.info(f"🧩 Configuración cargada desde {self.config_path}")
        logger.info("🚀 HTP Engine Iniciando...")

        # Estado compartido con bloque de debug completo
        self.state: Dict[str, Any] = self._init_shared_state()

        # --- INICIALIZACIÓN DE HARDWARE ---
        self._init_hardware()

        # Cargar plugins
        logger.info("🔌 Iniciando carga de plugins...")
        self.plugin_loader = PluginLoader(self.base_dir)
        self.plugins = self.plugin_loader.discover_and_load()

        # Inicializar plugins con setup(state, config)
        self._setup_plugins()

        self.running = True

    def _init_hardware(self):
        """Inicializa la cámara dedicada y el tracker de ventanas"""
        # Factores de escala: Monitor 2K (2560x1440) -> Captura (1920x1080)
        # Si usas otra resolución, ajusta estos valores o ponlos en config.json
        MONITOR_W, MONITOR_H = 2560, 1440
        CAPTURE_W, CAPTURE_H = 1920, 1080

        self.scale_x = CAPTURE_W / MONITOR_W
        self.scale_y = CAPTURE_H / MONITOR_H

        logger.info(f"🖥️  Monitor: {MONITOR_W}x{MONITOR_H} -> Captura: {CAPTURE_W}x{CAPTURE_H}")
        logger.info(f"📐 Factor de escala: X={self.scale_x:.2f}, Y={self.scale_y:.2f}")

        # Iniciar Cámara
        try:
            logger.info("🎥 Conectando con CameraStream...")
            self.camera = CameraStream(src=0, width=CAPTURE_W, height=CAPTURE_H).start()
            # Darle un segundo para 'calentar' sensor/hilo
            time.sleep(1.0)
        except Exception as e:
            logger.critical(f"❌ FALLO CAMARA: {e}")
            self.camera = None

        # Iniciar Tracker
        target_name = self.config.get("window_name", "Holdem") # Nombre por defecto
        logger.info(f"🪟 Iniciando WindowTracker buscando: '{target_name}'")
        self.tracker = WindowTracker(target_name)

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.isfile(self.config_path):
            logger.warning(f"⚠️ No se encontró config.json en {self.config_path}, usando defaults.")
            return {}

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        defaults = {
            "fps_idle": 5,
            "fps_active": 30,
            "debug_mode": False,
            "window_name": "Holdem", # Nuevo default
            "save_errors": True,
        }
        for k, v in defaults.items():
            data.setdefault(k, v)

        return data

    # ------------------------------------------------------------------
    # Estado compartido
    # ------------------------------------------------------------------

    def _init_shared_state(self) -> Dict[str, Any]:
        state: Dict[str, Any] = {
            "config": self.config,
            "running": True,
            "frame": None,
            "original_frame": None, # Guardamos el full frame por si acaso
            "detections": [],
            "ocr_data": {},
            "game_state": {},
            "decision": {},
            "vision_ok": False,
            "hero_active": False,
            "fps_current": 0.0,
            "window_title": "",
            "window_rect": None,
            "errors": [],
            "debug": {
                "vision_core_loaded": False, # Legacy
                "vision_last_error": "",
                "input_last_error": "",
                "cards_last_error": "",
                "ocr_last_error": "",
                "last_detection_count": 0,
                "table_sizer_seats": 0,
            },
        }
        return state

    # ------------------------------------------------------------------
    # Plugins
    # ------------------------------------------------------------------

    def _setup_plugins(self) -> None:
        for name, plugin in self.plugins.items():
            try:
                logger.info(f"⚙️ Configurando plugin: {name}...")
                if hasattr(plugin, "setup"):
                    plugin.setup(self.state, self.config)
            except Exception as e:
                logger.error(f"❌ Error en setup de '{name}': {e}")

    # ------------------------------------------------------------------
    # Bucle principal
    # ------------------------------------------------------------------

    def main_loop(self) -> None:
        logger.info("🟢 Bucle principal iniciado")

        fps_idle = float(self.config.get("fps_idle", 5))
        fps_active = float(self.config.get("fps_active", 30))
        debug_mode = bool(self.config.get("debug_mode", False))

        idle_interval = 1.0 / max(fps_idle, 0.1)
        active_interval = 1.0 / max(fps_active, 0.1)

        while self.running and self.state.get("running", True):
            loop_start = time.time()

            # --- 1. CAPTURA Y TRACKING DE HARDWARE ---
            if self.camera:
                raw_frame = self.camera.read()

                if raw_frame is not None:
                    self.state["original_frame"] = raw_frame

                    # Obtener coordenadas de la ventana en escritorio (2K)
                    coords_2k = self.tracker.get_crop_coords()

                    if coords_2k:
                        x, y, w, h = coords_2k

                        # Aplicar factor de escala (2K -> 1080p)
                        sx = int(x * self.scale_x)
                        sy = int(y * self.scale_y)
                        sw = int(w * self.scale_x)
                        sh = int(h * self.scale_y)

                        # Protección de límites
                        h_img, w_img = raw_frame.shape[:2]
                        sx = max(0, min(sx, w_img - 1))
                        sy = max(0, min(sy, h_img - 1))
                        sw = max(1, min(sw, w_img - sx))
                        sh = max(1, min(sh, h_img - sy))

                        # CROP
                        if sw > 10 and sh > 10:
                            self.state["frame"] = raw_frame[sy:sy+sh, sx:sx+sw]
                            self.state["window_rect"] = (sx, sy, sw, sh)
                            self.state["vision_ok"] = True
                        else:
                            self.state["vision_ok"] = False
                    else:
                        # Si no encontramos ventana, usamos frame completo (cuidado espejo infinito)
                        # O podriamos no actualizar el frame para ahorrar CPU
                         self.state["frame"] = raw_frame
                         self.state["vision_ok"] = True
                else:
                    self.state["vision_ok"] = False

            # --- 2. EJECUCIÓN DE PLUGINS ---
            hero_active = bool(self.state.get("hero_active", False))
            interval = active_interval if hero_active else idle_interval

            for name in self.plugin_loader.load_order:
                plugin = self.plugins.get(name)
                if plugin is None:
                    continue

                # Modo idle: saltar plugins pesados
                if not hero_active and name in ("advanced_ocr_plugin", "main_player_decisions"):
                    continue

                try:
                    if hasattr(plugin, "process"):
                        plugin.process(self.state)
                except Exception as e:
                    msg = f"Error en plugin '{name}': {e}"
                    logger.error(msg, exc_info=debug_mode)
                    errs = self.state.get("errors", [])
                    errs.append(msg)
                    self.state["errors"] = errs[-50:]

            # Control de FPS
            elapsed = time.time() - loop_start
            self.state["fps_current"] = 1.0 / elapsed if elapsed > 0 else 0

            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.info("🔴 Bucle principal detenido")
        if self.camera:
            self.camera.stop()

    # ------------------------------------------------------------------
    # Control externo
    # ------------------------------------------------------------------

    def stop(self) -> None:
        self.running = False
        self.state["running"] = False


# -------------------------------------------------------------------
# Punto de entrada
# -------------------------------------------------------------------

def main() -> None:
    orchestrator = HTPOrchestrator()
    try:
        orchestrator.main_loop()
    except KeyboardInterrupt:
        logger.info("⏹ Interrupción por teclado, cerrando...")
        orchestrator.stop()
    except Exception as e:
        logger.exception(f"💥 Error crítico en el motor HTP: {e}")
        orchestrator.stop()


if __name__ == "__main__":
    main()
