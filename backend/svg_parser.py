"""
SVG Parser - Extrae contornos de piezas desde SVGs de Illustrator
Soporta polygon, path, rect como contorno exterior
"""

import re
import math
from typing import List, Tuple, Optional
from lxml import etree


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
    vb = svg_root.get("viewBox", "")
    if vb:
        parts = vb.replace(",", " ").split()
        if len(parts) == 4:
            return tuple(float(p) for p in parts)
    w = svg_root.get("width", "0")
    h = svg_root.get("height", "0")
    def parse_val(v):
        v = str(v).replace("mm", "").replace("px", "").strip()
        try: return float(v)
        except: return 0.0
    return 0.0, 0.0, parse_val(w), parse_val(h)


def _polygon_to_points(points_str: str) -> List[Tuple[float, float]]:
    nums = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", points_str)
    pts = []
    for i in range(0, len(nums) - 1, 2):
        pts.append((float(nums[i]), float(nums[i + 1])))
    return pts


def _path_to_points(d: str, samples: int = 60) -> List[Tuple[float, float]]:
    pts = []
    d = d.strip()
    tokens = re.findall(r"[MmLlHhVvCcQqZz]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", d)
    cx, cy = 0.0, 0.0
    start_x, start_y = 0.0, 0.0
    i = 0
    cmd = "M"

    def pop():
        nonlocal i
        v = float(tokens[i]); i += 1; return v

    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t; i += 1
        else:
            try:
                if cmd == "M":
                    cx, cy = pop(), pop(); start_x, start_y = cx, cy; pts.append((cx, cy)); cmd = "L"
                elif cmd == "m":
                    cx += pop(); cy += pop(); start_x, start_y = cx, cy; pts.append((cx, cy)); cmd = "l"
                elif cmd in ("L", "l"):
                    if cmd == "L": cx, cy = pop(), pop()
                    else: cx += pop(); cy += pop()
                    pts.append((cx, cy))
                elif cmd == "H": cx = pop(); pts.append((cx, cy))
                elif cmd == "h": cx += pop(); pts.append((cx, cy))
                elif cmd == "V": cy = pop(); pts.append((cx, cy))
                elif cmd == "v": cy += pop(); pts.append((cx, cy))
                elif cmd in ("C", "c"):
                    x1, y1 = pop(), pop(); x2, y2 = pop(), pop(); x3, y3 = pop(), pop()
                    if cmd == "c": x1+=cx; y1+=cy; x2+=cx; y2+=cy; x3+=cx; y3+=cy
                    steps = 8
                    for s in range(1, steps+1):
                        tv = s/steps
                        bx = (1-tv)**3*cx + 3*(1-tv)**2*tv*x1 + 3*(1-tv)*tv**2*x2 + tv**3*x3
                        by = (1-tv)**3*cy + 3*(1-tv)**2*tv*y1 + 3*(1-tv)*tv**2*y2 + tv**3*y3
                        pts.append((bx, by))
                    cx, cy = x3, y3
                elif cmd in ("Q", "q"):
                    x1, y1 = pop(), pop(); x2, y2 = pop(), pop()
                    if cmd == "q": x1+=cx; y1+=cy; x2+=cx; y2+=cy
                    steps = 6
                    for s in range(1, steps+1):
                        tv = s/steps
                        bx = (1-tv)**2*cx + 2*(1-tv)*tv*x1 + tv**2*x2
                        by = (1-tv)**2*cy + 2*(1-tv)*tv*y1 + tv**2*y2
                        pts.append((bx, by))
                    cx, cy = x2, y2
                elif cmd in ("Z", "z"):
                    pts.append((start_x, start_y)); cx, cy = start_x, start_y; break
                else:
                    i += 1
            except (IndexError, ValueError):
                break
    return pts


def _bbox(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _area(pts):
    n = len(pts)
    if n < 3: return 0
    a = 0
    for i in range(n):
        j = (i+1) % n
        a += pts[i][0]*pts[j][1] - pts[j][0]*pts[i][1]
    return abs(a)/2


def _detectar_talle_de_texto(svg_content: str) -> Optional[str]:
    for talle in TALLES_CONOCIDOS:
        if re.search(rf'>\s*{re.escape(talle)}\s*<', svg_content, re.IGNORECASE):
            return talle
        if re.search(rf'"[^"]*{re.escape(talle)}[^"]*"', svg_content, re.IGNORECASE):
            return talle
    return None


def _detectar_nombre_de_texto(svg_content: str) -> Optional[str]:
    upper = svg_content.upper()
    for pieza in PIEZAS_CONOCIDAS:
        if pieza in upper:
            return pieza.capitalize()
    return None


def _detectar_desde_filename(filename: str) -> Tuple[Optional[str], Optional[str]]:
    upper = filename.upper().replace("_", " ").replace("-", " ")
    talle = None
    for t in TALLES_CONOCIDOS:
        if re.search(rf'\b{re.escape(t)}\b', upper):
            talle = t; break
    nombre = None
    for p in PIEZAS_CONOCIDAS:
        if p in upper:
            nombre = p.capitalize(); break
    return nombre, talle


class SVGParser:
    def parse(self, svg_bytes: bytes, filename: str = "pieza.svg") -> dict:
        svg_str = svg_bytes.decode("utf-8", errors="replace")

        nombre_fn, talle_fn = _detectar_desde_filename(filename)
        talle_txt = _detectar_talle_de_texto(svg_str)
        nombre_txt = _detectar_nombre_de_texto(svg_str)

        talle = talle_fn or talle_txt or ""
        nombre = nombre_fn or nombre_txt or filename.replace(".svg", "")

        try:
            root = etree.fromstring(svg_bytes)
        except Exception:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(svg_str)

        vb_x, vb_y, vb_w, vb_h = _parsear_viewbox(root)

        # Extraer todos los candidatos a contorno
        candidates = self._extraer_candidatos(root)

        if not candidates:
            contorno_pts = [(0,0),(vb_w,0),(vb_w,vb_h),(0,vb_h)]
        else:
            contorno_pts = self._elegir_contorno(candidates, vb_w, vb_h)

        # Normalizar offset viewBox
        if vb_x or vb_y:
            contorno_pts = [(x - vb_x, y - vb_y) for x, y in contorno_pts]

        # Calcular escala a mm
        # Illustrator: 1 pt = 0.352778 mm (72dpi)
        # Si el SVG tiene atributo width en mm, usar eso
        mm_por_pt = 0.352778
        width_attr = str(root.get("width", ""))

        if "mm" in width_attr:
            try:
                svg_w_mm = float(width_attr.replace("mm", "").strip())
                scale = svg_w_mm / vb_w if vb_w else mm_por_pt
            except:
                scale = mm_por_pt
        elif vb_w > 0:
            # Detectar si las coords son pts (Illustrator) o px
            # Heurística: si vb_w > 5000, probablemente px de alta res
            # Calcular tamaño físico asumiendo 72dpi
            ancho_mm_72dpi = vb_w * mm_por_pt
            if ancho_mm_72dpi > 50 and ancho_mm_72dpi < 3000:
                scale = mm_por_pt
            else:
                # Asumir 96dpi
                scale = 25.4 / 96
        else:
            scale = mm_por_pt

        contorno_mm = [(x * scale, y * scale) for x, y in contorno_pts]

        # Normalizar a (0,0)
        min_x, min_y, max_x, max_y = _bbox(contorno_mm)
        contorno_mm = [(x - min_x, y - min_y) for x, y in contorno_mm]

        ancho_mm = max_x - min_x
        alto_mm = max_y - min_y
        area_mm2 = _area(contorno_mm)

        return {
            "nombre_sugerido": nombre,
            "talle_sugerido": talle,
            "contorno": contorno_mm,
            "ancho_mm": ancho_mm,
            "alto_mm": alto_mm,
            "area_mm2": area_mm2,
            "contorno_ok": len(contorno_pts) > 4 and ancho_mm > 0,
        }

    def _extraer_candidatos(self, root) -> list:
        """Extrae todos los polígonos/paths candidatos con su área y clase"""
        candidates = []

        def iter_shapes(element):
            for child in element:
                tag = child.tag
                if "}" in tag:
                    tag = tag.split("}")[1]

                cls = child.get("class", "")
                fill = child.get("fill", "")

                # Ignorar elementos claramente de arte (texto, clips)
                if tag in ("text", "tspan", "defs", "clipPath", "mask", "symbol"):
                    continue
                # Ignorar paths de clip
                if child.get("clip-path") or "clip" in cls.lower():
                    continue

                if tag == "polygon":
                    pts_str = child.get("points", "")
                    if pts_str:
                        pts = _polygon_to_points(pts_str)
                        if len(pts) > 3:
                            area = _area(pts)
                            candidates.append({
                                "area": area,
                                "pts": pts,
                                "tag": "polygon",
                                "cls": cls,
                                "fill": fill,
                            })
                elif tag == "path":
                    d = child.get("d", "")
                    if d and len(d) > 30:
                        pts = _path_to_points(d)
                        if len(pts) > 3:
                            area = _area(pts)
                            if area > 0:
                                candidates.append({
                                    "area": area,
                                    "pts": pts,
                                    "tag": "path",
                                    "cls": cls,
                                    "fill": fill,
                                })
                elif tag == "rect":
                    try:
                        x = float(child.get("x", 0))
                        y = float(child.get("y", 0))
                        w = float(child.get("width", 0))
                        h = float(child.get("height", 0))
                        if w > 0 and h > 0:
                            pts = [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]
                            candidates.append({
                                "area": w*h, "pts": pts,
                                "tag": "rect", "cls": cls, "fill": fill,
                            })
                    except: pass

                iter_shapes(child)

        iter_shapes(root)
        return sorted(candidates, key=lambda c: c["area"], reverse=True)

    def _elegir_contorno(self, candidates: list, vb_w: float, vb_h: float) -> List[Tuple]:
        """
        Elige el contorno exterior correcto entre los candidatos.
        Estrategia: el polígono más grande que no sea arte interior.
        """
        if not candidates:
            return []

        # El más grande de todos suele ser el contorno exterior o el rect de página
        # El segundo o tercero suele ser el molde
        # Filtrar por fill: sin fill, fill=none, fill=#fff o cls sin arte

        # Primero buscar polygon sin clase (contorno exterior puro)
        for c in candidates[:5]:
            if c["tag"] == "polygon" and not c["cls"] and not c["fill"]:
                if len(c["pts"]) > 4:
                    return c["pts"]

        # Buscar el polygon con fill=white o cls que indique molde
        for c in candidates[:5]:
            cls = c["cls"].lower()
            fill = c["fill"].lower()
            if "cls-1" in cls or "cls-2" in cls:
                if len(c["pts"]) > 4:
                    return c["pts"]
            if fill in ("#fff", "#ffffff", "white"):
                if len(c["pts"]) > 4:
                    return c["pts"]

        # Fallback: el más grande
        for c in candidates:
            if len(c["pts"]) > 4:
                return c["pts"]

        return candidates[0]["pts"]
