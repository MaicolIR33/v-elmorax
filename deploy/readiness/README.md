# Puerta de carga y seguridad

Antes de liberar una versión se ejecutan pruebas unitarias, respaldo/restauración, revisión de configuración y la puerta HTTP:

`.venv/bin/python tools/readiness_gate.py --url https://dominio-real --requests 1000 --concurrency 50`

La puerta exige salud correcta, encabezados de seguridad, rechazo de solicitudes cruzadas, menos de 1% de error y percentil 95 inferior a 1,5 segundos. El resultado debe guardarse con versión, ambiente, hora y responsable.

## Para cadenas y hospitales

- Probar con volumen obtenido de métricas reales y al menos 2 veces el pico esperado.
- Separar lectura, escritura, exportaciones y operaciones concurrentes críticas.
- Ejecutar análisis de dependencias, imágenes y secretos en CI.
- Realizar prueba de penetración independiente anual y después de cambios mayores.
- Verificar autorización por rol, organización y sede; sesiones; recuperación; cargas; inyección; CSRF; XSS; rate limiting; logs y exportaciones.
- Probar pérdida de PostgreSQL, restauración, caída de integraciones y continuidad de urgencias.
- Definir objetivos de disponibilidad, recuperación y pérdida de datos en contrato.

Una ejecución local satisfactoria demuestra el mecanismo, no certifica por sí sola capacidad de producción. El visto bueno para una cadena requiere ambiente equivalente, datos anonimizados, prueba independiente y aceptación de riesgos.
