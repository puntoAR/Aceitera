# Modulo de entrada WSGI para ejecucion en la plataforma serverless Vercel
import sys
# Importa sys para manipular el path de modulos
import os
# Importa os para rutas del sistema operativo

# Agrega el directorio raiz del proyecto al path de busqueda de Python
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa la instancia de la aplicacion Flask desde run.py
from run import app

# Exporta la aplicacion como objeto app para que el runtime de Vercel lo ejecute
app = app

# Exporta tambien como handler para compatibilidad con ejecutores WSGI de Vercel
handler = app
