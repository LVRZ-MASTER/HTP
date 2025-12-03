import time
import cv2
import os
import math
from typing import Any, Dict, List
from collections import deque, Counter

class TableSizerPlugin:
    def __init__(self):
        # Buffer pequeño para evitar el parpadeo de 1 solo frame (ej: 0.1 segundos)
        self.history_count = deque(maxlen=15)
        self.history_levels = deque(maxlen=15)
        self.last_debug_save = 0

    def setup(self, state: Dict[str, Any], config: Dict[str, Any]) -> None:
        print(">>> TableSizer DIRECTO (YOLO Raw Analysis) Cargado")

    def _contar_niveles_verticales(self, puntos_y: List[float], alto_imagen: int) -> int:
        """
        Cuenta cuántos 'escalones' o niveles de altura únicos existen.
        Agrupa stacks que estén a la misma altura (con un margen de tolerancia).
        """
        if not puntos_y: return 0

        # Ordenamos las alturas de arriba a abajo
        ys = sorted(puntos_y)

        niveles = 0
        ultimo_y = -1.0

        # Tolerancia: 5% de la altura de la pantalla.
        # Si dos stacks están a menos de ese % de distancia vertical, son la misma fila.
        tolerancia = 0.05

        for y in ys:
            if ultimo_y == -1.0:
                niveles = 1
                ultimo_y = y
            else:
                # Si la distancia con el anterior es mayor a la tolerancia, es un NUEVO nivel
                if abs(y - ultimo_y) > tolerancia:
                    niveles += 1
                    ultimo_y = y
                # Si no, es el mismo nivel (ej: jugador izq y der en la misma fila)

        return niveles

    def process(self, state: Dict[str, Any]) -> None:
        frame = state.get("frame")
        detections = state.get("detections", [])

        if frame is None: return
        h, w = frame.shape[:2]

        # --- 1. EXTRAER DATOS CRUDOS DE YOLO ---
        stacks_y = []     # Solo guardamos la altura Y para los escalones
        stacks_centers = [] # Para debug visual

        # Etiquetas válidas según tu modelo
        TARGET_LABELS = ["stack_text", "all_in_symbol"]

        for det in detections:
            label = det.get("label")
            conf = float(det.get("conf", 0))

            # Filtro mínimo de confianza para no comer basura
            if conf < 0.30: continue

            if label in TARGET_LABELS:
                box = det.get("box")
                if box:
                    # Calculamos centro NORMALIZADO (0.0 a 1.0)
                    cx = ((box[0] + box[2]) / 2) / w
                    cy = ((box[1] + box[3]) / 2) / h

                    # Filtro de duplicados en el mismo frame
                    # (A veces YOLO detecta dos veces el mismo objeto muy cerca)
                    es_duplicado = False
                    for (ex_x, ex_y) in stacks_centers:
                        dist = math.hypot(cx - ex_x, cy - ex_y)
                        if dist < 0.05: # Si está pegado a otro (5% dist), es duplicado
                            es_duplicado = True
                            break

                    if not es_duplicado:
                        stacks_centers.append((cx, cy))
                        stacks_y.append(cy)

        # --- 2. ANÁLISIS DE DATOS ---

        # A. Cantidad de Stacks detectados
        count = len(stacks_centers)

        # B. Corrección Hero:
        # Si NO detectamos ningún stack en la zona del Hero (abajo, Y > 0.75),
        # asumimos que el Hero está jugando pero tapado o sin stack visible.
        # ¡Sumamos 1 jugador!
        hero_visible = any(y > 0.75 for y in stacks_y)
        if not hero_visible and count > 0:
            count += 1

        if count < 2: count = 2 # Mínimo siempre 2

        # C. Niveles Verticales ("Escalones")
        niveles = self._contar_niveles_verticales(stacks_y, h)

        # --- 3. ESTABILIZACIÓN (ANTI-PARPADEO) ---
        self.history_count.append(count)
        self.history_levels.append(niveles)

        # Tomamos el valor más común de los últimos frames (Moda)
        final_count = Counter(self.history_count).most_common(1)[0][0]
        final_levels = Counter(self.history_levels).most_common(1)[0][0]

        # --- 4. DETERMINAR FORMATO (LÓGICA DE NEGOCIO) ---

        table_format = "6-Max" # Default

        # REGLA 1: Cantidad bruta
        if final_count > 6:
            table_format = "9-Max"

        # REGLA 2: Estructura de escalones (Tu petición específica)
        # 6-Max suele tener 3 o 4 niveles.
        # 9-Max suele tener 5 niveles.
        elif final_levels >= 5:
            table_format = "9-Max"

        # REGLA 3: Si hay pocos jugadores (ej: 4) pero están en 5 niveles distintos...
        # (Caso raro de mesa 9-max vacía con gente dispersa) -> Mantenemos 9-Max

        # --- 5. ACTUALIZAR ESTADO GLOBAL ---
        gs = state.setdefault("game_state", {})

        # ¡ESTOS SON LOS VALORES OFICIALES!
        gs["active_players"] = final_count
        gs["table_format"] = table_format

        # Exportamos datos crudos por si acaso
        gs["raw_stacks_count"] = count
        gs["raw_levels"] = niveles

        # Debug data
        state["debug"]["table_sizer_seats"] = final_count
        state["debug"]["table_sizer_levels"] = final_levels

        # --- 6. DEBUG VISUAL ---
        if time.time() - self.last_debug_save > 2.0:
            self.last_debug_save = time.time()
            try:
                img = frame.copy()

                # Dibujar puntos detectados
                for (cx, cy) in stacks_centers:
                    px, py = int(cx * w), int(cy * h)
                    cv2.circle(img, (px, py), 10, (0, 255, 0), -1) # Verde sólido
                    # Dibujar linea horizontal para visualizar niveles
                    cv2.line(img, (0, py), (w, py), (0, 255, 0), 1)

                # Texto de Estado
                info = f"JUGADORES: {final_count} | NIVELES: {final_levels} => {table_format}"
                cv2.putText(img, info, (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

                # Guardar
                path = os.path.abspath("debug_table_sizer.jpg")
                cv2.imwrite(path, img)
                print(f"📸 DEBUG: {path} -> {info}")

            except Exception as e:
                print(f"Error debug: {e}")
