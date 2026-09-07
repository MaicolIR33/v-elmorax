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

4. Usa uno para `SESSION_SECRET` y otro para `POSTGRES_PASSWORD`.
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
