# Integraciones de Velmorax

Velmorax prepara integraciones mediante una bandeja de salida transaccional (`integration_outbox`). Cada evento lleva una clave idempotente para evitar envíos duplicados. Las credenciales nunca se guardan en el repositorio ni dentro del evento; se suministran como secretos del entorno de producción.

## Orden recomendado

1. Correo transaccional para recuperación y avisos.
2. WhatsApp mediante proveedor oficial, consentimiento y plantillas aprobadas.
3. Facturación electrónica con proveedor habilitado y conciliación fiscal.
4. Laboratorio con catálogo, unidades, identificadores y firma del resultado.
5. Contabilidad enviando solo comprobantes necesarios, nunca historias clínicas completas.

## Contrato técnico obligatorio

- Campos mínimos autorizados, TLS y secretos rotables.
- Clave idempotente, firma de webhooks y protección contra repetición.
- Reintentos con espera creciente, cola de fallos y recuperación manual.
- Registro de estado y referencia externa sin secretos ni notas innecesarias.
- Límites, timeout, degradación controlada y responsable operativo.
- Pruebas en el ambiente del proveedor antes de producción.

Administración diferencia “Configurada” de “No configurada”. Estar en el catálogo no significa que la integración haya sido contratada o certificada.
