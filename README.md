# Velmorax

Base inicial de una plataforma web en Python para gestion clinica e inventario
multiespecialidad.

## Stack inicial

- FastAPI
- Jinja2
- Uvicorn

## Ejecutar en local

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m uvicorn app.main:app --reload
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m uvicorn app.main:app --reload
```

Abre `http://127.0.0.1:8000/login`.

## Clonar y arrancar

El repositorio esta preparado para clonar sin archivos sensibles ni bases locales.

```powershell
git clone https://github.com/MaicolIR33/v-elmorax.git
cd v-elmorax
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

Arranque guiado en Windows:

```powershell
.\start-production.ps1
```

Si `.env.production` no existe, el script creara una copia base desde
`.env.production.example`.

## Flujo de acceso

- Antes de iniciar sesion, el usuario elige para que quiere usar la web:
  odontologia, veterinaria, consulta general o inventario.
- Despues del login, Velmorax redirige al modulo mas util segun esa intencion y
  los permisos del rol.

## PostgreSQL

La app sigue funcionando con SQLite por defecto, pero ahora acepta
`DATABASE_URL` para correr sobre PostgreSQL.

Inicio rapido con Docker:

```powershell
docker compose up -d
$env:DATABASE_URL="postgresql://velmorax:velmorax_dev@localhost:5432/velmorax"
python -m uvicorn app.main:app --reload
```

Ejemplo manual en PowerShell:

```powershell
$env:DATABASE_URL="postgresql://postgres:tu_clave@localhost:5432/velmorax"
uvicorn app.main:app --reload
```

Por defecto, si `DATABASE_URL` no existe, se usa:

```text
sqlite:///data/velmorax.db
```

## Vision del producto

- Inventario inteligente con lotes, vencimientos y semaforizacion
- Registro clinico configurable por especialidad
- Soporte para odontologia, veterinaria y otras clinicas
- Base con soporte configurable para SQLite/PostgreSQL, autenticacion y auditoria
- Gestion multi-sede y multi-organizacion
- Modulo administrativo para red, sedes y usuarios
- Activacion y desactivacion operativa de sedes y usuarios
- Importacion masiva de catalogos odontologicos por CSV desde administracion

## Estado actual

La base ya incluye una version operativa de estos frentes:

- Login por flujo clinico con sesion y expiracion por inactividad
- Recuperacion de clave por token local y cambio obligatorio de clave temporal
- Bloqueo temporal tras varios intentos fallidos
- Roles por modulo y sede
- Inventario con proveedor, costos, cadena de frio y exportacion CSV
- Historia clinica extendida para odontologia, veterinaria y consulta general
- Cierre diario con resumen por especialidad, medio de pago y profesional
- Auditoria exportable y respaldo descargable desde administracion
- Configuracion central de soporte y despliegue
- Compatibilidad con SQLite y PostgreSQL

## Flujo veterinario de Insumos

El módulo conserva la trazabilidad por producto y lote sin duplicar operaciones de otros módulos:

- Recepción guiada en tres pasos con producto, proveedor, documento, lote, vencimiento y responsable.
- Registro automático del movimiento inicial y de la temperatura recibida cuando aplica cadena de frío.
- Búsqueda por producto, lote, código y filtros de estado, tipo, vencimiento, ubicación o proveedor.
- Movimientos de entrada, consumo, ajuste y merma con existencia anterior y posterior.
- Consumo clínico vinculado al paciente o cita, con prioridad urgente y referencia del caso.
- Cuarentena operativa que bloquea el uso clínico y el traslado de lotes bajo revisión.
- Traslados balanceados entre sedes con una sola referencia y registro en origen y destino; la opción solo aparece cuando existe otra sede veterinaria configurada.
- Abastecimiento con solicitud, aprobación independiente y recepción vinculada al nuevo lote.
- Vista consolidada de existencias, críticos y stock bajo cuando la organización configura varias sedes.
- Adaptación progresiva: una sede trabaja con el flujo esencial y las capacidades de red aparecen únicamente al crecer.
- Conteo físico, control de temperatura, edición y retiro trazable en paneles laterales compactos.
- Separación entre lotes activos y retirados, historial responsable y exportación CSV.
- Bloqueo de duplicados, existencias negativas, consumo de lotes vencidos o en cuarentena y operaciones sin permisos.
- Actualizaciones atómicas de existencias para evitar sobreconsumo cuando varios usuarios trabajan al mismo tiempo.
- Aislamiento de consultas y operaciones por organización y sede autorizada.
- Índices operativos para lotes, movimientos, traslados y solicitudes de abastecimiento.
- Respaldo SQLite consistente incluso con escritura simultánea y comprobación de base en `/health`.
- Esquema y consultas del módulo compatibles con PostgreSQL para despliegues de mayor escala.

## Seguridad y acceso

- Las claves nuevas se almacenan con PBKDF2-SHA256.
- Los hashes antiguos demo siguen siendo compatibles para no romper la base inicial.
- Despues de varios intentos fallidos, el usuario queda bloqueado temporalmente.
- Los usuarios creados desde administracion quedan marcados para cambio obligatorio de clave en el primer acceso.

## Despliegue recomendado

Para una instalacion definitiva:

1. Usa PostgreSQL en `DATABASE_URL`.
2. Cambia `SESSION_SECRET`.
3. Activa `SESSION_HTTPS_ONLY=1` detras de HTTPS.
4. Configura respaldos periodicos de la base.
5. Mantén el endpoint `/health` para monitoreo.

## Archivos no versionados

Por seguridad y limpieza, el repositorio excluye:

- `.env.production`
- `.venv/`
- bases de datos SQLite locales
- `data/`
- `output/`
- recursos temporales de trabajo local

## Reportes disponibles

- `/clinica/cierre-diario/export`
- `/clinica/cierre-diario/imprimir`
- `/clinica/reportes/atenciones/export`
- `/inventario/export`
- `/admin/auditoria/export`
- `/admin/backup`

## Pruebas

Prueba rapida con la libreria estandar:

```powershell
python -m unittest discover -s tests
```

## Importacion de catalogos odontologicos

Desde `Administracion` puedes importar instituciones y sedes con un archivo CSV.

Plantilla base:

```text
/static/templates/odontologia_catalogo_template.csv
```

Columnas esperadas:

```text
organization_name,country,timezone,location_name,city,sector,address,is_active
```

Notas:

- `organization_name`: nombre de la institucion o red.
- `sector`: zona o parte de la ciudad.
- `address`: direccion corta o referencia.
- `is_active`: usa `1` para activa y `0` para inactiva.
- Si la institucion o la sede ya existen, la importacion las actualiza.
