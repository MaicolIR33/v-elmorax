# Actividad Full Stack Docker

Variante visual del ejercicio de tareas: Astro y React para el frontend, Express para la API y MySQL para la persistencia. La estructura y los requisitos técnicos son los del ejercicio; la interfaz utiliza una composición editorial distinta.

## Requisitos incluidos

- `GET /api/health` comprueba que MySQL está disponible.
- `GET /api/tasks` lista las tareas de la tabla `task`.
- `POST /api/tasks` registra una tarea usando `{ "title": "..." }`.
- `PUT /api/tasks/:id` actualiza el título y estado de una tarea.
- `DELETE /api/tasks/:id` elimina una tarea existente.
- El inicializador crea `app_db`, la tabla `task` y las tres tareas de ejemplo.
- Nginx publica el frontend y reenvía `/api` al backend.
- Docker Compose incluye MySQL, healthchecks, dependencias entre servicios y volumen persistente.

## Ejecutar

1. Desde esta carpeta, copia `.env.example` como `.env` y ajusta los valores si no es desarrollo local.
2. Ejecuta `docker compose up --build`.
3. Abre [http://localhost:8180](http://localhost:8180).

Para detener los servicios usa `docker compose down`. Si venías de la versión antigua de directorio de usuarios, ejecuta una única vez `docker compose down -v` antes de levantarla para iniciar la base de datos de tareas desde cero.

## Puertos

| Servicio | Puerto | Uso |
| --- | --- | --- |
| Frontend | 8180 | Interfaz de tareas y proxy `/api` |
| Backend | 3100 | API Express |
| MySQL | Interno | Persistencia de tareas |
