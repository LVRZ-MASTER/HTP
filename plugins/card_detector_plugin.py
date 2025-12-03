from typing import Any, Dict, List, Tuple
from collections import deque, Counter
import math
import time
import eval7


CARD_LABELS = {
    "2c", "2d", "2h", "2s",
    "3c", "3d", "3h", "3s",
    "4c", "4d", "4h", "4s",
    "5c", "5d", "5h", "5s",
    "6c", "6d", "6h", "6s",
    "7c", "7d", "7h", "7s",
    "8c", "8d", "8h", "8s",
    "9c", "9d", "9h", "9s",
    "Tc", "Td", "Th", "Ts",
    "Jc", "Jd", "Jh", "Js",
    "Qc", "Qd", "Qh", "Qs",
    "Kc", "Kd", "Kh", "Ks",
    "Ac", "Ad", "Ah", "As",
    "card_back" # IMPORTANTE: Añadido soporte explícito
}

# --- CONFIGURACIÓN DE ESTABILIDAD ---
BUFFER_SIZE = 6
CONFIRMATION_THRESHOLD = 2
MIN_CONFIDENCE_NORMAL = 0.40
MIN_CONFIDENCE_BACK = 0.25 # Umbral más bajo para dorsos difíciles

# --- CONFIGURACIÓN DE ASIENTOS (SEAT REGISTRY) ---
# Distancia horizontal máxima para agrupar cartas en un mismo asiento (12% del ancho)
MIN_SEAT_DISTANCE = 0.12

# Tiempo (segundos) para mantener un asiento CONFIRMADO en memoria aunque no se vea.
# 300 segundos (5 min) garantiza que no perdamos la posición del jugador en toda la mano.
SEAT_CONFIRMED_TIMEOUT = 300.0

# Tiempo (segundos) para borrar un asiento CANDIDATO (ruido) que no se confirmó.
SEAT_CANDIDATE_TIMEOUT = 2.0

# Cuántas veces debe detectarse un asiento para pasar de CANDIDATO a CONFIRMADO
SEAT_CREATION_FRAMES = 8

# --- LAYOUTS OFICIALES DE GGPOKER (Normalizados X, Y) ---
GG_LAYOUTS = {
    "3-Max": [(0.50, 0.68), (0.20, 0.35), (0.80, 0.35)],
    "4-Max": [(0.50, 0.68), (0.15, 0.45), (0.50, 0.25), (0.85, 0.45)],
    "5-Max": [(0.50, 0.68), (0.18, 0.55), (0.18, 0.28), (0.82, 0.28), (0.82, 0.55)],
    "6-Max": [(0.50, 0.68), (0.28, 0.65), (0.12, 0.45), (0.35, 0.25), (0.65, 0.25), (0.88, 0.45), (0.72, 0.65)],
    "8-Max": [(0.50, 0.68), (0.30, 0.66), (0.15, 0.50), (0.15, 0.30), (0.40, 0.22), (0.60, 0.22), (0.85, 0.30), (0.85, 0.50), (0.70, 0.66)],
    "9-Max": [(0.50, 0.68), (0.32, 0.66), (0.16, 0.52), (0.14, 0.32), (0.30, 0.22), (0.70, 0.22), (0.86, 0.32), (0.84, 0.52), (0.68, 0.66)]
}


class Seat:
    """Clase auxiliar para gestionar el estado de un asiento individual."""
    def __init__(self, x: float, y: float):
        self.center_x = x
        self.center_y = y
        self.last_seen_time = time.time()
        self.detection_count = 1
        self.is_confirmed = False  # Solo cuenta como jugador si es True

    def update(self, x: float, y: float):
        # Actualizamos posición con promedio móvil para suavizar
        self.center_x = (self.center_x * 0.9) + (x * 0.1)
        self.center_y = (self.center_y * 0.9) + (y * 0.1)
        self.last_seen_time = time.time()
        self.detection_count += 1

        # Si superamos el umbral, confirmamos que es un asiento real (no ruido)
        if self.detection_count >= SEAT_CREATION_FRAMES:
            self.is_confirmed = True


class CardDetectorPlugin:
    """
    Detector de cartas avanzado con Registro de Asientos Persistente.
    """

    def __init__(self) -> None:
        self.board_y_min = 0.30
        self.board_y_max = 0.60
        self.hero_y_min = 0.65

        self.layout_name: str = "default_6max_1080p"
        self.hero_region: Tuple[float, float, float, float] | None = None
        self.board_row: Dict[str, float] | None = None

        # Historial de detecciones (Buffer visual)
        self.detection_history = deque(maxlen=BUFFER_SIZE)

        # REGISTRO DE ASIENTOS (Memoria de la mesa)
        self.seats: List[Seat] = []

        self.last_hero_seen_time = 0.0
        self.last_street = "PREFLOP"

        # Variable para almacenar el formato detectado (ej: "6-Max")
        self.detected_table_format = "Detectando..."

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        self.layout_name = config.get("active_table_layout", "default_6max_1080p")
        layouts = config.get("table_layouts", {})
        layout = layouts.get(self.layout_name, {})

        hero_region = layout.get("hero_cards_region")
        if isinstance(hero_region, list) and len(hero_region) == 4:
            self.hero_region = tuple(float(x) for x in hero_region)
        else:
            self.hero_region = None

        board_row = layout.get("community_cards_row")
        if isinstance(board_row, dict):
            self.board_row = {
                "y_center": float(board_row.get("y_center", 0.45)),
                "height": float(board_row.get("height", 0.10)),
                "first_x": float(board_row.get("first_x", 0.35)),
                "last_x": float(board_row.get("last_x", 0.65)),
            }
        else:
            self.board_row = None

        fallback = config.get("fallback_thresholds", {})
        if isinstance(fallback, dict):
            try:
                self.board_y_min = float(fallback.get("board_y_min", self.board_y_min))
                self.board_y_max = float(fallback.get("board_y_max", self.board_y_max))
                self.hero_y_min = float(fallback.get("hero_y_min", self.hero_y_min))
            except Exception:
                pass

    def _es_label_carta(self, label: str) -> bool:
        return label in CARD_LABELS or label == "card_back"

    def _convertir_a_card(self, label: str) -> eval7.Card | None:
        try:
            return eval7.Card(label)
        except Exception:
            return None

    def _clasificar_por_layout(self, cx: float, cy: float, ancho: int, alto: int) -> str | None:
        if ancho <= 0 or alto <= 0: return None
        x_norm = cx / float(ancho)
        y_norm = cy / float(alto)

        if self.hero_region is not None:
            hx1, hy1, hx2, hy2 = self.hero_region
            if hx1 <= x_norm <= hx2 and hy1 <= y_norm <= hy2: return "hero"

        if self.board_row is not None:
            y_center = self.board_row["y_center"]
            h = self.board_row["height"]
            by1 = y_center - (h / 1.4)
            by2 = y_center + (h / 1.4)
            bx1 = self.board_row["first_x"]
            bx2 = self.board_row["last_x"]
            if bx1 <= x_norm <= bx2 and by1 <= y_norm <= by2: return "board"

        return None

    def _clasificar_por_fallback(self, cy: float, alto: int) -> str | None:
        if alto <= 0: return None
        y_norm = cy / float(alto)
        if y_norm >= self.hero_y_min: return "hero"
        if self.board_y_min <= y_norm <= self.board_y_max: return "board"
        return None

    def _consolidar_buffer(self) -> Tuple[List[Any], List[Any], List[Any]]:
        """Estabiliza las detecciones crudas usando historial."""
        grid_size = 30
        candidates = {"hero": [], "board": [], "opponent": []}

        for frame_dets in self.detection_history:
            for cx, cy, label, ctype in frame_dets:
                candidates[ctype].append((cx, cy, label))

        final_results = {"hero": [], "board": [], "opponent": []}

        for ctype, items in candidates.items():
            clusters = []
            for cx, cy, label in items:
                found = False
                for cl in clusters:
                    dcx = cl['sum_x'] / cl['count']
                    dcy = cl['sum_y'] / cl['count']
                    if abs(cx - dcx) < grid_size and abs(cy - dcy) < grid_size:
                        cl['labels'].append(label)
                        cl['sum_x'] += cx
                        cl['sum_y'] += cy
                        cl['count'] += 1
                        found = True
                        break
                if not found:
                    clusters.append({'labels': [label], 'sum_x': cx, 'sum_y': cy, 'count': 1})

            for cl in clusters:
                # Mantenemos el umbral general de 2 frames para estabilidad
                if cl['count'] >= CONFIRMATION_THRESHOLD:
                    most_common = Counter(cl['labels']).most_common(1)[0][0]
                    avg_x = cl['sum_x'] / cl['count']
                    avg_y = cl['sum_y'] / cl['count']
                    final_results[ctype].append((avg_x, avg_y, most_common))

        return final_results["hero"], final_results["board"], final_results["opponent"]

    def _agrupar_rivales(self, items: List[Tuple[float, float, str]], ancho: int) -> List[List[str]]:
        """Agrupa cartas visualmente para mostrar en el GUI (pares)."""
        if not items: return []
        items.sort(key=lambda x: x[0])

        grupos = []
        used = [False] * len(items)
        dist_thresh = ancho * 0.18

        for i in range(len(items)):
            if used[i]: continue
            c1 = items[i]
            grupo = [c1]
            used[i] = True

            best_idx = -1
            min_d = float('inf')
            for j in range(i+1, len(items)):
                if used[j]: continue
                c2 = items[j]
                d = math.hypot(c1[0]-c2[0], c1[1]-c2[1])
                if d < dist_thresh and d < min_d:
                    min_d = d
                    best_idx = j

            if best_idx != -1:
                grupo.append(items[best_idx])
                used[best_idx] = True

            # Aceptamos cualquier grupo >= 1 carta
            if len(grupo) >= 1:
                grupo.sort(key=lambda x: x[0])
                cartas = [x[2] for x in grupo]

                # --- FIX: RELLENADO DE PAREJA ("Phantom Card") ---
                # Si solo vemos 1 carta, asumimos que hay otra invisible (o dada vuelta).
                # Duplicamos la que vemos para que la GUI pinte dos cartas.
                if len(cartas) == 1:
                    cartas.append(cartas[0]) # Duplicamos

                grupos.append(cartas)

        return grupos

    def _inferir_formato_geometrico(self, puntos_confirmados: List[Tuple[float, float]]) -> str:
        """
        Compara los puntos (x,y) de los asientos confirmados con los layouts teóricos de GG.
        """
        if not puntos_confirmados:
            return "Detectando..."

        puntos_test = puntos_confirmados.copy()
        hero_present = False
        for px, py in puntos_test:
            if abs(px - 0.5) < 0.1 and abs(py - 0.68) < 0.1:
                hero_present = True
                break
        if not hero_present:
            puntos_test.append((0.50, 0.68))

        mejor_fit = "Custom"
        menor_score = float('inf')

        for nombre, layout in GG_LAYOUTS.items():
            error_layout = 0.0
            matches = 0

            for px, py in puntos_test:
                min_d = min([math.hypot(px-lx, py-ly) for lx, ly in layout])
                if min_d < 0.15:
                    error_layout += min_d
                    matches += 1

            if matches > 0:
                avg_error = error_layout / matches
                unexplained_points_penalty = (len(puntos_test) - matches) * 5.0
                empty_seats_penalty = (len(layout) - matches) * 0.1
                score = avg_error + unexplained_points_penalty + empty_seats_penalty

                if score < menor_score:
                    menor_score = score
                    mejor_fit = nombre

        if menor_score > 3.0:
            return "Detectando..."

        return mejor_fit

    def _gestionar_asientos(self, opp_raw: List[Tuple[float, float, str]], ancho_img: int, alto_img: int) -> int:
        """
        Lógica principal de REGISTRO DE ASIENTOS Y TAMAÑO DE MESA.
        """
        if ancho_img <= 0 or alto_img <= 0: return 0

        # 1. Agrupar detecciones actuales en 'clusters' espaciales
        current_clusters = []
        if opp_raw:
            sorted_items = sorted(opp_raw, key=lambda x: x[0])
            cluster_group = [sorted_items[0]]

            for i in range(1, len(sorted_items)):
                item = sorted_items[i]
                prev = cluster_group[-1]
                if abs(item[0] - prev[0]) < (ancho_img * MIN_SEAT_DISTANCE):
                    cluster_group.append(item)
                else:
                    avg_x = sum(c[0] for c in cluster_group) / len(cluster_group)
                    avg_y = sum(c[1] for c in cluster_group) / len(cluster_group)
                    current_clusters.append((avg_x, avg_y))
                    cluster_group = [item]

            if cluster_group:
                avg_x = sum(c[0] for c in cluster_group) / len(cluster_group)
                avg_y = sum(c[1] for c in cluster_group) / len(cluster_group)
                current_clusters.append((avg_x, avg_y))

        # 2. Asignar Clusters a Asientos (Matching)
        now = time.time()
        norm_thresh_x = ancho_img * 0.15

        for (cx, cy) in current_clusters:
            matched_seat = None
            min_dist = float('inf')

            for seat in self.seats:
                dx = abs(seat.center_x - cx)
                dy = abs(seat.center_y - cy)
                if dx < norm_thresh_x and dy < (ancho_img * 0.2):
                    if dx < min_dist:
                        min_dist = dx
                        matched_seat = seat

            if matched_seat:
                matched_seat.update(cx, cy)
            else:
                new_seat = Seat(cx, cy)
                self.seats.append(new_seat)

        # 3. Limpieza Inteligente (Garbage Collection)
        active_seats_list = []
        puntos_geom = []

        for s in self.seats:
            age = now - s.last_seen_time

            if s.is_confirmed:
                if age < SEAT_CONFIRMED_TIMEOUT:
                    active_seats_list.append(s)
                    puntos_geom.append((s.center_x / float(ancho_img), s.center_y / float(alto_img)))
            else:
                if age < SEAT_CANDIDATE_TIMEOUT:
                    active_seats_list.append(s)

        self.seats = active_seats_list

        # 4. Determinar Formato de Mesa
        self.detected_table_format = self._inferir_formato_geometrico(puntos_geom)

        return sum(1 for s in self.seats if s.is_confirmed)

    def process(self, state: Dict[str, Any]) -> None:
        frame = state.get("frame")
        detections = state.get("detections", [])
        debug = state.setdefault("debug", {})
        gs = state.setdefault("game_state", {})

        if frame is None: return
        alto_img, ancho_img = frame.shape[:2]

        # 1. Recolectar
        frame_items = []
        if detections:
            for det in detections:
                conf = float(det.get("conf", det.get("confidence", 0.0)))
                label = det.get("label")

                # --- FIX: SENSIBILIDAD CARD_BACK ---
                min_conf = MIN_CONFIDENCE_BACK if label == "card_back" else MIN_CONFIDENCE_NORMAL

                if conf < min_conf: continue

                box = det.get("box")
                if not isinstance(label, str) or not isinstance(box, (list, tuple)) or len(box) != 4: continue
                if not self._es_label_carta(label): continue

                x1, y1, x2, y2 = box
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0

                clasif = self._clasificar_por_layout(cx, cy, ancho_img, alto_img)
                if clasif is None: clasif = self._clasificar_por_fallback(cy, alto_img)
                ctype = clasif if clasif else "opponent"
                frame_items.append((cx, cy, label, ctype))

        # 2. Buffer
        self.detection_history.append(frame_items)

        # 3. Consolidar
        hero_raw, board_raw, opp_raw = self._consolidar_buffer()

        # 4. Post-Procesado visual
        hero_raw.sort(key=lambda x: x[0])
        # Hero y Board no pueden tener 'card_back'
        hero_valid = [x for x in hero_raw if x[2] != "card_back"]
        if len(hero_valid) > 2: hero_valid = hero_valid[:2]

        board_raw.sort(key=lambda x: x[0])
        board_valid = [x for x in board_raw if x[2] != "card_back"]
        if len(board_valid) > 5: board_valid = board_valid[:5]

        # Oponentes: Sí aceptamos card_back y aplicamos agrupación con relleno
        opponents_grouped = self._agrupar_rivales(opp_raw, ancho_img)

        # 5. Actualizar Estado GUI
        my_cards_str = [x[2] for x in hero_valid]
        board_str = [x[2] for x in board_valid]

        gs["my_cards"] = my_cards_str
        gs["board"] = board_str
        gs["opponents_cards"] = opponents_grouped

        # --- STICKY HERO ---
        if len(my_cards_str) >= 2:
            self.last_hero_seen_time = time.time()
            state["hero_active"] = True
        elif (time.time() - self.last_hero_seen_time) < 3.0:
            state["hero_active"] = True

        # --- CALLE ---
        nb = len(board_str)
        if nb == 0: gs["street"] = "PREFLOP"
        elif nb == 3: gs["street"] = "FLOP"
        elif nb == 4: gs["street"] = "TURN"
        elif nb == 5: gs["street"] = "RIVER"
        else: gs["street"] = gs.get("street", "PREFLOP")

        # --- FIX: JUGADORES EN MANO (Players In Hand) ---
        # Calculamos cuántos rivales tienen cartas visibles + Hero
        players_in_hand = len(opponents_grouped)
        if len(my_cards_str) > 0:
            players_in_hand += 1

        if players_in_hand < 2 and nb > 0:
             players_in_hand = 2

        gs["players_in_hand"] = players_in_hand

        # --- CONTEO DE MESA (Active Players) ---
        # Usamos la lógica de Seat Registry para la mesa general
        confirmed_opponents_seats = self._gestionar_asientos(opp_raw, ancho_img, alto_img)
        seats_active = confirmed_opponents_seats
        if len(my_cards_str) > 0: seats_active += 1

        # Merge con TableSizer (Stacks)
        stack_count = gs.get("active_players", 0)
        final_active = max(stack_count, seats_active)

        # Consistencia
        if players_in_hand > final_active:
            final_active = players_in_hand

        if final_active < 2: final_active = 2

        gs["active_players"] = final_active

        if self.detected_table_format != "Detectando...":
            gs["table_format"] = self.detected_table_format

        state["game_state"] = gs

        # Debug
        debug["last_my_cards"] = my_cards_str
        debug["last_board_cards"] = board_str
        debug["confirmed_seats"] = confirmed_opponents_seats
        debug["total_seats_tracked"] = len(self.seats)
        debug["table_fmt_geo"] = self.detected_table_format
        debug["players_in_hand_calc"] = players_in_hand
