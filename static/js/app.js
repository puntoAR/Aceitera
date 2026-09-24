// Archivo JavaScript principal para interactividad responsiva y asistentes de calculo en vivo

// Ejecuta la inicializacion una vez que el DOM esta completamente cargado
document.addEventListener('DOMContentLoaded', () => {
    // 1. Auto-cierre de alertas flash despues de 5 segundos
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.5s ease';
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 500);
        }, 5000);
    });

    // 2. Asistente interactivo en vivo para la pesada de produccion (calculo en tiempo real al tipear)
    const grossInput = document.getElementById('gross_weight_kg');
    const tareInput = document.getElementById('tare_weight_kg');
    const timeInput = document.getElementById('fill_time_seconds');
    const previewSpeed = document.getElementById('preview_speed_kg_h');
    const preview8h = document.getElementById('preview_proj_8h');

    // Si los campos de pesada existen en la pagina actual
    if (grossInput && timeInput && previewSpeed) {
        // Funcion para recalcular velocidad instantanea
        const updateSpeedPreview = () => {
            const gross = parseFloat(grossInput.value) || 0.0;
            const tare = parseFloat(tareInput ? tareInput.value : 0.0) || 0.0;
            const time = parseFloat(timeInput.value) || 0.0;
            const net = Math.max(0.0, gross - tare);

            if (time > 0 && net > 0) {
                const speed = (net / time) * 3600.0;
                const proj8 = speed * 8.0;
                previewSpeed.textContent = speed.toFixed(1) + ' kg/h';
                if (preview8h) {
                    preview8h.textContent = (proj8 / 1000.0).toFixed(2) + ' Tn (8h)';
                }
            } else {
                previewSpeed.textContent = '0.0 kg/h';
                if (preview8h) preview8h.textContent = '0.0 Tn (8h)';
            }
        };

        // Escucha eventos de entrada en los campos numericos
        grossInput.addEventListener('input', updateSpeedPreview);
        if (tareInput) tareInput.addEventListener('input', updateSpeedPreview);
        timeInput.addEventListener('input', updateSpeedPreview);
    }

    // 3. Manejo de instalacion PWA (Progressive Web App) en dispositivos moviles
    let deferredPrompt = null; // Variable para almacenar el evento nativo de instalacion
    const installBanner = document.getElementById('pwa-install-banner'); // Contenedor del banner
    const installBtn = document.getElementById('pwa-install-btn'); // Boton de instalacion
    const closeBtn = document.getElementById('pwa-close-btn'); // Boton de cierre

    // Si los elementos del banner de instalacion existen en la pagina
    if (installBanner && installBtn) {
        // Escucha el evento del navegador cuando la app es elegible para instalacion
        window.addEventListener('beforeinstallprompt', (e) => {
            // Previene el aviso intrusivo por defecto
            e.preventDefault();
            // Guarda el evento para dispararlo al pulsar el boton
            deferredPrompt = e;
            // Si el usuario no descarto el aviso en esta sesion
            if (!sessionStorage.getItem('pwa_dismissed')) {
                // Hace visible el banner flotante
                installBanner.style.display = 'flex';
            }
        });

        // Evento de clic en el boton de instalacion
        installBtn.addEventListener('click', async () => {
            // Si se dispone del evento nativo
            if (deferredPrompt) {
                // Muestra la ventana nativa de instalacion del sistema operativo
                deferredPrompt.prompt();
                // Espera la respuesta del usuario
                const choiceResult = await deferredPrompt.userChoice;
                // Si la instalacion fue confirmada
                if (choiceResult.outcome === 'accepted') {
                    // Oculta el banner
                    installBanner.style.display = 'none';
                }
                // Limpia la referencia al evento
                deferredPrompt = null;
            } else {
                // Mensaje guiado para navegadores o dispositivos iOS
                alert("Para instalar en tu celular:\n1. Toca el menú de tu navegador (3 puntos o botón Compartir ⎋).\n2. Selecciona 'Agregar a la pantalla principal' o 'Instalar aplicación' 📲.");
                // Oculta el banner
                installBanner.style.display = 'none';
            }
        });

        // Evento de cierre manual del banner
        if (closeBtn) {
            // Escucha el clic sobre la cruz
            closeBtn.addEventListener('click', () => {
                // Oculta el contenedor del banner
                installBanner.style.display = 'none';
                // Guarda en la sesion actual que fue descartado
                sessionStorage.setItem('pwa_dismissed', '1');
            });
        }

        // Deteccion de dispositivos Apple iOS
        const isIos = /iphone|ipad|ipod/.test(window.navigator.userAgent.toLowerCase());
        // Verifica si ya se encuentra abierta en modo pantalla completa standalone
        const isStandalone = window.navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches;
        // Si es dispositivo Apple, no esta instalada y no fue descartada
        if (isIos && !isStandalone && !sessionStorage.getItem('pwa_dismissed')) {
            // Despliega el banner con el boton informativo
            installBanner.style.display = 'flex';
        }
    }
});
