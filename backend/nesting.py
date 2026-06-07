"""
Nesting Engine - Algoritmo NFP (No-Fit Polygon)
True shape nesting para piezas de sublimación
"""

import math
from typing import List, Tuple, Dict, Optional, Callable


def _translate(pts: List[Tuple], dx: float, dy: float) -> List[Tuple]:
    return [(x + dx, y + dy) for x, y in pts]


def _rotate_180(pts: List[Tuple], cx: float = None, cy: float = None) -> List[Tuple]:
    """Rotación 180° alrededor del centroide"""
    if cx is None or cy is None:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
    return [(2 * cx - x, 2 * cy - y) for x, y in pts]


def _bbox(pts: List[Tuple]) -> Tuple[float, float, float, float]:
    """min_x, min_y, max_x, max_y"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _normalize(pts: List[Tuple]) -> List[Tuple]:
    """Mueve polígono para que empiece en (0,0)"""
    min_x, min_y, _, _ = _bbox(pts)
    return [(x - min_x, y - min_y) for x, y in pts]


def _area(pts: List[Tuple]) -> float:
    n = len(pts)
    if n < 3:
        return 0
    a = 0
    for i in range(n):
        j = (i + 1) % n
        a += pts[i][0] * pts[j][1]
        a -= pts[j][0] * pts[i][1]
    return abs(a) / 2


def _segments_intersect(p1, p2, p3, p4) -> bool:
    """Verifica si el segmento p1-p2 intersecta con p3-p4"""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def _point_in_polygon(point: Tuple, polygon: List[Tuple]) -> bool:
    """Ray casting para punto en polígono"""
    x, y = point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _polygons_overlap(poly_a: List[Tuple], poly_b: List[Tuple], margin: float = 0.1) -> bool:
    """
    Verifica si dos polígonos se solapan.
    Método: SAT simplificado + punto interior.
    """
    # Chequeo rápido de bounding boxes
    ax1, ay1, ax2, ay2 = _bbox(poly_a)
    bx1, by1, bx2, by2 = _bbox(poly_b)

    if ax2 + margin < bx1 or bx2 + margin < ax1:
        return False
    if ay2 + margin < by1 or by2 + margin < ay1:
        return False

    # Si las bboxes no se solapan, no hay solapamiento
    # Si se solapan, hacer check más detallado con algunos puntos
    # (NFP completo es muy costoso, usamos aproximación por muestreo)
    
    # Verificar si algún punto de B está dentro de A
    step = max(1, len(poly_b) // 8)
    for i in range(0, len(poly_b), step):
        if _point_in_polygon(poly_b[i], poly_a):
            return True

    # Verificar si algún punto de A está dentro de B
    step = max(1, len(poly_a) // 8)
    for i in range(0, len(poly_a), step):
        if _point_in_polygon(poly_a[i], poly_b):
            return True

    # Verificar intersección de bordes (muestreado)
    step_a = max(1, len(poly_a) // 12)
    step_b = max(1, len(poly_b) // 12)
    for i in range(0, len(poly_a) - 1, step_a):
        for j in range(0, len(poly_b) - 1, step_b):
            if _segments_intersect(poly_a[i], poly_a[i+1], poly_b[j], poly_b[j+1]):
                return True

    return False


class NestingEngine:
    def __init__(self, ancho_rollo_mm: float = 1600, espacio_mm: float = 7):
        self.ancho_rollo_mm = ancho_rollo_mm
        self.espacio_mm = espacio_mm

    def nest(
        self,
        piezas: List[dict],
        largo_max_mm: float = 3500,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """
        Ejecuta el nesting de todas las piezas.
        
        Algoritmo: Bottom-Left con NFP aproximado + rotación 180°
        
        piezas: [{nombre, talle, cantidad, contorno, ancho_mm, alto_mm}]
        """
        def progress(p, msg):
            if progress_callback:
                progress_callback(p, msg)

        progress(0, "Preparando piezas...")

        # Expandir piezas según cantidad
        items = []
        for p in piezas:
            for n in range(int(p["cantidad"])):
                items.append({
                    "nombre": p["nombre"],
                    "talle": p["talle"],
                    "contorno": _normalize(p["contorno"]),
                    "svg_data": p.get("svg_data", ""),
                    "idx": len(items),
                })

        total_items = len(items)
        if total_items == 0:
            return {"hojas": [], "alto_total_mm": 0, "n_hojas": 0}

        progress(5, f"Ordenando {total_items} piezas...")

        # Ordenar por área descendente (piezas grandes primero)
        items.sort(key=lambda it: _area(it["contorno"]), reverse=True)

        progress(10, "Calculando posiciones...")

        # Bottom-Left Fit con rotación 180°
        placed = []  # [{contorno_colocado, pos_x, pos_y, rotado, item}]
        cursor_y = self.espacio_mm
        cursor_x = self.espacio_mm
        fila_alto = 0

        for idx_item, item in enumerate(items):
            pct = 10 + int(idx_item / total_items * 85)
            progress(pct, f"Colocando pieza {idx_item+1}/{total_items}...")

            contorno_orig = item["contorno"]
            min_x, min_y, max_x, max_y = _bbox(contorno_orig)
            ancho = max_x - min_x
            alto = max_y - min_y

            # Intentar colocar en la posición actual
            colocado = False

            # Primero intentar normal, luego rotado 180°
            for rotado in [False, True]:
                if rotado:
                    contorno_base = _normalize(_rotate_180(contorno_orig))
                    min_x2, min_y2, max_x2, max_y2 = _bbox(contorno_base)
                    ancho_use = max_x2 - min_x2
                    alto_use = max_y2 - min_y2
                else:
                    contorno_base = contorno_orig
                    ancho_use = ancho
                    alto_use = alto

                # Si no entra en el ancho, saltar
                if ancho_use > self.ancho_rollo_mm - 2 * self.espacio_mm:
                    continue

                # Intentar posición actual
                if cursor_x + ancho_use + self.espacio_mm > self.ancho_rollo_mm:
                    # Nueva fila
                    cursor_y += fila_alto + self.espacio_mm
                    cursor_x = self.espacio_mm
                    fila_alto = 0

                # Intentar colocar en (cursor_x, cursor_y)
                contorno_colocado = _translate(contorno_base, cursor_x, cursor_y)

                # Verificar que no se solape con piezas ya colocadas
                ok = True
                for p_prev in placed[-20:]:  # Chequear últimas 20 piezas
                    if _polygons_overlap(
                        contorno_colocado,
                        p_prev["contorno_colocado"],
                        margin=self.espacio_mm * 0.5,
                    ):
                        ok = False
                        break

                if ok:
                    placed.append({
                        "contorno_colocado": contorno_colocado,
                        "pos_x": cursor_x,
                        "pos_y": cursor_y,
                        "ancho": ancho_use,
                        "alto": alto_use,
                        "rotado": rotado,
                        "item": item,
                    })
                    if alto_use > fila_alto:
                        fila_alto = alto_use
                    cursor_x += ancho_use + self.espacio_mm
                    colocado = True
                    break

            if not colocado:
                # Forzar nueva fila y colocar sin verificar solapamiento
                cursor_y += fila_alto + self.espacio_mm
                cursor_x = self.espacio_mm
                fila_alto = 0
                contorno_colocado = _translate(contorno_orig, cursor_x, cursor_y)
                placed.append({
                    "contorno_colocado": contorno_colocado,
                    "pos_x": cursor_x,
                    "pos_y": cursor_y,
                    "ancho": ancho,
                    "alto": alto,
                    "rotado": False,
                    "item": item,
                })
                if alto > fila_alto:
                    fila_alto = alto
                cursor_x += ancho + self.espacio_mm

        # Alto total
        alto_total = cursor_y + fila_alto + self.espacio_mm

        progress(96, "Dividiendo en hojas...")

        # Dividir en hojas de largo_max_mm
        hojas = self._dividir_en_hojas(placed, alto_total, largo_max_mm)

        progress(100, "Nesting completado")

        return {
            "hojas": hojas,
            "alto_total_mm": alto_total,
            "n_hojas": len(hojas),
        }

    def _dividir_en_hojas(
        self,
        placed: List[dict],
        alto_total: float,
        largo_max_mm: float,
    ) -> List[dict]:
        """Divide el layout en hojas de máximo largo_max_mm"""
        hojas = []
        y_inicio = 0
        y_fin = largo_max_mm

        while y_inicio < alto_total:
            hoja_items = []
            for p in placed:
                min_y = p["pos_y"]
                max_y = p["pos_y"] + p["alto"]
                # Incluir si el centro de la pieza está en esta hoja
                cy = (min_y + max_y) / 2
                if y_inicio <= cy < y_fin:
                    hoja_items.append(p)

            if not hoja_items:
                y_inicio = y_fin
                y_fin += largo_max_mm
                continue

            # Calcular alto real de esta hoja
            max_y_hoja = max(p["pos_y"] + p["alto"] for p in hoja_items) + self.espacio_mm
            min_y_hoja = min(p["pos_y"] for p in hoja_items)
            alto_hoja = max_y_hoja - y_inicio

            # Ajustar coordenadas Y relativas a esta hoja
            hoja_items_adj = []
            for p in hoja_items:
                adj = dict(p)
                adj["pos_y_hoja"] = p["pos_y"] - y_inicio
                adj["contorno_hoja"] = [(x, y - y_inicio) for x, y in p["contorno_colocado"]]
                hoja_items_adj.append(adj)

            hojas.append({
                "items": hoja_items_adj,
                "alto_mm": max(alto_hoja, 10),
                "y_inicio_mm": y_inicio,
            })

            y_inicio = y_fin
            y_fin += largo_max_mm

        return hojas if hojas else [{"items": [], "alto_mm": 10, "y_inicio_mm": 0}]
