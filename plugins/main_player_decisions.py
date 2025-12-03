import json
import random
import logging
from typing import Any, Dict, List

# Configuración de Logging
logger = logging.getLogger('HTP.Decisions')

# Intentar importar eval7, manejar la ausencia elegantemente
try:
    import eval7
except ImportError:
    eval7 = None
    logger.warning("⚠️ Librería eval7 no encontrada. El cálculo de equity no funcionará.")

# Mapeo manual de rangos para evitar errores de atributo en eval7
RANK_MAP = {
    12: 'A', 11: 'K', 10: 'Q', 9: 'J', 8: 'T',
    7: '9', 6: '8', 5: '7', 4: '6', 3: '5', 2: '4', 1: '3', 0: '2'
}

class PreflopBrain:
    """
    Cerebro preflop basado en charts externos (preflop_charts.json).
    Maneja la lógica de selección de manos antes de ver el flop.
    """

    def __init__(self, ruta_json: str) -> None:
        self.charts: Dict[str, Any] = {}
        self._cargar_charts(ruta_json)

    def _cargar_charts(self, ruta: str) -> None:
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                self.charts = json.load(f)
        except Exception:
            self.charts = {}

    def _normalizar_mano(self, cards_str: List[str]) -> str:
        """
        Convierte lista de strings ["Ah", "Kd"] -> "AKo".
        """
        if len(cards_str) < 2:
            return ""

        try:
            # Usamos eval7 para parsear correctamente rangos y palos
            if eval7:
                c1 = eval7.Card(cards_str[0])
                c2 = eval7.Card(cards_str[1])
                r1_val = c1.rank
                r2_val = c2.rank

                # Usar mapeo manual para evitar error de atributo
                r1_char = RANK_MAP.get(r1_val, str(r1_val))
                r2_char = RANK_MAP.get(r2_val, str(r2_val))

                # Ordenar para que el rango más alto vaya primero (AK, no KA)
                if r2_val > r1_val:
                    c1, c2 = c2, c1
                    r1_val, r2_val = r2_val, r1_val
                    r1_char, r2_char = r2_char, r1_char

                suited = (c1.suit == c2.suit)

                if r1_val == r2_val:
                    # Pareja (AA, KK)
                    return f"{r1_char}{r2_char}"
                else:
                    # Cartas distintas
                    suffix = 's' if suited else 'o'
                    return f"{r1_char}{r2_char}{suffix}"
            else:
                # Fallback básico si eval7 falla (asume formato rank+suit ej "Ah")
                return f"{cards_str[0]}{cards_str[1]}"
        except Exception as e:
            logger.error(f"Error normalizando mano {cards_str}: {e}")
            return ""

    def obtener_consejo(
        self,
        my_cards_str: List[str],
        pos_hero: str,
        accion_previa: str,
        mesa_tipo: str = "6-Max",
    ) -> str:
        mano = self._normalizar_mano(my_cards_str)
        if not mano:
            return "ESPERANDO..."

        # Intentar buscar charts especificos para el tipo de mesa detectado
        # Si no existe "9-Max" en el JSON, intentamos caer en "6-Max" como default
        charts_mesa = self.charts.get(mesa_tipo)
        if not charts_mesa:
             charts_mesa = self.charts.get("6-Max", {})

        rfi_chart = charts_mesa.get("RFI", {})
        # Intentar obtener rango por posición, default a lista vacía
        rango_pos = rfi_chart.get(pos_hero.upper(), [])

        # Si no hay charts cargados, lógica simple de respaldo
        if not rango_pos:
            # Simple lógica: Jugar parejas y cartas altas
            if len(mano) == 2: # Pareja AA, KK (simplificado)
                 return "RAISE (Par)"
            if "A" in mano or "K" in mano:
                 return "PLAYABLE"
            return "FOLD (No Chart)"

        if accion_previa == "NADIE":
            return "RAISE" if mano in rango_pos else "FOLD"
        else:
            return "CALL" if mano in rango_pos else "FOLD"


class PlayerProfile:
    def __init__(self, name: str, tipo: str = "REGULAR") -> None:
        self.name = name
        self.tipo = tipo


class PostflopBrain:
    """
    Cerebro postflop. Usa eval7 para calcular equity real mediante simulación Monte Carlo.
    """

    def __init__(self) -> None:
        pass

    def calcular_equity(
        self,
        my_cards_str: List[str],
        board_str: List[str],
        iteraciones: int = 600,
    ) -> float:
        """
        Calcula equity vs Rango Aleatorio usando Monte Carlo.
        Funciona tanto para Preflop como Postflop.
        """
        # Chequeo de seguridad básico
        if not eval7:
            return 0.0
        if len(my_cards_str) < 2:
            return 0.0

        try:
            hero_hand = [eval7.Card(x) for x in my_cards_str]
            board_hand = [eval7.Card(x) for x in board_str]
        except Exception as e:
            logger.error(f"Error convirtiendo cartas: {e}")
            return 0.0

        deck = eval7.Deck()
        # Remover cartas conocidas del mazo
        try:
            # Usar set para evitar duplicados al remover
            known_cards = set()
            for c in hero_hand + board_hand:
                c_str = str(c)
                if c_str not in known_cards:
                    deck.cards.remove(c)
                    known_cards.add(c_str)
        except ValueError:
            # Puede ocurrir si hay duplicados por error de detección
            return 0.0

        wins = 0
        ties = 0

        # Simulación Monte Carlo
        for _ in range(iteraciones):
            deck.shuffle()

            # Asumimos rival con mano aleatoria (2 cartas)
            opp_hand = deck.peek(2)

            # Completar el board si faltan cartas (hasta 5)
            remaining_board_count = 5 - len(board_hand)
            draw = deck.peek(2 + remaining_board_count)
            opp_hand = draw[:2]
            community_fill = draw[2:]

            full_board = board_hand + community_fill

            hero_val = eval7.evaluate(hero_hand + full_board)
            opp_val = eval7.evaluate(opp_hand + full_board)

            if hero_val > opp_val:
                wins += 1
            elif hero_val == opp_val:
                ties += 1

        return (wins + ties * 0.5) / iteraciones if iteraciones > 0 else 0.0

    def obtener_consejo(
        self,
        equity: float,
        bote_total: float,
        costo_call: float,
        perfil_rival: str = "REGULAR"
    ) -> Dict[str, str]:

        # 1. Calcular Pot Odds
        bote_final = bote_total + costo_call
        pot_odds = 0.0
        if bote_final > 0:
            pot_odds = costo_call / bote_final

        # 2. Ajuste por Perfil
        margen = 0.0
        if perfil_rival == "DURISIMO":
            margen = 0.05  # Necesito 5% más de equity
        elif perfil_rival == "FLOJO":
            margen = -0.05 # Puedo pagar con 5% menos

        equity_necesaria = pot_odds + margen
        sugerencia = "FOLD"

        if costo_call <= 0:
            sugerencia = "CHECK"
            if equity > 0.60: sugerencia = "BET / VALUE"
        else:
            if equity > equity_necesaria:
                if equity > 0.75:
                    sugerencia = "RAISE / ALL-IN"
                else:
                    sugerencia = "CALL"
            else:
                # Oportunidad de Farol si la equity es baja pero no nula
                if 0.3 < equity < equity_necesaria and costo_call < (bote_total * 0.3):
                     sugerencia = "FOLD (o Bluff)"
                else:
                     sugerencia = "FOLD"

        return {
            "action": sugerencia,
            "pot_odds": f"{pot_odds:.1%}",
            "equity_req": f"{equity_necesaria:.1%}"
        }


class MainPlayerDecisionsPlugin:
    """
    Plugin Orquestador de Decisiones.
    """

    def __init__(self) -> None:
        self.preflop_brain: PreflopBrain | None = None
        self.postflop_brain = PostflopBrain()
        self.player_profiles: Dict[str, PlayerProfile] = {}
        self.active_layout: str = "default_6max_1080p"
        self.layout_conf: Dict[str, Any] = {}

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        ruta_charts = config.get("preflop_charts_path", "config/preflop_charts.json")
        self.preflop_brain = PreflopBrain(ruta_charts)
        self.active_layout = config.get("active_table_layout", "default_6max_1080p")
        self.layout_conf = config.get("table_layouts", {}).get(self.active_layout, {})

    def _inferir_posicion_hero(self, game_state: Dict[str, Any]) -> str:
        dealer_seat = game_state.get("dealer_seat", -1)
        hero_idx = self.layout_conf.get("hero_seat_index", 5)
        if dealer_seat < 0: return "BTN" # Default

        dist = (hero_idx - dealer_seat) % 6
        # Mapeo distancia dealer -> posicion (aproximado para 6-max)
        mapping = {0: "BTN", 1: "SB", 2: "BB", 3: "UTG", 4: "MP", 5: "CO"}
        return mapping.get(dist, "BTN")

    def process(self, state: Dict[str, Any]) -> None:
        """
        Proceso principal: Lee estado del juego y genera decisiones.
        Protegido contra fallos para evitar que la GUI se quede vacía.
        """
        # Si eval7 no está instalado, reportarlo en la GUI
        if not eval7:
            state["decision"] = {
                "action": "ERROR: NO EVAL7",
                "equity": "0%",
                "pot_odds": "N/A",
                "tags": ["Instalar eval7"]
            }
            return

        try:
            game_state = state.get("game_state", {})
            ocr_data = state.get("ocr_data", {})

            # Obtenemos las cartas como strings del estado
            my_cards = game_state.get("my_cards", [])
            board = game_state.get("board", [])

            # Extracción segura de datos OCR (puede venir basura o string vacío)
            try:
                pot = float(ocr_data.get("pot", 0.0))
            except (ValueError, TypeError):
                pot = 0.0

            try:
                costo_call = float(ocr_data.get("call_amount", 0.0))
            except (ValueError, TypeError):
                costo_call = 0.0

            final_decision = {
                "action": "ESPERANDO...",
                "equity": "--%",
                "pot_odds": "--%",
                "tags": []
            }

            # Solo procesar si tenemos cartas propias (Hero está en la mano)
            if len(my_cards) == 2:

                # 1. SIEMPRE CALCULAR EQUITY (Preflop y Postflop)
                equity_val = self.postflop_brain.calcular_equity(my_cards, board)
                final_decision["equity"] = f"{equity_val:.1%}"

                # 2. Lógica de Decisión
                if not board:
                    # --- FASE PREFLOP ---
                    if self.preflop_brain:
                        pos_hero = self._inferir_posicion_hero(game_state)
                        # Detectar si alguien subió antes (simple heurística por bote)
                        accion_previa = "NADIE" if pot < 2.5 else "RAISE"

                        # --- INTEGRACIÓN CON DETECTOR DE MESA ---
                        # Leemos el formato detectado (ej: "9-Max") o usamos 6-Max por defecto
                        table_format = game_state.get("table_format", "6-Max")

                        consejo = self.preflop_brain.obtener_consejo(
                            my_cards, pos_hero, accion_previa, table_format
                        )

                        # Fallback inteligente si no hay chart
                        if consejo == "ESPERANDO..." or "No Chart" in consejo:
                             if equity_val > 0.60: consejo = "RAISE (Premium)"
                             elif equity_val > 0.50: consejo = "PLAYABLE"
                             else: consejo = "FOLD"

                        final_decision["action"] = consejo
                        final_decision["tags"] = [pos_hero, "Preflop", table_format]
                else:
                    # --- FASE POSTFLOP ---
                    perfil_rival = "REGULAR"

                    consejo_dict = self.postflop_brain.obtener_consejo(
                        equity_val, pot, costo_call, perfil_rival
                    )

                    final_decision["action"] = consejo_dict["action"]
                    final_decision["pot_odds"] = consejo_dict["pot_odds"]

                    street_name = game_state.get("street", "Postflop")
                    final_decision["tags"] = [street_name, f"Req:{consejo_dict['equity_req']}"]
            else:
                # Si no tengo cartas (o solo 1 detectada), indicar estado
                if len(my_cards) > 0:
                     final_decision["action"] = "DETECTANDO..."

            state["decision"] = final_decision

        except Exception as e:
            # En caso de error crítico, loguear y notificar GUI para no dejarla colgada
            logger.exception(f"Error en MainPlayerDecisions: {e}")
            state["decision"] = {
                "action": "ERROR INTERNO",
                "equity": "ERR",
                "tags": ["Check Logs"]
            }
