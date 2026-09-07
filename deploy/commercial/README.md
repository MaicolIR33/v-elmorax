# Modelo comercial de Velmorax

## Catálogo vigente

La fuente ejecutable de planes está en `app/services/commercial.py`. La página pública `/planes` y el panel de Administración consumen ese mismo catálogo para evitar diferencias entre lo vendido y lo mostrado.

- **Esencial:** COP 89.000/mes o COP 890.000/año. Hasta 2 sedes y 5 usuarios activos.
- **Clínica:** COP 199.000/mes o COP 1.990.000/año. Hasta 3 sedes y 20 usuarios activos.
- **Hospital y red:** desde COP 549.000/mes. Capacidad, disponibilidad, soporte, migración e integraciones según propuesta y contrato.

Los valores son precios base antes de impuestos y deben validarse comercialmente antes de una campaña pública. Descuentos, permanencia, costos de puesta en marcha y desarrollos especiales solo son válidos cuando figuran en una propuesta aprobada.

## Regla de continuidad clínica

Velmorax nunca bloquea la consulta de información, el registro clínico ni una urgencia por llegar a un límite comercial. Los límites se aplican únicamente al alta de nuevas sedes y usuarios. El administrador ve el consumo de capacidad y recibe una explicación accionable cuando debe desactivar un recurso o ampliar su plan.

## Flujo de venta y activación

1. Clasificar tamaño, sedes, usuarios, horario, urgencias, volumen e integraciones.
2. Entregar propuesta con plan, ciclo, impuestos, migración, soporte y disponibilidad.
3. Registrar en la organización `plan_code`, `plan_status` y `billing_cycle` durante el aprovisionamiento.
4. Verificar capacidad desde Administración antes de entregar accesos.
5. Cualquier excepción se documenta en contrato; no se modifica el catálogo para un solo cliente.

## Estados permitidos

- `active`: operación contratada vigente.
- `trial`: evaluación controlada.
- `past_due`: pago pendiente; se gestiona comercialmente sin interrumpir atención clínica.
- `suspended`: solo después del procedimiento contractual y con exportación/continuidad acordada.

## Revisión trimestral

Comparar conversión, cancelación, costo de soporte, infraestructura por cliente y competidores. Los cambios de precio requieren versión, fecha efectiva y comunicación; nunca deben alterar silenciosamente contratos vigentes.
