# Programa de pilotos

Un piloto dura entre 2 y 4 semanas y utiliza una sede, responsables nominados y alcance firmado. No se declara aprobado por percepción: requiere métricas, incidentes cerrados y aceptación del cliente.

## Cohortes mínimas

- Veterinaria pequeña: 1 sede, 2–5 usuarios, operación general.
- Clínica mediana: varias áreas/turnos, inventario y agenda concurrente.
- Hospital o red grande: varias sedes, gobierno de accesos, volumen y continuidad.
- Urgencias: triage, tiempos críticos, entrega de turno y operación fuera de horario.

## Fases

1. Descubrimiento, datos, responsables, consentimiento y criterios de salida.
2. Migración de prueba, capacitación y restauración verificada.
3. Operación paralela controlada; registro diario de tareas, tiempos e incidentes.
4. Simulación de urgencia y de indisponibilidad sin comprometer pacientes reales.
5. Cierre, exportación de evidencia, encuesta y decisión firmada.

## Umbral de aprobación

- Éxito de tareas ≥95%.
- Cero errores críticos abiertos.
- Disponibilidad ≥99,5% durante la ventana medida.
- Satisfacción ≥4/5.
- Capacitación completada ≥90%.

Ejecutar `.venv/bin/python tools/evaluate_pilot.py reporte.json`. El resultado automatizado complementa, pero no reemplaza, el acta firmada ni la revisión de seguridad.

Nunca cargar datos reales sin contrato, autorización, respaldo y procedimiento de salida. Cada hallazgo debe tener severidad, responsable, fecha y evidencia de cierre.
