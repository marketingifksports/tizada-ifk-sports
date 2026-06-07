# Tizada Automática IFK Sports

Sistema de true shape nesting para sublimación deportiva.

## Estructura del proyecto

```
tizada_web/
├── backend/
│   ├── main.py          # API FastAPI
│   ├── svg_parser.py    # Extrae contornos de SVGs de Illustrator
│   ├── nesting.py       # Algoritmo NFP de nesting
│   └── image_exporter.py # Genera JPG con perfil ICC
├── frontend/
│   └── index.html       # Interfaz web completa
├── requirements.txt
├── Procfile
└── railway.toml
```

## Cómo deployar en Railway (paso a paso)

### 1. Crear cuenta en GitHub
- Andá a github.com y creá una cuenta gratuita si no tenés

### 2. Subir el código a GitHub
- En GitHub, hacé clic en "New repository"
- Nombre: `tizada-ikf` (o cualquier nombre)
- Clic en "Create repository"
- Subí todos los archivos de esta carpeta

### 3. Crear cuenta en Railway
- Andá a railway.app
- Registrate con tu cuenta de GitHub (botón "Login with GitHub")

### 4. Crear nuevo proyecto en Railway
- Clic en "New Project"
- Elegí "Deploy from GitHub repo"
- Seleccioná tu repo `tizada-ikf`
- Railway detecta automáticamente el Procfile y deploya

### 5. Acceder a la app
- Railway te da una URL pública (ej: `tizada-ikf.up.railway.app`)
- Compartí esa URL con las diseñadoras

## Uso

1. Subir SVGs exportados desde Illustrator
2. Verificar/editar nombre y talle de cada pieza
3. Ingresar cantidades por pieza
4. Configurar ancho de rollo, largo máximo y perfil de color
5. Clic en "Generar Tizada"
6. Descargar los JPGs resultantes

## Notas técnicas

- El nesting usa algoritmo Bottom-Left + NFP aproximado
- Rotación 180° automática para aprovechar espacio
- Salida a 300 DPI con perfil ICC incrustado
- Hojas automáticas de máximo N metros
- WebSocket para progreso en tiempo real
