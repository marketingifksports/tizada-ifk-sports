"""
Image Exporter - Renderiza el layout de nesting como JPG con perfil ICC
"""

import os
import io
import math
from typing import List, Tuple, Dict
from PIL import Image, ImageDraw


DPI = 300
MM_POR_PULGADA = 25.4


def mm_to_px(mm: float) -> int:
    return int(round(mm * DPI / MM_POR_PULGADA))


PERFILES_ICC = {
    "Adobe RGB (1998)": "AdobeRGB1998",
    "sRGB": "sRGB IEC61966-2.1",
    "Coated FOGRA39": "CoatedFOGRA39",
}

# Rutas de perfiles ICC en Linux/Railway
RUTAS_PERFILES = [
    "/usr/share/color/icc",
    "/usr/share/color/icc/colord",
    "/usr/share/color/icc/Adobe",
    "/usr/lib/color",
]


def _buscar_perfil_icc(nombre_perfil: str) -> bytes | None:
    """Busca el perfil ICC en el sistema"""
    buscar = nombre_perfil.lower().replace(" ", "").replace("-", "")
    for ruta in RUTAS_PERFILES:
        if not os.path.exists(ruta):
            continue
        for archivo in os.listdir(ruta):
            sin_ext = os.path.splitext(archivo)[0].lower().replace(" ", "").replace("-", "")
            if buscar in sin_ext or sin_ext in buscar:
                ruta_completa = os.path.join(ruta, archivo)
                with open(ruta_completa, "rb") as f:
                    return f.read()
    return None


def _svg_a_imagen_pil(svg_data: str, ancho_px: int, alto_px: int) -> Image.Image:
    """
    Convierte SVG a imagen PIL.
    Intenta usar cairosvg si está disponible, sino renderiza con PIL básico.
    """
    try:
        import cairosvg
        png_bytes = cairosvg.svg2png(
            bytestring=svg_data.encode("utf-8"),
            output_width=ancho_px,
            output_height=alto_px,
        )
        return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    except ImportError:
        pass

    try:
        import subprocess
        # Intentar con inkscape si está disponible
        proc = subprocess.run(
            ["inkscape", "--export-type=png", "--export-width", str(ancho_px),
             "--export-filename=-", "-"],
            input=svg_data.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            return Image.open(io.BytesIO(proc.stdout)).convert("RGBA")
    except Exception:
        pass

    # Fallback: imagen en blanco (el SVG se verá en blanco pero el layout es correcto)
    img = Image.new("RGBA", (ancho_px, alto_px), (255, 255, 255, 255))
    return img


class ImageExporter:
    def __init__(self, dpi: int = 300, perfil_color: str = "sRGB"):
        self.dpi = dpi
        self.perfil_color = perfil_color
        self.icc_data = self._cargar_icc()

    def _cargar_icc(self) -> bytes | None:
        nombre = PERFILES_ICC.get(self.perfil_color, self.perfil_color)
        return _buscar_perfil_icc(nombre)

    def exportar_hoja(
        self,
        hoja: dict,
        ancho_mm: float,
        ruta_salida: str,
    ):
        """Genera el JPG de una hoja del layout"""
        ancho_px = mm_to_px(ancho_mm)
        alto_px = mm_to_px(hoja["alto_mm"])

        # Crear imagen base blanca
        imagen = Image.new("RGB", (ancho_px, alto_px), (255, 255, 255))

        items = hoja.get("items", [])

        for item_data in items:
            svg_data = item_data["item"].get("svg_data", "")
            pos_x_mm = item_data["pos_x"]
            pos_y_mm = item_data["pos_y_hoja"]
            ancho_pieza_mm = item_data["ancho"]
            alto_pieza_mm = item_data["alto"]
            rotado = item_data.get("rotado", False)

            if not svg_data:
                continue

            ancho_pieza_px = mm_to_px(ancho_pieza_mm)
            alto_pieza_px = mm_to_px(alto_pieza_mm)
            pos_x_px = mm_to_px(pos_x_mm)
            pos_y_px = mm_to_px(pos_y_mm)

            if ancho_pieza_px <= 0 or alto_pieza_px <= 0:
                continue

            # Renderizar SVG
            try:
                pieza_img = _svg_a_imagen_pil(svg_data, ancho_pieza_px, alto_pieza_px)

                if rotado:
                    pieza_img = pieza_img.rotate(180)

                # Pegar en la imagen principal
                if pieza_img.mode == "RGBA":
                    fondo = Image.new("RGBA", pieza_img.size, (255, 255, 255, 255))
                    fondo.paste(pieza_img, mask=pieza_img.split()[3])
                    pieza_rgb = fondo.convert("RGB")
                else:
                    pieza_rgb = pieza_img.convert("RGB")

                imagen.paste(pieza_rgb, (pos_x_px, pos_y_px))

            except Exception as e:
                # Si falla el render, dibujar el contorno del molde
                self._dibujar_contorno_fallback(imagen, item_data, pos_x_px, pos_y_px)

        # Guardar con perfil ICC y DPI
        save_kwargs = {
            "dpi": (self.dpi, self.dpi),
            "quality": 95,
            "subsampling": 0,
        }
        if self.icc_data:
            save_kwargs["icc_profile"] = self.icc_data

        imagen.save(ruta_salida, "JPEG", **save_kwargs)

    def _dibujar_contorno_fallback(
        self,
        imagen: Image.Image,
        item_data: dict,
        pos_x_px: int,
        pos_y_px: int,
    ):
        """Dibuja el contorno del molde cuando el SVG no puede renderizarse"""
        contorno_hoja = item_data.get("contorno_hoja", [])
        if len(contorno_hoja) < 3:
            return

        draw = ImageDraw.Draw(imagen)
        pts_px = [(mm_to_px(x), mm_to_px(y)) for x, y in contorno_hoja]
        draw.polygon(pts_px, fill=(240, 240, 240), outline=(0, 0, 0))
        
        # Nombre de la pieza
        nombre = item_data["item"].get("nombre", "")
        talle = item_data["item"].get("talle", "")
        if nombre or talle:
            draw.text((pos_x_px + 10, pos_y_px + 10), f"{nombre} {talle}", fill=(0, 0, 0))
