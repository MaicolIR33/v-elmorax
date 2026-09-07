# Migración inicial de clientes

Cada cliente se importa desde una carpeta aislada. Nunca se mezcla información entre organizaciones o sedes.

1. Copiar `deploy/migration/template` fuera del repositorio y completar sus CSV en UTF-8.
2. Ajustar `manifest.json` con los identificadores de organización y sede creados durante el aprovisionamiento.
3. Validar sin escribir: `.venv/bin/python tools/migrate_client_data.py /ruta/cliente`.
4. Corregir todas las filas reportadas y guardar el informe de validación.
5. Crear un respaldo verificado.
6. Importar: `.venv/bin/python tools/migrate_client_data.py /ruta/cliente --apply`.
7. Ejecutar nuevamente en modo validación: los registros ya cargados deben aparecer como duplicados, no volver a insertarse.
8. Revisar muestras de pacientes, citas e insumos con el cliente y firmar aceptación.

La operación es transaccional: un error durante la escritura revierte todo el paquete. `source_system` y `external_id` permiten reintentos sin duplicados. Los archivos reales de clientes contienen datos personales y no deben entrar al repositorio; se transfieren cifrados y se eliminan del área temporal al aprobar la migración.
