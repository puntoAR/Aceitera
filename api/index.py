# Importa sys para manipular el path de modulos
import sys
# Importa os para rutas del sistema operativo
import os
# Importa traceback para inspeccion de errores en arranque serverless
import traceback
# Importa html para escapar mensajes en la vista de emergencia
import html

# Agrega el directorio raiz del proyecto al path de busqueda de Python
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Bloque protegido para inicializar la aplicacion Flask en Vercel
try:
    # Importa la instancia de la aplicacion Flask desde run.py
    from run import app
    # Exporta tambien como handler para compatibilidad con ejecutores WSGI de Vercel
    handler = app
# Captura cualquier falla durante el arranque de la funcion serverless
except Exception as startup_err:
    # Captura la traza completa del fallo de arranque
    _err_trace = traceback.format_exc()
    # Define la aplicacion WSGI de contingencia para reportar el error en pantalla
    def emergency_handler(environ, start_response):
        # Establece el codigo HTTP 500 de error interno
        status = '500 Internal Server Error'
        # Define cabeceras de respuesta en formato HTML UTF-8
        response_headers = [('Content-Type', 'text/html; charset=utf-8')]
        # Notifica las cabeceras al servidor WSGI
        start_response(status, response_headers)
        # Construye la plantilla HTML visual con el detalle tecnico del incidente
        body = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Error de Arranque Serverless - BioBalcarce</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; margin: 0; }}
        .card {{ max-width: 800px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 2rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #334155; }}
        h1 {{ color: #ef4444; font-size: 1.5rem; margin-top: 0; }}
        pre {{ background: #090d16; color: #38bdf8; padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.85rem; border: 1px solid #1e293b; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>⚠️ Falla de Inicialización en Vercel Serverless</h1>
        <p>Ocurrió un error al cargar la aplicación en el entorno serverless:</p>
        <p><strong>{html.escape(str(startup_err))}</strong></p>
        <pre>{html.escape(_err_trace)}</pre>
    </div>
</body>
</html>"""
        # Retorna el cuerpo codificado en bytes
        return [body.encode('utf-8')]
    # Asigna el handler de contingencia como app
    app = emergency_handler
    # Asigna tambien a handler
    handler = emergency_handler
