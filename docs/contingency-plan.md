# Plan de contingencia de Velmorax

## 1 Objetivo

Este plan define la respuesta técnica ante una falla crítica, pérdida o corrupción de datos, acceso no autorizado y errores de despliegue en Velmorax. Su propósito es contener el incidente, recuperar la operación veterinaria y conservar evidencia de las decisiones tomadas.

El alcance incluye la aplicación FastAPI, PostgreSQL, el proxy HTTPS, los respaldos cifrados, la configuración de producción y los módulos de administración, agenda, clínica e inventario.

## 2 Activos prioritarios

1. La base de datos PostgreSQL con usuarios, pacientes, citas, historias clínicas, lotes, movimientos y auditoría.
2. El código fuente versionado y la imagen estable desplegada.
3. Las variables de entorno, secretos de sesión y clave de cifrado de backups.
4. La disponibilidad de la aplicación y sus endpoints de salud.
5. Los registros de auditoría y logs técnicos correlacionados por solicitud.
6. La documentación operativa y de recuperación.

Los datos clínicos y las credenciales reciben la prioridad más alta. Los respaldos reales no se guardan en Git; la carpeta `backups/` y los archivos de entorno están excluidos mediante `.gitignore`.

## 3 Clasificación del incidente

### Baja

Error aislado que no impide la atención y no presenta riesgo de pérdida de datos. Se registra para corrección sin activar una recuperación completa.

### Media

Degradación parcial, fallas repetidas en un módulo o riesgo limitado para la integridad de la información. Se restringe el componente afectado y se informa al responsable técnico.

### Alta

Aplicación o base de datos no disponible, corrupción confirmada, acceso no autorizado, pérdida de información o despliegue que impide usar login, clínica, agenda o inventario. Se detienen cambios, se declara el incidente y se evalúa restauración o rollback.

## 4 Responsables

| Función | Responsable del ejercicio | Responsabilidad |
| --- | --- | --- |
| Líder del incidente | Maicol Andrés Ospina | Clasifica la severidad, ordena la contención y autoriza recuperación o reversa. |
| Responsable técnico | Juan David Bastidas | Diagnostica, ejecuta backup, restauración o rollback y valida los servicios. |
| Documentador | Emanuel Castaño | Registra cronología, comandos, resultados, tiempos y evidencias. |
| Comunicación | Maicol Andrés Ospina con apoyo de Emanuel Castaño | Informa el impacto confirmado y la siguiente actualización. |

La ficha del equipo es **3229209**.

## 5 Procedimiento de respuesta

1. Registrar fecha, hora, síntoma, módulos afectados y persona que reporta.
2. Clasificar el incidente y asignar al líder, responsable técnico y documentador.
3. Suspender despliegues y operaciones que puedan aumentar el daño.
4. Revisar `/health/live`, `/health/ready`, `/health` y los logs de aplicación, PostgreSQL, backup y proxy.
5. Si la base sigue accesible, generar un backup de emergencia antes de modificar datos.
6. Identificar el último commit o imagen estable y el backup verificado anterior a la falla.
7. Decidir según la evidencia:
   - reiniciar el componente cuando no exista corrupción;
   - aplicar rollback cuando la falla provenga del código;
   - restaurar datos cuando exista pérdida o corrupción confirmada;
   - combinar rollback y restauración cuando una migración defectuosa afecte código y datos.
8. Probar cualquier restauración en una base temporal. No reemplazar directamente la base de producción.
9. Validar tablas, conteos y una muestra de pacientes, citas, historias, lotes y movimientos.
10. Levantar los servicios y ejecutar las verificaciones de recuperación.
11. Abrir el acceso inicialmente a un grupo de prueba y observar logs durante quince minutos.
12. Habilitar el servicio general, reconciliar registros temporales y documentar la causa y el resultado.

## 6 Backup y restauración

El servicio `backup` definido en `docker-compose.production.yml` ejecuta un backup completo de PostgreSQL cada seis horas por defecto. El script `deploy/backup-cycle.sh` realiza estas acciones:

1. Genera un archivo en formato custom mediante `pg_dump`.
2. Comprueba que el archivo pueda ser leído por `pg_restore`.
3. Cifra el backup con AES-256-CBC y una clave separada.
4. Calcula una suma SHA-256.
5. Descifra y restaura el contenido en una base temporal.
6. Verifica la presencia de las tablas operativas requeridas.
7. Elimina copias con más de treinta días, salvo que la política configurada indique otro plazo.
8. Envía una copia fuera del servidor cuando `BACKUP_REMOTE` está configurado.

Para forzar una copia antes de un cambio importante:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml \
  exec backup backup-cycle
```

Para comprobar un backup sin tocar producción:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml \
  exec backup restore-backup /backups/velmorax_FECHA.dump.enc
```

La restauración manual crea una base temporal. El reemplazo de producción requiere autorización del líder, una ventana controlada y un backup adicional del estado actual cuando todavía sea accesible.

## 7 Criterios de recuperación

La recuperación se considera exitosa cuando se cumplen todas estas condiciones:

- `GET /health/live` confirma que el proceso está activo.
- `GET /health/ready` confirma conexión con la base de datos.
- `GET /health` informa estado correcto y PostgreSQL como motor en producción.
- Un usuario autorizado puede iniciar sesión.
- Un usuario sin permisos administrativos no puede administrar usuarios ni descargar backups.
- Agenda, pacientes, historia clínica e inventario muestran los datos esperados.
- No existen cantidades negativas ni relaciones rotas en los registros verificados.
- Los logs no presentan errores críticos durante quince minutos.

## 8 Continuidad RTO y RPO

| Proceso | Prioridad | RTO | RPO | Operación temporal |
| --- | --- | --- | --- | --- |
| Autenticación | Crítica | 1 hora | No aplica a datos clínicos | No compartir cuentas; esperar recuperación segura. |
| Historia clínica | Crítica | 2 horas | 6 horas | Formato clínico controlado y posterior transcripción. |
| Agenda | Alta | 4 horas | 6 horas | Lista temporal con hora, mascota, tutor y profesional. |
| Inventario clínico | Alta | 4 horas | 6 horas | Registrar lote, cantidad, paciente y responsable. |
| Administración | Media | 8 horas | 24 horas | Aplazar altas y cambios que no sean urgentes. |
| Reportes | Baja | 24 horas | 24 horas | Generarlos después de recuperar la operación. |

## 9 Rollback

Antes de cada despliegue se debe conservar el commit o imagen estable, la configuración vigente, el resultado de las pruebas y un backup verificado.

El rollback se activa si `/health/ready` no se recupera en diez minutos, fallan login o los procesos clínicos, aparecen errores críticos repetidos o una migración deja datos inconsistentes.

1. Detener el despliegue y bloquear nuevos cambios.
2. Guardar logs, versión fallida y hora del primer error.
3. Volver a la imagen o commit estable anterior sin borrar volúmenes.
4. Si el esquema quedó incompatible, restaurar el backup previo en una base aislada.
5. Iniciar PostgreSQL, aplicación y proxy.
6. Verificar los endpoints de salud y los recorridos de login, clínica, agenda e inventario.
7. Habilitar el servicio gradualmente y observarlo durante treinta minutos.
8. Registrar la causa, la decisión y la condición requerida antes de intentar otro despliegue.

## 10 Evidencias que deben conservarse

- Identificador y timestamp del incidente.
- Severidad, alcance y personas responsables.
- Commit o imagen estable seleccionada.
- Nombre, fecha y checksum del backup utilizado.
- Comandos ejecutados y resultados obtenidos.
- Pruebas funcionales y verificaciones de integridad.
- Mensajes enviados a los usuarios.
- Hora de recuperación, datos reconstruidos y lecciones aprendidas.

## 11 Mensaje de incidente

> Detectamos una interrupción en Velmorax a las **hora y fecha**. El incidente afecta a **usuarios, sedes o módulos confirmados**. El equipo técnico aisló el componente y está ejecutando **acción actual**. La recuperación se estima para **hora estimada** o enviaremos una nueva actualización en treinta minutos. Mientras tanto, utilice el procedimiento temporal indicado y no repita operaciones fallidas. Responsable de contacto: **nombre, rol y canal**.

El mensaje no debe incluir contraseñas, datos clínicos, nombres de pacientes ni una causa que todavía no esté confirmada.

## 12 Cierre

Un backup no probado puede estar incompleto, corrupto o cifrado con una clave que ya no existe. Por eso una copia que nunca se restaura equivale en la práctica a no tener respaldo. Velmorax prueba cada copia en una base temporal y debe realizar además un ejercicio mensual con validación funcional.

La recuperación es parte de la seguridad informática porque protege la disponibilidad y permite comprobar la integridad de la información. Controlar accesos evita acciones indebidas; conservar logs explica lo ocurrido; restaurar o volver a una versión estable permite continuar la atención veterinaria con datos confiables.
