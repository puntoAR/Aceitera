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
});
