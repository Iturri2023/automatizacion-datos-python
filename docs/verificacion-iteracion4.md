# Verificación de la Iteración 4

Fecha: 26 de septiembre de 2026. Entorno ejecutado: Windows, Python 3.12.14,
PostgreSQL 18.3, openpyxl 3.1.5, psycopg2-binary 2.9.10 y python-dotenv 1.0.1.

## Pruebas ejecutadas

- `python -m unittest discover -s tests -v`: **35 aprobadas**. Incluye las 25
  pruebas anteriores sin cambios y 10 nuevas pruebas unitarias con mocks.
- `python scripts/test_postgres.py --pg-bin "C:\Program Files\PostgreSQL\18\bin" --demo`:
  **9 integraciones reales aprobadas** y demostración completada.
- Ejecución normal también comprobada con el intérprete incluido en el entorno,
  sin psycopg2 ni python-dotenv instalados: resultado CSV original conservado.

Las integraciones verificaron JSONB, errores múltiples y de celdas Excel,
columnas adicionales, SHA-256, original intacto, historial nuevo en cada repetición,
límites de historial, detalle existente/inexistente, tres estados finales,
inicialización repetida con datos, restricciones y cascadas. También comprobaron
fallos reales de esquema y autenticación antes de modificar salidas.

Un trigger instalado únicamente en una base temporal provocó un error SQL durante
la inserción de registros, después de escribir los CSV. Se verificó rollback real
del archivo y sus filas, registro `FAILED` sin conteos, continuación del lote y
código 1. Un fallo de escritura simulado produjo un archivo fallido sin registros
persistidos. Las pruebas con mocks cubrieron pérdida persistente de conexión,
mensajes seguros y propagación de errores inesperados.

## Demostración real del historial

Se ejecutó `--init-db` dos veces, con código 0 ambas veces. Los identificadores
siguientes pertenecen a la base efímera de demostración, eliminada al terminar:

- Ejecución **1**, `single`, `COMPLETED`: CSV, código 0. 10 originales,
  2 duplicados, 8 procesados, 3 con faltantes, 5 válidos y 3 rechazados.
- Ejecución **2**, `single`, `COMPLETED`: XLSX, hoja `Clientes`, código 0.
  6 originales, 1 duplicado, 5 procesados, 1 con faltantes, 2 válidos y 3 rechazados.
- Ejecución **3**, `batch`, `PARTIAL`: código 1. Tres archivos encontrados,
  dos completados y uno fallido. Totales: 16 originales, 3 duplicados,
  13 procesados, 4 con faltantes, 7 válidos y 6 rechazados.

`--history` devolvió las ejecuciones en orden **3, 2, 1**. `--run-detail 3`
devolvió `a_defectuoso.csv` como `FAILED` por columnas ausentes, `clientes.csv`
como `COMPLETED` y `clientes.xlsx` como `COMPLETED`, con hoja `Clientes`.
No se mostraron los registros de clientes desde esos comandos.

Huellas verificadas contra los bytes originales y las copias procesadas:

```text
clientes.csv
e20e6891dfb911180eb1b707bd07fcc7cf6b6b11c4ed3677caf926e43dc24e01

clientes.xlsx
23d8f423ba30b7c7d8889e70adacc0f34292f07cb734acfab48c90cad51945d0
```

La demostración comprobó programáticamente que la contraseña efímera no apareciera
en stdout/stderr. No se creó `.env` ni se guardaron credenciales reales en el proyecto.
El servidor temporal y sus bases se detuvieron y eliminaron; no se usaron las bases
existentes del usuario. El historial demostrado no queda instalado permanentemente.

## Incidencias resueltas durante la verificación

- La descarga inicial de dependencias fue bloqueada por el sandbox y se completó
  con permisos de red. El instalador mostró avisos de normalización de metadatos
  de versiones; la instalación terminó correctamente.
- `initdb` no pudo arrancar bajo el token del sandbox; las integraciones se
  ejecutaron con permisos ampliados sobre el clúster creado para ellas.
- El primer ejecutor de pruebas esperaba EOF de pipes heredados por PostgreSQL en
  Windows. Se cambió la captura a un archivo temporal con tiempo máximo. Al detener
  ese primer clúster sus pruebas terminaron con errores de conexión; no se cuentan
  como aprobadas. La ejecución final corregida aprobó las nueve integraciones.

## Entrega y límites

`scripts/build_zip.py` genera `dist/automatizacion-datos-python-iteracion4.zip`
usando una lista permitida. Incluye código, pruebas, documentación, esquema,
configuración ficticia y los dos ejemplos. Excluye entornos, `.env`, cachés,
logs, bases temporales y CSV generados. Verifica la integridad del ZIP al crearlo.

No hay transacción distribuida CSV/PostgreSQL ni recuperación automática de una
ejecución interrumpida. Un fallo persistente de la base puede impedir guardar el
detalle del fallo o cerrar un `RUNNING`. Los datos se procesan en memoria y las
rutas almacenadas pueden revelar información local. No se afirma preparación
para producción ni compatibilidad probada con otras versiones de PostgreSQL.
