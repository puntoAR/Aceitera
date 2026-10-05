// Service Worker para la Progressive Web App (PWA) de BioBalcarce
const CACHE_NAME = 'biobalcarce-pwa-v1.3.5'; // Identificador unico de version de cache actualizada v1.3.5
const STATIC_ASSETS = [ // Lista de recursos estaticos a pre-cachear
    '/static/css/styles.css', // Hoja de estilos principal del sistema
    '/static/js/app.js', // Logica de interfaz y calculos en vivo
    '/static/images/logo_simple.png', // Logotipo de girasol para barra superior
    '/static/images/logo_full.png', // Logotipo completo institucional
    '/static/images/oil_plant_bg.jpg', // Fondo industrial de planta aceitera
    '/static/images/biobalcarce.ico', // Icono multirresolucion de la planta
    '/static/images/pwa_icon_192.png', // Icono PWA de 192 px para dispositivos moviles
    '/static/images/pwa_icon_512.png', // Icono PWA de 512 px para pantalla de inicio
    '/static/manifest.json' // Manifiesto de aplicacion web para instalacion
]; // Cierre del arreglo de recursos estaticos

// Evento de instalacion del Service Worker
self.addEventListener('install', (event) => { // Escucha el evento install al registrarse
    event.waitUntil( // Extiende el ciclo de instalacion hasta completar el cacheo
        caches.open(CACHE_NAME).then((cache) => { // Abre el almacenamiento de cache nombrado
            return cache.addAll(STATIC_ASSETS); // Descarga y almacena los recursos estaticos base
        }).then(() => { // Al finalizar la carga en cache
            return self.skipWaiting(); // Fuerza la activacion inmediata sin esperar recarga
        }) // Cierre de la promesa encadenada
    ); // Cierre de waitUntil
}); // Cierre de addEventListener install

// Evento de activacion y depuracion de caches antiguos
self.addEventListener('activate', (event) => { // Escucha el evento activate al activarse
    event.waitUntil( // Espera a purgar caches obsoletos
        caches.keys().then((keys) => { // Obtiene todos los nombres de caches existentes
            return Promise.all( // Ejecuta la limpieza de forma paralela
                keys.map((key) => { // Mapea cada clave de cache
                    if (key !== CACHE_NAME) { // Si el cache pertenece a una version anterior
                        return caches.delete(key); // Elimina el cache desactualizado
                    } // Cierre del condicional
                }) // Cierre del mapeo
            ); // Cierre de Promise.all
        }).then(() => { // Una vez eliminados los caches obsoletos
            return self.clients.claim(); // Toma control de todos los clientes abiertos de inmediato
        }) // Cierre del encadenamiento
    ); // Cierre de waitUntil
}); // Cierre de addEventListener activate

// Evento de interceptacion de peticiones de red (Fetch)
self.addEventListener('fetch', (event) => { // Intercepta cada solicitud saliente
    const req = event.request; // Obtiene el objeto de solicitud HTTP
    const url = new URL(req.url); // Parsea la URL solicitada

    // Si la solicitud es para recursos estaticos (CSS, JS, Imagenes, Manifiesto): Network-First con Cache fallback
    if (url.pathname.startsWith('/static/')) { // Comprueba si apunta al directorio static
        event.respondWith(
            fetch(req).then((networkResponse) => { // Prioriza la red para obtener estilos y scripts actualizados
                if (networkResponse && networkResponse.status === 200) { // Si la respuesta de red es exitosa
                    const responseToCache = networkResponse.clone(); // Clona la respuesta antes de consumirla
                    caches.open(CACHE_NAME).then((cache) => { // Abre el cache activo
                        cache.put(req, responseToCache); // Guarda la version mas fresca
                    }); // Cierre de apertura de cache
                } // Cierre de validacion
                return networkResponse; // Retorna el recurso nuevo de la red
            }).catch(() => { // Si no hay internet (offline), recurre al cache local
                return caches.match(req);
            })
        );
        return; // Finaliza la ejecucion para solicitudes estaticas
    } // Cierre del bloque static

    // Para rutas dinamicas de navegacion y datos: estrategia Network-First
    event.respondWith( // Maneja solicitudes de paginas HTML y APIs operativas
        fetch(req).catch(() => { // Intenta primero obtener la respuesta actualizada del servidor
            return caches.match(req); // Si no hay conexion de red, intenta servir desde cache
        }) // Cierre de fallback catch
    ); // Cierre de respondWith dinamico
}); // Cierre de addEventListener fetch
