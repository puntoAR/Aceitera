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
    # Exporta explicitamente como app para el runtime de Vercel
    app = app
    # Exporta tambien como handler para ejecutores WSGI compatibles
    handler = app
# Captura cualquier falla durante el arranque de la funcion serverless (incluye BaseException)
except BaseException as startup_err:
    # Captura la traza completa del fallo de arranque
    _err_trace = traceback.format_exc()
    # Emite la traza directamente a stderr para los registros de ejecucion de Vercel
    sys.stderr.write(f"\n[CRITICAL STARTUP ERROR] {startup_err}\n{_err_trace}\n")
    # Construye el contenido HTML de contingencia
    emergency_html = f"""<!DOCTYPE html>
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
    # Intenta instanciar una aplicacion Flask valida para @vercel/python
    try:
        # Importa la clase Flask y generador de respuestas
        from flask import Flask, make_response
        # Crea aplicacion Flask de emergencia
        emergency_app = Flask(__name__)
        # Configura ruta universal para atrapar cualquier peticion
        @emergency_app.route('/', defaults={'path': ''})
        @emergency_app.route('/<path:path>')
        def catch_all_emergency(path):
            # Retorna el mensaje de error con codigo HTTP 500
            return make_response(emergency_html, 500, {'Content-Type': 'text/html; charset=utf-8'})
        # Asigna la aplicacion de emergencia como app oficial
        app = emergency_app
        # Asigna tambien a handler
        handler = emergency_app
    # Si Flask tampoco esta disponible recurre a WSGI nativo
    except BaseException:
        # Define funcion WSGI pura de emergencia
        def emergency_handler(environ, start_response):
            # Envia codigo 500
            start_response('500 Internal Server Error', [('Content-Type', 'text/html; charset=utf-8')])
            # Retorna cuerpo en bytes
            return [emergency_html.encode('utf-8')]
        # Asigna handler WSGI
        app = emergency_handler
        # Asigna handler WSGI
        handler = emergency_handler
