# Despliegue de Velmorax

Esta instalación ejecuta tres servicios aislados: Velmorax, PostgreSQL y Caddy.
PostgreSQL no publica puertos hacia Internet y Caddy obtiene y renueva el
certificado HTTPS automáticamente.

## Requisitos

- Un servidor Linux con Docker y Docker Compose.
- Un dominio o subdominio, por ejemplo `app.clinica.com`.
- Registros DNS `A` y, si corresponde, `AAAA` apuntando al servidor.
- Puertos 80 y 443 abiertos. PostgreSQL (5432) debe permanecer cerrado.

Para una clínica pequeña puede usarse un servidor con 2 CPU y 4 GB de RAM.
Para operación 24/7, varias sedes o mayor concurrencia, comienza con 4 CPU,
8 GB de RAM y almacenamiento SSD administrado. Ajusta `WEB_CONCURRENCY` según
la capacidad y mide antes de ampliarlo.

## Preparación

1. Copia `.env.production.example` como `.env.production`.
2. Define `VELMORAX_DOMAIN` sin `https://` ni rutas.
3. Genera secretos distintos y no los compartas ni los subas al repositorio:

   ```bash
   openssl rand -hex 32
   ```

4. Usa uno para `SESSION_SECRET`, otro para `POSTGRES_PASSWORD` y guarda un
   tercero como clave de cifrado del respaldo:

   ```bash
   mkdir -p .secrets backups
   chmod 700 .secrets backups
   openssl rand -hex 32 > .secrets/backup_passphrase
   chmod 600 .secrets/backup_passphrase
   ```

   Conserva una copia de esa clave en el gestor de contraseñas empresarial. Sin
   ella, los respaldos cifrados no pueden recuperarse.
5. Comprueba la configuración antes de iniciar:

   ```bash
   docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
   ```

## Inicio

```bash
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yml ps
```

Al abrir `https://TU_DOMINIO/health`, el estado debe ser `ok` y la base debe
figurar como `postgres`. Los certificados se renuevan automáticamente.

La comprobación final puede ejecutarse desde otro equipo para verificar dominio,
HTTPS, disponibilidad y PostgreSQL de una sola vez:

```bash
./deploy/check-production.sh https://app.tu-dominio.com
```

## Actualización sin improvisaciones

```bash
git pull --ff-only
docker compose --env-file .env.production -f docker-compose.production.yml build app
docker compose --env-file .env.production -f docker-compose.production.yml up -d
```

Antes de actualizar una clínica real debe ejecutarse la copia de seguridad del
punto 2 del plan. La aplicación valida la configuración al arrancar y se detiene
si detecta SQLite, HTTP, dominio abierto, secreto débil o datos demo.

## Comprobaciones operativas

```bash
docker compose --env-file .env.production -f docker-compose.production.yml ps
docker compose --env-file .env.production -f docker-compose.production.yml logs --tail=100 app caddy postgres
```

La base de datos vive en el volumen `postgres_data`; los certificados, en
`caddy_data`. No borres esos volúmenes al detener los servicios.

## Copias automáticas y recuperación

El servicio `backup` genera inmediatamente una copia y repite el ciclo cada seis
horas por defecto. Cada copia:

1. Se crea con el formato recuperable de PostgreSQL.
2. Se cifra con una clave independiente.
3. Se valida mediante suma de integridad.
4. Se restaura en una base temporal.
5. Comprueba las tablas operativas y elimina la restauración temporal.
6. Se conserva 30 días y, si se configuró, se envía fuera del servidor.

Consulta el último resultado:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml ps backup
cat backups/last_success_at backups/last_success_file backups/last_success_status
```

Fuerza una copia antes de una actualización importante:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml exec backup backup-cycle
```

Comprueba manualmente una copia concreta sin tocar producción:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml exec backup \
  restore-backup /backups/velmorax_FECHA.dump.enc
```

La restauración manual crea una base temporal e informa su nombre. Esto permite
revisarla antes de reemplazar datos reales. El reemplazo de producción debe
realizarse durante una ventana controlada, con la aplicación detenida y después
de generar una copia de seguridad adicional.

Para cumplir una estrategia 3-2-1, configura `BACKUP_REMOTE` y crea
`.secrets/rclone.conf` con un destino externo cifrado (S3, almacenamiento de otro
proveedor o servidor independiente). Una copia ubicada únicamente en el mismo
servidor no protege contra pérdida total del equipo.

Frecuencia sugerida:

- Clínica pequeña: cada 12 horas, conservación mínima de 30 días.
- Clínica mediana: cada 6 horas y copia externa obligatoria.
- Clínica grande o urgencias 24/7: cada hora, almacenamiento externo con
  versionado y una prueba de recuperación supervisada cada mes.

Estos valores se cambian mediante `BACKUP_INTERVAL_SECONDS` y
`BACKUP_RETENTION_DAYS`, sin modificar la aplicación.
