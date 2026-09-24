# Script para generar iconos PWA estandar y maskable para dispositivos moviles
from PIL import Image, ImageOps
# Importa modulos de Pillow para manipulacion de imagenes
import os
# Importa os para rutas de archivos

# Define el directorio base de imagenes estaticas
IMG_DIR = os.path.join(os.path.dirname(__file__), 'static', 'images')
# Abre la imagen fuente del logotipo simple transparente
src_path = os.path.join(IMG_DIR, 'logo_simple.png')
# Carga la imagen en modo RGBA
src_img = Image.open(src_path).convert('RGBA')

# Funcion para generar icono con fondo y relleno seguro (safe-zone 80%)
def make_icon(size, bg_color=None, padding_ratio=0.15):
    # Crea lienzo nuevo del tamano solicitado
    if bg_color:
        # Lienzo con color de fondo solido
        canvas = Image.new('RGBA', (size, size), bg_color)
    else:
        # Lienzo transparente
        canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    # Calcula tamano del logo interior respetando la zona segura
    inner_size = int(size * (1.0 - padding_ratio * 2))
    # Redimensiona el logotipo con interpolacion bicubica de alta calidad
    resized_logo = src_img.resize((inner_size, inner_size), Image.Resampling.LANCZOS)
    # Calcula coordenadas de centrado en el lienzo
    offset = ((size - inner_size) // 2, (size - inner_size) // 2)
    # Pega el logotipo centrado usando su propio canal alfa como mascara
    canvas.paste(resized_logo, offset, mask=resized_logo)
    # Retorna la imagen compuesta
    return canvas

# Genera icono estandar transparente de 192x192 px
icon_192 = make_icon(192, bg_color=None, padding_ratio=0.08)
# Guarda el icono de 192 px en disco
icon_192.save(os.path.join(IMG_DIR, 'pwa_icon_192.png'), 'PNG')

# Genera icono estandar transparente de 512x512 px
icon_512 = make_icon(512, bg_color=None, padding_ratio=0.08)
# Guarda el icono de 512 px en disco
icon_512.save(os.path.join(IMG_DIR, 'pwa_icon_512.png'), 'PNG')

# Genera icono maskable para Android con fondo solido azul industrial #0f172a
maskable_192 = make_icon(192, bg_color=(15, 23, 42, 255), padding_ratio=0.18)
# Guarda el icono maskable de 192 px
maskable_192.save(os.path.join(IMG_DIR, 'pwa_icon_maskable_192.png'), 'PNG')

# Genera icono maskable para Android de 512x512 px con fondo solido azul industrial #0f172a
maskable_512 = make_icon(512, bg_color=(15, 23, 42, 255), padding_ratio=0.18)
# Guarda el icono maskable de 512 px
maskable_512.save(os.path.join(IMG_DIR, 'pwa_icon_maskable_512.png'), 'PNG')

# Imprime confirmacion de generacion
print("Iconos PWA generados con éxito en:", IMG_DIR)
