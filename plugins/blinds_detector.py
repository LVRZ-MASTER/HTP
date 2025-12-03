import re
from typing import Any, Dict, Optional, Tuple

try:
    import pygetwindow as gw
except ImportError:
    gw = None


class BlindsDetectorPlugin:
    """
    Plugin para detectar las ciegas (SB/BB) desde el título de la ventana.

    Responsabilidades:
    - Leer state["window_title"].
    - Aplicar una regex para extraer patrones tipo "$0.50 / $1.00" o "100/200".
    - Actualizar state["game_state"]["blinds"] = {"sb": float, "bb": float}.
    - Si falla la detección, deja los valores actuales sin tocar.
    """

    def __init__(self) -> None:
        # Regex que busca "X / Y" con posibles símbolos de moneda
        self.patron_ciegas = re.compile(
            r"(?:[\$€¥£C]|BB)?\s*(\d+(?:[.,]\d+)?)\s*/\s*(?:[\$€¥£C]|BB)?\s*(\d+(?:[.,]\d+)?)"
        )

        self.lista_negra_titulo = ["Lobby", "Tournament Lobby", "Manager", "Login"]

    def _parsear_blinds(self, titulo: str) -> Optional[Tuple[float, float]]:
        if not titulo:
            return None

        # Evitar algunos títulos obviamente incorrectos
        for palabra in self.lista_negra_titulo:
            if palabra.lower() in titulo.lower():
                return None

        m = self.patron_ciegas.search(titulo)
        if not m:
            return None

        sb_str = m.group(1).replace(",", ".")
        bb_str = m.group(2).replace(",", ".")

        try:
            sb = float(sb_str)
            bb = float(bb_str)
        except ValueError:
            return None

        if bb < sb:
            return None

        return sb, bb

    def process(self, state: Dict[str, Any]) -> None:
        game_state = state.get("game_state", {})
        blinds = game_state.get("blinds", {"sb": 0.0, "bb": 0.0})

        titulo = state.get("window_title", "")
        resultado = self._parsear_blinds(titulo)

        if resultado is None:
            # No sobreescribimos si no podemos detectar nada
            game_state["blinds"] = blinds
            state["game_state"] = game_state
            return

        sb, bb = resultado
        blinds["sb"] = sb
        blinds["bb"] = bb
        game_state["blinds"] = blinds
        state["game_state"] = game_state
