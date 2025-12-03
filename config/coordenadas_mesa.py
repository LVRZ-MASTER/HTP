"""
LAYOUTS DE MESAS DE GGPOKER (Coordenadas Normalizadas)

Este archivo define la posición geométrica esperada de los jugadores en los distintos formatos.
Las coordenadas (X, Y) están normalizadas de 0.0 a 1.0 respecto al tamaño de la ventana.
- X=0.0 (Izquierda), X=1.0 (Derecha)
- Y=0.0 (Arriba), Y=1.0 (Abajo)

La posición del HERO siempre se asume fija en el centro inferior.
"""

# Tolerancia para considerar que un jugador está "en" un asiento (radio normalizado)
SEAT_TOLERANCE = 0.12

LAYOUTS = {
    # --- 3-Max: Spin & Gold ---
    # Formato triangular.
    "3-Max": [
        (0.50, 0.68), # S1: Hero (Centro Abajo)
        (0.20, 0.35), # S2: Izquierda Arriba
        (0.80, 0.35), # S3: Derecha Arriba
    ],

    # --- 4-Max: All-In or Fold (AoF) ---
    # Formato cuadrado/diamante.
    "4-Max": [
        (0.50, 0.68), # S1: Hero (Centro Abajo)
        (0.15, 0.45), # S2: Izquierda pura
        (0.50, 0.22), # S3: Centro Arriba (Dealer)
        (0.85, 0.45), # S4: Derecha pura
    ],

    # --- 5-Max: Short Deck (6+) ---
    # Formato pentagonal. Similar al 6-max pero sin el asiento superior central.
    "5-Max": [
        (0.50, 0.68), # S1: Hero
        (0.18, 0.55), # S2: Izquierda Abajo
        (0.18, 0.28), # S3: Izquierda Arriba
        (0.82, 0.28), # S4: Derecha Arriba
        (0.82, 0.55), # S5: Derecha Abajo
    ],

    # --- 6-Max: Cash Games / Rush & Cash ---
    # El formato estándar más común. Hexagonal.
    "6-Max": [
        (0.50, 0.68), # S1: Hero
        (0.28, 0.65), # S2: Izquierda Abajo
        (0.12, 0.45), # S3: Izquierda Medio
        (0.35, 0.25), # S4: Izquierda Arriba
        (0.65, 0.25), # S5: Derecha Arriba
        (0.88, 0.45), # S6: Derecha Medio
        # Nota: A veces S4/S5 están más centrados, pero esta es la config base
    ],

    # --- 8-Max: Torneos (MTTs) ---
    # Estándar de torneos en GG. Ovalado.
    "8-Max": [
        (0.50, 0.68), # S1: Hero
        (0.30, 0.66), # S2: Izquierda Cercana
        (0.15, 0.50), # S3: Izquierda Medio
        (0.15, 0.30), # S4: Izquierda Lejana
        (0.40, 0.22), # S5: Arriba Izquierda
        (0.60, 0.22), # S6: Arriba Derecha
        (0.85, 0.30), # S7: Derecha Lejana
        (0.85, 0.50), # S8: Derecha Medio
        # (El asiento S2 derecho suele faltar respecto al 9-max)
    ],

    # --- 9-Max: Full Ring / Mesas Finales ---
    # Mesa llena ovalada.
    "9-Max": [
        (0.50, 0.68), # S1: Hero
        (0.32, 0.66), # S2: Izquierda Cercana
        (0.16, 0.52), # S3: Izquierda Medio
        (0.14, 0.32), # S4: Izquierda Lejana
        (0.30, 0.22), # S5: Arriba Izquierda
        (0.70, 0.22), # S6: Arriba Derecha
        (0.86, 0.32), # S7: Derecha Lejana
        (0.84, 0.52), # S8: Derecha Medio
        (0.68, 0.66), # S9: Derecha Cercana
    ]
}

def obtener_layout_mas_cercano(puntos_confirmados_norm):
    """
    Determina qué formato de mesa (string) encaja mejor con los puntos detectados.

    Args:
        puntos_confirmados_norm: Lista de tuplas [(x, y), ...] normalizadas (0.0-1.0).
                                 DEBE incluir al Hero si está presente.

    Returns:
        str: Nombre del formato detectado (ej: "6-Max").
    """
    if not puntos_confirmados_norm:
        return "Detectando..."

    # Asegurarnos de tener al Hero como referencia si no está explícito
    # (GG siempre pone al Hero abajo al centro)
    puntos_a_probar = list(puntos_confirmados_norm)
    hero_presente = any(abs(x-0.5) < 0.1 and abs(y-0.68) < 0.1 for x, y in puntos_a_probar)

    if not hero_presente:
        puntos_a_probar.append((0.50, 0.68))

    mejor_formato = "Desconocido"
    menor_error = float('inf')

    for nombre, layout_teorico in LAYOUTS.items():
        error_acumulado = 0.0
        matches = 0

        # Para cada punto detectado, buscamos su asiento más cercano en el layout teórico
        for px, py in puntos_a_probar:
            dist_min = float('inf')
            for lx, ly in layout_teorico:
                # Distancia Euclidiana
                d = ((px - lx)**2 + (py - ly)**2) ** 0.5
                if d < dist_min:
                    dist_min = d

            # Si el punto detectado está razonablemente cerca de un asiento teórico
            if dist_min < SEAT_TOLERANCE:
                error_acumulado += dist_min
                matches += 1

        # Solo consideramos el layout si explica la mayoría de los puntos detectados
        if matches > 0:
            # Cálculo de Score (Menor es mejor):
            # 1. Error de distancia promedio (precisión)
            avg_error = error_acumulado / matches

            # 2. Ratio de cobertura: ¿Qué % de mis puntos detectados encajan en este layout?
            # Si detecto 6 puntos y el layout 3-Max solo explica 3, el ratio es 0.5 (malo).
            cobertura = matches / len(puntos_a_probar)

            # 3. Penalización por exceso de asientos vacíos (Opcional pero útil)
            # Si detecto 3 jugadores y encajan perfecto en 3-Max y 9-Max, prefiero 3-Max.
            exceso_asientos = abs(len(layout_teorico) - len(puntos_a_probar)) * 0.02

            score_final = avg_error + (1.0 - cobertura) * 2.0 + exceso_asientos

            if score_final < menor_error:
                menor_error = score_final
                mejor_formato = nombre

    return mejor_formato
