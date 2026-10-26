# Sistema de Reservas de Laboratorio

API REST para consultar equipos y administrar reservas de un laboratorio universitario. La aplicación está construida con FastAPI, valida los intervalos de uso y guarda las reservas en un archivo JSON local.

## 1. ESPECIFICACIÓN BREVE

### Problema y alcance

Un laboratorio universitario comparte instrumentos entre estudiantes y personal. El sistema permite consultar el inventario y la disponibilidad, registrar reservas, cancelarlas y consultar el historial. El inventario inicial es fijo y contiene:

- `MIC-01`
- `MIC-02`
- `OSC-01`
- `MUL-01`
- `FUE-01`

La API no administra usuarios, autenticación, permisos ni cambios en el inventario.

### Requisitos verificables y reglas de negocio

1. `GET /api/inventory` devuelve las cinco unidades precargadas.
2. `GET /api/availability` recibe `start` y `end`, y opcionalmente `instrument_id`; informa disponibilidad para el intervalo solicitado.
3. `POST /api/reservations` crea una reserva para una unidad existente y un solicitante no vacío.
4. El inicio debe ser anterior al fin. Fechas que no puedan interpretarse como fechas ISO 8601 se rechazan.
5. No se permiten intervalos superpuestos entre reservas activas de la misma unidad. Los extremos del intervalo no se consideran ocupados: una reserva puede comenzar exactamente cuando termina otra.
6. Se permiten reservas simultáneas para unidades distintas.
7. `PATCH /api/reservations/{id}/cancel` cambia el estado de una reserva activa a `cancelled`. La reserva permanece en el historial y deja de bloquear disponibilidad. Cancelar nuevamente una reserva ya cancelada no cambia su estado.
8. `GET /api/reservations` incluye reservas activas y canceladas.
9. Las altas y cancelaciones se guardan localmente y se recuperan al reiniciar la aplicación.

### Supuestos

- Las fechas sin zona horaria se interpretan como UTC. Las fechas con zona horaria se normalizan a UTC al guardarlas.
- Los intervalos se tratan como semiabiertos: `[start, end)`. Así se admiten reservas consecutivas sin considerarlas superpuestas.
- El archivo JSON es el almacenamiento persistente para una instancia local del servicio; no es una base de datos compartida.
- Los estados válidos del sistema son `active` y `cancelled`.

### Criterios de aceptación

El sistema se considera aceptable cuando los endpoints devuelven los datos esperados, rechazan entradas inválidas y unidades desconocidas, detectan conflictos solo para la misma unidad, admiten reservas consecutivas y simultáneas entre equipos distintos, y conservan tanto altas como cancelaciones en el almacenamiento local. La suite automatizada de `test_main.py` comprueba estos casos.

## 2. SOLUCIÓN

### Estructura y tecnologías

```text
.
├── main.py           # Aplicación FastAPI, modelos y reglas de negocio
├── test_main.py      # Pruebas automatizadas de la API
├── requirements.txt  # Dependencias
└── reservations.json # Se crea al registrar la primera reserva
```

- **FastAPI** expone los endpoints REST y genera la documentación OpenAPI.
- **Pydantic** valida el cuerpo de las solicitudes y convierte las fechas a `datetime`.
- **Uvicorn** ejecuta el servidor ASGI.
- **Pytest** ejecuta las pruebas; **HTTPX** las envía a la aplicación ASGI sin iniciar un servidor externo.

### Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/inventory` | Devuelve la lista de unidades precargadas. |
| `GET` | `/api/availability?start=...&end=...` | Devuelve la disponibilidad de todas las unidades para el intervalo. |
| `GET` | `/api/availability?start=...&end=...&instrument_id=MIC-01` | Consulta una unidad específica. |
| `POST` | `/api/reservations` | Crea una reserva; responde con `201 Created`. |
| `PATCH` | `/api/reservations/{id}/cancel` | Cancela una reserva existente. |
| `GET` | `/api/reservations` | Lista reservas activas y canceladas. |

El cuerpo de `POST /api/reservations` tiene esta forma:

```json
{
  "requester": "Ana Pérez",
  "instrument_id": "MIC-01",
  "start": "2026-11-01T09:00:00Z",
  "end": "2026-11-01T10:00:00Z"
}
```

Una reserva creada contiene un identificador UUID, solicitante, unidad, fechas ISO 8601 y estado:

```json
{
  "id": "identificador-generado",
  "requester": "Ana Pérez",
  "instrument_id": "MIC-01",
  "start": "2026-11-01T09:00:00+00:00",
  "end": "2026-11-01T10:00:00+00:00",
  "status": "active"
}
```

Las solicitudes inválidas responden con `422`, una unidad o reserva inexistente con `404`, y un conflicto de horario con `409`.

### Decisiones técnicas

- Las reservas se serializan como una lista JSON en `reservations.json`, ubicado junto a `main.py`. Si el archivo aún no existe, se interpreta como un historial vacío.
- Las fechas se guardan en formato ISO 8601 normalizadas a UTC y se leen desde el mismo formato.
- La cancelación modifica el estado del registro existente en vez de eliminarlo, preservando el historial.
- Las escrituras se realizan primero en un archivo temporal y luego se reemplaza el archivo de datos. Un bloqueo en memoria protege las operaciones de alta y cancelación dentro del proceso.

### Requisitos previos e instalación

Se requiere Python 3.10 o posterior. Desde la raíz del repositorio, instalar las dependencias:

```bash
pip install -r requirements.txt
```

### Ejecución, documentación y pruebas

Iniciar el servidor de desarrollo:

```bash
uvicorn main:app --reload
```

Abrir Swagger UI en [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). La especificación OpenAPI también está disponible en `/openapi.json`.

Ejecutar las pruebas automatizadas desde la raíz:

```bash
pytest -v
```

### Datos, reinicio y limitaciones conocidas

La ubicación predeterminada de los datos es `reservations.json` en el directorio raíz del proyecto, junto a `main.py`. Para reiniciar el historial, detener el servidor y eliminar ese archivo; la aplicación comenzará con una lista vacía y lo volverá a crear cuando se registre otra reserva. No se debe borrar el archivo mientras haya escrituras activas.

El almacenamiento JSON y el bloqueo son adecuados para una ejecución local o de desarrollo. El bloqueo solo coordina solicitudes dentro de un proceso; no garantiza exclusión entre varios procesos o servidores. Para despliegues concurrentes se recomienda migrar a una base de datos con transacciones. El sistema tampoco incluye autenticación, autorización, administración dinámica del inventario ni políticas de retención.

## 3. PREPARACIÓN DEL AGENTE

### Entorno y modelo

- **Entorno de trabajo:** Orca ADE, según el contexto de ejecución indicado para el proyecto.
- **Modelo de IA:** GitHub Copilot, agente de programación integrado. La selección concreta del modelo subyacente depende del modo automático del entorno.
- **Repositorio y alcance:** cambios locales en `main.py`, `test_main.py` y `requirements.txt`; documentación en la raíz del repositorio.

### Instrucciones y contexto suministrado

El agente recibió como contexto las reglas del sistema de reservas: inventario fijo de cinco instrumentos, endpoints requeridos, validaciones de solicitante y fechas, prevención de superposiciones, reservas consecutivas y simultáneas entre unidades, cancelaciones y persistencia local. También se solicitó una suite de pruebas con Pytest y HTTPX que verificara las reglas de negocio.

La configuración del proyecto declara FastAPI, Uvicorn, HTTPX y Pytest en `requirements.txt`. El servicio no necesita credenciales externas ni acceso a servicios de terceros para operar.

### Herramientas, permisos y supervisión humana

Se utilizaron herramientas de lectura y edición del repositorio, ejecución de Python y Git para validar los cambios. El agente pudo modificar archivos del proyecto y ejecutar pruebas localmente; no se configuraron herramientas de despliegue ni servicios externos como parte de esta solución.

La persona solicitante definió los requisitos y revisó el resultado mediante instrucciones posteriores. Antes de dar por terminada la implementación se ejecutaron las pruebas automatizadas y se comprobó que los cambios no tuvieran errores de sintaxis o formato. La aceptación final de los cambios corresponde a la supervisión humana.

### Adaptación específica al laboratorio

La solución no usa almacenamiento genérico ni depende de una base de datos: guarda los registros localmente en `reservations.json`, conserva las cancelaciones y vuelve a cargar los datos en cada operación. La comparación de intervalos permite turnos consecutivos mediante la condición estricta `start < existing_end` y `end > existing_start`; a la vez, limita los conflictos a reservas activas de la misma unidad.

## 4. REGISTRO DE DECISIONES Y DELEGACIÓN (LOS 3 EPISODIOS REALES)

Los episodios siguientes resumen las solicitudes y decisiones registradas durante el trabajo. La implementación, las correcciones y la aceptación se realizaron en el mismo flujo de trabajo; no se delegaron tareas a otros agentes.

### Episodio 1: Creación del backend inicial FastAPI, modelos Pydantic e inventario precargado

- **Objetivo:** establecer el backend del sistema de reservas y exponer el inventario fijo del laboratorio.
- **Prompt/Contexto:** se solicitó reestructurar `main.py` para un sistema de reservas de laboratorio con unidades `MIC-01`, `MIC-02`, `OSC-01`, `MUL-01` y `FUE-01`, además de definir endpoints REST y sus reglas.
- **Resultado:** se reemplazó el servicio anterior de orquestación de IA por una aplicación FastAPI titulada `Laboratory Reservation System`; se definió el modelo Pydantic `ReservationRequest`, el inventario constante y las rutas de inventario, disponibilidad y reservas.
- **Decisión humana de aceptar/corregir:** la persona solicitante especificó el alcance y las reglas del nuevo sistema. La implementación se conservó como base y se continuó con la lógica de negocio y su verificación automatizada.

### Episodio 2: Implementación de la lógica de negocio

- **Objetivo:** validar disponibilidad, permitir reservas consecutivas y simultáneas entre unidades distintas, administrar cancelaciones y persistir los registros.
- **Prompt/Contexto:** se pidieron validaciones de solicitante y fechas, prevención de superposiciones entre reservas activas para la misma unidad, tolerancia a turnos consecutivos, simultaneidad entre unidades y persistencia local de reservas activas y canceladas.
- **Resultado:** se implementó la comprobación de intervalos activos, la normalización de fechas ISO 8601 a UTC, la cancelación por identificador sin eliminar el registro y la lectura/escritura de `reservations.json`. Las escrituras usan archivo temporal y reemplazo; un bloqueo en memoria protege altas y cancelaciones dentro del proceso.
- **Decisión humana de aceptar/corregir:** las reglas y el formato de persistencia fueron definidos por la solicitud. La persona solicitante pidió que se documentara expresamente la adaptación de turnos consecutivos; la solución los permite cuando el inicio de una reserva coincide con el fin de la anterior.

### Episodio 3: Generación de la suite de pruebas automáticas con Pytest

- **Objetivo:** comprobar las reglas de negocio, respuestas de validación y persistencia después de reiniciar el cliente de la API.
- **Prompt/Contexto:** se solicitó crear `test_main.py` con Pytest y HTTPX para probar las reglas del sistema, incluyendo superposiciones, límites temporales, entradas inválidas y persistencia.
- **Resultado:** se añadieron pruebas para inventario, solicitantes vacíos, fechas inválidas o invertidas, instrumentos inexistentes, conflictos, turnos consecutivos, unidades distintas, disponibilidad, cancelaciones, listado y lectura de datos guardados. Se añadió `pytest` a `requirements.txt`; las pruebas ejercitan la aplicación ASGI mediante HTTPX.
- **Decisión humana de aceptar/corregir:** el alcance de las verificaciones se basó en la consigna. La suite se ejecutó durante la implementación y las 16 pruebas pasaron antes de preparar esta documentación.
