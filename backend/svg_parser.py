"""
SVG Parser - Extrae contornos de piezas desde SVGs de Illustrator
Soporta polygon, path, rect como contorno exterior
"""

import re
import math
from typing import List, Tuple, Optional
from lxml import etree
import xml.etree.ElementTree as ET


TALLES_CONOCIDOS = [
    "5XL", "4XL", "3XL", "2XL", "XL", "XXL", "XXXL", "XXXXL", "XXXXXL",
    "XS", "S", "M", "L",
    "T16", "T14", "T12", "T10", "T8", "T6",
    "16", "14", "12", "10", "8", "6",
]

PIEZAS_CONOCIDAS = [
    "FRENTE", "ESPALDA", "MANGA", "CUELLO", "BOLSILLO",
    "DELANTERO", "TRASERO", "PUÑO", "PRETINA",
    "IZQ", "DER", "IZQUIERDA", "DERECHA",
]


def _parsear_viewbox(svg_root) -> Tuple[float, float, float, float]:
    """Retorna (min_x, min_y, width, height) del viewBox"""
    vb = svg_root.get("viewBox", "")
    if vb:
        parts = vb.replace(",", " ").split()
        if len(parts) == 4:
            return tuple(float(p) for p in parts)

    w = svg_root.get("width", "0")
    h = svg_root.get("height", "0")

    def parse_val(v):
        v = str(v).replace("mm", "").replace("px", "").strip()
        try:
            return float(v)
        except:
            return 0.0

    return 0.0, 0.0, parse_val(w), parse_val(h)


def _polygon_to_points(points_str: str) -> List[Tuple[float, float]]:
    """Convierte string de puntos de <polygon> a lista de (x,y)"""
    nums = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", points_str)
    pts = []
    for i in range(0, len(nums) - 1, 2):
        pts.append((float(nums[i]), float(nums[i + 1])))
    return pts


def _path_to_points(d: str, samples: int = 100) -> List[Tuple[float, float]]:
    """
    Convierte path SVG a lista de puntos discretizados.
    Soporta M, L, H, V, Z y curves (C, Q) con muestreo.
    """
    pts = []
    d = d.strip()
    # Tokenizar
    tokens = re.findall(r"[MmLlHhVvCcQqZz]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", d)

    cx, cy = 0.0, 0.0
    start_x, start_y = 0.0, 0.0
    i = 0
    cmd = "M"

    def pop():
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            i += 1
        else:
            if cmd == "M":
                cx, cy = pop(), pop()
                start_x, start_y = cx, cy
                pts.append((cx, cy))
                cmd = "L"
            elif cmd == "m":
                cx += pop()
                cy += pop()
                start_x, start_y = cx, cy
                pts.append((cx, cy))
                cmd = "l"
            elif cmd in ("L", "l"):
                if cmd == "L":
                    cx, cy = pop(), pop()
                else:
                    cx += pop()
                    cy += pop()
                pts.append((cx, cy))
            elif cmd == "H":
                cx = pop()
                pts.append((cx, cy))
            elif cmd == "h":
                cx += pop()
                pts.append((cx, cy))
            elif cmd == "V":
                cy = pop()
                pts.append((cx, cy))
            elif cmd == "v":
                cy += pop()
                pts.append((cx, cy))
            elif cmd in ("C", "c"):
                x1, y1 = pop(), pop()
                x2, y2 = pop(), pop()
                x3, y3 = pop(), pop()
                if cmd == "c":
                    x1 += cx; y1 += cy
                    x2 += cx; y2 += cy
                    x3 += cx; y3 += cy
                # Samplear curva Bezier cúbica
                steps = max(10, samples // 10)
                for s in range(1, steps + 1):
                    t_v = s / steps
                    bx = (1-t_v)**3*cx + 3*(1-t_v)**2*t_v*x1 + 3*(1-t_v)*t_v**2*x2 + t_v**3*x3
                    by = (1-t_v)**3*cy + 3*(1-t_v)**2*t_v*y1 + 3*(1-t_v)*t_v**2*y2 + t_v**3*y3
                    pts.append((bx, by))
                cx, cy = x3, y3
            elif cmd in ("Q", "q"):
                x1, y1 = pop(), pop()
                x2, y2 = pop(), pop()
                if cmd == "q":
                    x1 += cx; y1 += cy
                    x2 += cx; y2 += cy
                steps = max(8, samples // 12)
                for s in range(1, steps + 1):
                    t_v = s / steps
                    bx = (1-t_v)**2*cx + 2*(1-t_v)*t_v*x1 + t_v**2*x2
                    by = (1-t_v)**2*cy + 2*(1-t_v)*t_v*y1 + t_v**2*y2
                    pts.append((bx, by))
                cx, cy = x2, y2
            elif cmd in ("Z", "z"):
                pts.append((start_x, start_y))
                cx, cy = start_x, start_y
                i += 1 if i < len(tokens) and tokens[i] in ("Z", "z") else 0
                break
            else:
                i += 1

    return pts


def _bbox(pts: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Retorna (min_x, min_y, max_x, max_y)"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _area_poligono(pts: List[Tuple[float, float]]) -> float:
    """Área por fórmula del zapato (Shoelace)"""
    n = len(pts)
    if n < 3:
        return 0
    area = 0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2


def _detectar_talle_de_texto(svg_content: str) -> Optional[str]:
    """Busca texto de talle en el SVG"""
    for talle in TALLES_CONOCIDOS:
        # Buscar como texto en el SVG
        if re.search(rf'>\s*{re.escape(talle)}\s*<', svg_content, re.IGNORECASE):
            return talle
        if re.search(rf'"[^"]*{re.escape(talle)}[^"]*"', svg_content, re.IGNORECASE):
            return talle
    return None


def _detectar_nombre_de_texto(svg_content: str) -> Optional[str]:
    """Busca nombre de pieza en el SVG"""
    upper = svg_content.upper()
    for pieza in PIEZAS_CONOCIDAS:
        if pieza in upper:
            return pieza.capitalize()
    return None


def _detectar_desde_filename(filename: str) -> Tuple[Optional[str], Optional[str]]:
    """Detecta nombre y talle desde el nombre del archivo"""
    upper = filename.upper().replace("_", " ").replace("-", " ")
    
    talle = None
    for t in TALLES_CONOCIDOS:
        if re.search(rf'\b{re.escape(t)}\b', upper):
            talle = t
            break

    nombre = None
    for p in PIEZAS_CONOCIDAS:
        if p in upper:
            nombre = p.capitalize()
            break

    return nombre, talle


class SVGParser:
    def parse(self, svg_bytes: bytes, filename: str = "pieza.svg") -> dict:
        """
        Parsea un SVG y extrae:
        - contorno exterior (lista de puntos en mm)
        - dimensiones en mm
        - nombre y talle sugeridos
        """
        svg_str = svg_bytes.decode("utf-8", errors="replace")

        # Detectar talle y nombre
        nombre_fn, talle_fn = _detectar_desde_filename(filename)
        talle_txt = _detectar_talle_de_texto(svg_str)
        nombre_txt = _detectar_nombre_de_texto(svg_str)

        talle = talle_fn or talle_txt or ""
        nombre = nombre_fn or nombre_txt or filename.replace(".svg", "")

        # Parsear SVG
        try:
            root = etree.fromstring(svg_bytes)
        except Exception:
            root = ET.fromstring(svg_str)

        ns = {"svg": "http://www.w3.org/2000/svg"}
        vb_x, vb_y, vb_w, vb_h = _parsear_viewbox(root)

        # Buscar el contorno más grande (el molde exterior)
        contorno_pts = self._extraer_contorno_exterior(root, svg_str)

        if not contorno_pts:
            # Fallback: usar viewBox como rectángulo
            contorno_pts = [
                (0, 0), (vb_w, 0), (vb_w, vb_h), (0, vb_h)
            ]

        # Normalizar: restar offset del viewBox
        if vb_x or vb_y:
            contorno_pts = [(x - vb_x, y - vb_y) for x, y in contorno_pts]

        # Convertir de unidades SVG a mm
        # Illustrator exporta a 72dpi por defecto: 1 pt = 0.352778 mm
        # pero con viewBox en pts, 1 unidad SVG = 1 pt
        mm_por_pt = 0.352778
        
        # Detectar si las unidades son pixels (96dpi) o points (72dpi)
        width_attr = str(root.get("width", ""))
        if "mm" in width_attr:
            # SVG ya está en mm
            try:
                svg_w_mm = float(width_attr.replace("mm", "").strip())
                scale = svg_w_mm / vb_w if vb_w else mm_por_pt
            except:
                scale = mm_por_pt
        elif "px" in width_attr:
            px_w = float(width_attr.replace("px", "").strip())
            svg_w_mm = px_w * 25.4 / 96
            scale = svg_w_mm / vb_w if vb_w else 25.4 / 96
        else:
            scale = mm_por_pt

        contorno_mm = [(x * scale, y * scale) for x, y in contorno_pts]

        # Calcular bbox
        min_x, min_y, max_x, max_y = _bbox(contorno_mm)
        
        # Normalizar para que empiece en (0,0)
        contorno_mm = [(x - min_x, y - min_y) for x, y in contorno_mm]

        ancho_mm = max_x - min_x
        alto_mm = max_y - min_y
        area_mm2 = _area_poligono(contorno_mm)

        return {
            "nombre_sugerido": nombre,
            "talle_sugerido": talle,
            "contorno": contorno_mm,
            "ancho_mm": ancho_mm,
            "alto_mm": alto_mm,
            "area_mm2": area_mm2,
            "contorno_ok": len(contorno_pts) > 4,
        }

    def _extraer_contorno_exterior(self, root, svg_str: str) -> List[Tuple[float, float]]:
        """
        Encuentra el polígono/path más grande del SVG (= molde exterior)
        Excluye elementos de arte interior
        """
        candidates = []

        # Buscar todos los elementos con xmlns
        ns = "http://www.w3.org/2000/svg"
        
        def iter_shapes(element):
            for child in element:
                tag = child.tag
                if "}" in tag:
                    tag = tag.split("}")[1]
                
                # Ignorar elementos de texto y grupos de arte
                cls = child.get("class", "")
                if "cls-2" in cls or "cls-3" in cls or "cls-4" in cls:
                    # Estos son elementos de arte interior en Illustrator
                    # cls-1 = blanco, cls-2 = color primario, cls-3/4 = texto
                    pass
                elif tag == "polygon":
                    pts = child.get("points", "")
                    if pts:
                        points = _polygon_to_points(pts)
                        if len(points) > 3:
                            area = _area_poligono(points)
                            candidates.append((area, points, "polygon", cls))
                elif tag == "path":
                    d = child.get("d", "")
                    if d and len(d) > 20:
                        pts = _path_to_points(d)
                        if len(pts) > 3:
                            area = _area_poligono(pts)
                            candidates.append((area, pts, "path", cls))
                elif tag == "rect":
                    x = float(child.get("x", 0))
                    y = float(child.get("y", 0))
                    w = float(child.get("width", 0))
                    h = float(child.get("height", 0))
                    if w > 0 and h > 0:
                        pts = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]
                        candidates.append((w * h, pts, "rect", cls))

                # Recursivo
                iter_shapes(child)

        iter_shapes(root)

        if not candidates:
            return []

        # Ordenar por área descendente
        candidates.sort(key=lambda c: c[0], reverse=True)

        # El molde exterior es normalmente:
        # 1. cls-1 (blanco) = interior blanco del molde
        # 2. el polígono más grande sin clase (el contorno)
        # Preferimos el elemento más grande que NO sea cls-2 (arte)
        
        # Buscar el elemento cls-1 (interior blanco) - es el segundo más grande típicamente
        # O el polygon sin clase más grande
        
        for area, pts, tipo, cls in candidates:
            if "cls-1" in cls or cls == "":
                # Este es probablemente el molde
                if len(pts) > 4:
                    return pts

        # Fallback: el más grande de todos
        return candidates[0][1]
