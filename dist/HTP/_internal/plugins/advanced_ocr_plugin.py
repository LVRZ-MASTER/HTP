import re
import time
from typing import Any, Dict, Optional, List

try:
    import pygetwindow as gw
except ImportError:
    gw = None

# Opcional: usa el logger principal si existe
try:
    from htp import logger as core_logger  # si htp.py está en el path
except Exception:
    core_logger = None


class WindowDetectorPlugin:
    """
    Plugin encargado de detectar y seguir la ventana de la mesa de póker.

    Estrategia de selección:

    1. Obtener todos los títulos de ventanas.
    2. Filtrar por:
       - NO contener palabras bloqueadas (blocked_window_keywords).
       - Contener al menos una palabra permitida (allowed_window_keywords).
    3. Si hay preferred_window_regex en config:
       - Priorizar títulos que matcheen ese patrón.
       - Loguear cuál fue el título elegido por regex.
    4. Si no hay match con regex, usar el primer título que pase el filtro de keywords.
    5. Mantener cached_title si sigue siendo válido (evita saltos innecesarios).
    """

    def __init__(self) -> None:
        self.last_scan: float = 0.0
        self.scan_interval: float = 2.0  # segundos entre escaneos
        self.cached_title: Optional[str] = None

        self.include_keywords: List[str] = [
            "holdem",
            "mesa",
            "table",
            "poker",
            "ciegas",
            "blinds",
            "green",
            "tournament",
            "freeroll",
        ]
        self.exclude_keywords: List[str] = [
            "lobby",
            "tournament lobby",
            "manager",
            "cashier",
            "login",
            "log in",
            "settings",
        ]

        self.preferred_regex: Optional[re.Pattern] = None
        self.debug_mode: bool = False

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        """
        Lee de config:

        - window_scan_interval
        - allowed_window_keywords
        - blocked_window_keywords
        - preferred_window_regex
        - debug_mode
        """
        interval = config.get("window_scan_interval")
        if isinstance(interval, (int, float)) and interval > 0:
            self.scan_interval = float(interval)

        allowed = config.get("allowed_window_keywords")
        if isinstance(allowed, list) and allowed:
            self.include_keywords = [str(x).lower() for x in allowed]

        blocked = config.get("blocked_window_keywords")
        if isinstance(blocked, list) and blocked:
            self.exclude_keywords = [str(x).lower() for x in blocked]

        regex_str = config.get("preferred_window_regex")
        if isinstance(regex_str, str) and regex_str.strip():
            try:
                self.preferred_regex = re.compile(regex_str)
            except re.error:
                self.preferred_regex = None

        self.debug_mode = bool(config.get("debug_mode", False))

    def _log(self, msg: str) -> None:
        if self.debug_mode:
            if core_logger is not None:
                core_logger.info(f"[WindowDetector] {msg}")
            else:
                print(f"[WindowDetector] {msg}")

    def _es_titulo_candidato(self, title: str) -> bool:
        """Devuelve True si el título pasa filtros de palabras clave."""
        if not title:
            return False

        lower = title.lower()

        if any(bad in lower for bad in self.exclude_keywords):
            return False

        if any(kw in lower for kw in self.include_keywords):
            return True

        return False

    def _obtener_rect_de_titulo(self, title: str):
        """
        Dado un título, intenta devolver (x, y, w, h) de la primera ventana
        que coincida con ese título.
        """
        if gw is None:
            return None

        try:
            wins = gw.getWindowsWithTitle(title)
        except Exception:
            return None

        if not wins:
            return None

        w = wins[0]
        try:
            x, y, ww, hh = w.left, w.top, w.width, w.height
        except Exception:
            return None

        if ww is None or hh is None:
            return None

        return int(x), int(y), int(ww), int(hh)

    def _filtrar_candidatos(self, titles: List[str]) -> List[str]:
        """Aplica filtro de palabras clave a la lista de títulos."""
        return [t for t in titles if t and self._es_titulo_candidato(t)]

    def _priorizar_por_regex(self, candidatos: List[str]) -> Optional[str]:
        """
        Si hay regex preferida, devuelve el primer título que la matchee.
        Loguea cuál fue el ganador si debug_mode está activo.
        """
        if not self.preferred_regex:
            return None

        for t in candidatos:
            try:
                if self.preferred_regex.search(t):
                    self._log(f"Título seleccionado por regex preferido: '{t}'")
                    return t
            except Exception as e:
                self._log(f"Error evaluando regex en título '{t}': {e}")
                continue

        return None

    def _scan_ventanas(self, state: Dict[str, Any]) -> None:
        """
        Escanea todas las ventanas, aplica heurísticas y actualiza:
        - state["window_title"]
        - state["window_rect"]
        """
        if gw is None:
            return

        try:
            titles = gw.getAllTitles()
        except Exception:
            return

        # 1) Si cached_title sigue existiendo y pasa filtros, mantenerlo
        if (
            self.cached_title
            and self.cached_title in titles
            and self._es_titulo_candidato(self.cached_title)
        ):
            rect = self._obtener_rect_de_titulo(self.cached_title)
            if rect is not None:
                x, y, w, h = rect
                state["window_title"] = self.cached_title
                state["window_rect"] = (x, y, w, h)
                return

        # 2) Filtrar títulos de mesa candidatos
        candidatos = self._filtrar_candidatos(titles)
        if not candidatos:
            state["window_title"] = ""
            return

        # 3) Usar regex preferida si está disponible
        best_title = self._priorizar_por_regex(candidatos)
        if not best_title:
            # 4) Si no hay match con regex, usar el primer candidato
            best_title = candidatos[0]
            self._log(f"Título seleccionado por palabras clave: '{best_title}'")

        rect = self._obtener_rect_de_titulo(best_title)
        if rect is None:
            state["window_title"] = ""
            return

        x, y, w, h = rect
        state["window_title"] = best_title
        state["window_rect"] = (x, y, w, h)
        self.cached_title = best_title

    def process(self, state: Dict[str, Any]) -> None:
        now = time.time()
        if now - self.last_scan < self.scan_interval:
            return

        self.last_scan = now
        self._scan_ventanas(state)
