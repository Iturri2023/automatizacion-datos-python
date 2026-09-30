# Automatización de datos con Python

Proyecto de portfolio para una empresa ficticia que recibe registros de clientes
en CSV o XLSX con duplicados, espacios innecesarios y campos vacíos. Todos los datos de
ejemplo son ficticios; los correos usan el dominio reservado `.invalid`.

## Flujo actual — iteración 4

CSV o XLSX original → validación estructural → eliminación de duplicados exactos →
normalización de espacios → validación de valores → CSV de válidos y rechazados
→ resumen.

Opcionalmente, `--store-db` guarda el historial, los resultados y los fallos en
PostgreSQL después de escribir los CSV. Sin opciones DB, el programa no carga
la configuración `.env`, no importa el driver ni intenta conectarse al servidor.

Las columnas obligatorias son `id_cliente`, `nombre`, `email`, `telefono`,
`fecha_registro`, `ciudad` y `monto_compra`. El formato de entrada es CSV separado
por comas, con encabezado y codificación UTF-8 (se admite BOM).

- Los duplicados se comparan por todos los campos **antes** de limpiar espacios;
  se conserva la primera aparición y el orden original.
- Se quitan espacios al principio y al final y se reducen espacios, tabulaciones
  y saltos de línea internos a un solo espacio en todos los campos.
- Un registro con uno o más campos vacíos tras limpiar cuenta una sola vez como
  registro con valores faltantes, después de deduplicar.
- Se conservan columnas adicionales y todos los valores como texto, incluidos
  ceros iniciales. Los campos adicionales vacíos cuentan como faltantes pero no
  provocan rechazo. Las líneas totalmente en blanco se ignoran.

## Lectura de Excel

Se admite `.xlsx`; no `.xls` ni `.xlsm`. Solo se procesa la **primera hoja de
cálculo**, cuyo nombre se muestra en el resumen; las demás no se inspeccionan
ni se mezclan. La primera fila debe ser el encabezado.

- Los encabezados deben ser textos no vacíos, sin duplicados, con las siete
  columnas obligatorias. `errores_validacion` está reservado también en Excel.
  El contenido bajo una columna sin encabezado hace fallar el archivo.
- Se ignoran filas completamente vacías y columnas finales sin contenido
  (por ejemplo, celdas que solo tienen formato). Los espacios cuentan como
  contenido antes de normalizar. Los vacíos dentro de una fila son faltantes.
- El texto se conserva hasta aplicar la normalización común.
- Los números se convierten a texto decimal sin notación científica, sin
  redondear y sin `.0` para enteros. `12.345` sigue siendo inválido aunque su
  formato visual muestre dos decimales. No se utiliza el formato visual para
  reconstruir datos ni ceros iniciales: guarda identificadores y teléfonos
  **como texto en Excel** si necesitas conservar sus ceros.
- Los booleanos se convierten a `TRUE` o `FALSE`, nunca a `1` o `0`.
- En `fecha_registro`, fechas nativas y datetimes a medianoche se convierten a
  `YYYY-MM-DD`. Un datetime con hora conserva esa hora y se rechaza como fecha.
- Los errores de celda rechazan la fila, con el campo y el error en el motivo,
  incluso en columnas adicionales.
- Una fórmula en la primera hoja hace fallar todo el archivo antes de escribir
  salidas. El mensaje identifica hoja y celda y pide reemplazarla por valores.
  No se evalúan fórmulas ni se leen sus resultados almacenados en caché.

En XLSX se deduplica por los **valores convertidos a texto**, antes de normalizar;
en CSV se compara el texto leído de los campos. Por ejemplo, un número Excel
`12.0` y el texto `12` son equivalentes después de la conversión. Si algún
duplicado contiene un error de celda, el registro único conserva ese motivo y
se rechaza. La deduplicación es independiente para cada archivo.

## Reglas de validación de valores

Se aplican después de normalizar espacios:

- Las siete columnas obligatorias deben tener contenido. Un campo vacío recibe
  únicamente el motivo `campo obligatorio vacío`, sin otro error de formato.
- `email`: exactamente un `@`, parte local y dominio no vacíos, sin espacios,
  dominio con al menos un punto y sin segmentos vacíos. Se acepta `.invalid`.
  Es una comprobación básica, no una validación completa del estándar de correo.
- `telefono`: de 7 a 15 dígitos ASCII (`0` a `9`), con un `+` opcional solo al
  principio. No admite guiones, paréntesis ni espacios internos. Se conservan
  ceros iniciales. Es una regla del proyecto.
- `fecha_registro`: exactamente `YYYY-MM-DD`, con una fecha real del calendario
  (años de 0001 a 9999). Se comprueban años bisiestos y se admiten fechas futuras.
- `monto_compra`: uno o más dígitos ASCII y, opcionalmente, un punto seguido de
  uno o dos decimales. Se aceptan `0`, `0.00`, `12`, `12.5` y `12.50`. Se rechazan
  negativos, signos `+`, comas, símbolos monetarios, notación científica, `NaN`
  e `Infinity`. Se conserva el texto normalizado sin conversión numérica.
- `id_cliente`, `nombre` y `ciudad`: solo requieren contenido no vacío.
  No se comprueba la unicidad de `id_cliente`.

Una fila puede acumular varios errores. No se corrigen automáticamente valores
inválidos ni se verifica la existencia de correos o teléfonos; no se consultan
servicios externos.

## Requisitos e instalación

Python 3.8 o posterior disponible como `python` y `openpyxl==3.1.5` para Excel.
Las pruebas usan `unittest`, incluido en Python. No se utiliza pandas.
Para la persistencia se añaden `psycopg2-binary==2.9.10` y `python-dotenv==1.0.1`.
Solo el modo DB necesita un servidor PostgreSQL; la integración real de esta
iteración se verifica con PostgreSQL 18.

Desde la carpeta del proyecto, comprueba el intérprete:

```bash
python --version
python -m venv .venv
```

Activa el entorno en Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

En Linux/macOS:

```bash
source .venv/bin/activate
```

Instala las dependencias dentro del entorno:

```bash
python -m pip install -r requirements.txt
python -m pip check
```

En Windows, si tu instalación expone `py` en lugar de `python`, puedes usar `py`
en los comandos siguientes.
Si PowerShell no permite activar scripts, utiliza directamente
`.\.venv\Scripts\python.exe` en lugar de `python`; no necesitas cambiar la
política de ejecución. La verificación del 30 de septiembre de 2026 se realizó
con Python 3.12.14 en Windows y PostgreSQL 18.3; no prueba todas las versiones
de Python admitidas. Las dependencias directas están fijadas en
`requirements.txt`; la dependencia transitiva `et-xmlfile` no lo está
(en esta verificación se instaló 2.0.0).
Si los acentos se muestran mal en la consola, utiliza `python -X utf8 main.py`.

## Ejecución y comprobación

```bash
python main.py
python main.py --input data/raw/clientes.xlsx
python main.py --input data/raw/clientes.csv --output-dir data/processed/individual
python main.py --input-dir data/raw --output-dir data/processed/lote
python -m unittest discover -s tests -v
```

Sin opciones de entrada se utiliza `data/raw/clientes.csv` y permanece intacto.
Se conservan las dos salidas originales:

- `data/processed/clientes_procesados.csv`: solo filas válidas, con las columnas
  originales en su orden original.
- `data/processed/clientes_rechazados.csv`: filas rechazadas normalizadas y una
  columna adicional `errores_validacion`. Cada motivo indica `campo: motivo`;
  los motivos se separan con `; `.

Con `--input` o `--input-dir`, las salidas se organizan por nombre completo de
archivo, incluida la extensión. Por ejemplo, en el destino predeterminado:

```text
data/processed/clientes.csv/validos.csv
data/processed/clientes.csv/rechazados.csv
data/processed/clientes.xlsx/validos.csv
data/processed/clientes.xlsx/rechazados.csv
```

`--input` y `--input-dir` son excluyentes. `--output-dir` cambia el destino y,
usado solo, conserva los nombres originales para el CSV de ejemplo. Las rutas
predeterminadas parten de la ubicación de `main.py`; las rutas relativas pasadas
como argumentos parten del directorio de ejecución.

El modo carpeta busca solo archivos directos `.csv` y `.xlsx`, sin distinguir
mayúsculas y sin recorrer subcarpetas. Ignora nombres que comienzan por `~$`.
Procesa en orden alfabético sin distinguir mayúsculas (el nombre original
desempata). Un archivo fallido no detiene los demás. Antes de iniciar el lote
se comprueba que los destinos no colisionen entre sí ni con ninguna entrada.
Usa un directorio de salida separado de los archivos de entrada.

Cada ejecución correcta reemplaza ambos archivos, aunque alguno solo tenga
encabezado, para eliminar resultados obsoletos. Si todas las filas son inválidas,
el procesamiento también se completa.

El ejemplo CSV original produce:

```text
Registros originales: 10
Duplicados eliminados: 2
Registros procesados: 8
Registros con valores faltantes: 3
Registros válidos: 5
Registros rechazados: 3
```

El ejemplo `data/raw/clientes.xlsx`, hoja `Clientes`, contiene 6 registros:
1 duplicado, 5 procesados, 1 con faltantes, 2 válidos y 3 rechazados. Los rechazos
son el correo vacío (103), la fecha con hora (104) y el monto `12.345` (105).
Sus fechas e importes son valores nativos de Excel; identificadores y teléfonos
son texto.

Un lote de ambos ejemplos completa 2 archivos y suma 16 originales,
3 duplicados, 13 procesados, 4 con faltantes, 7 válidos y 6 rechazados.

El programa también muestra las rutas de ambas salidas. `Procesados` cuenta todas
las filas únicas, válidas y rechazadas. Siempre se cumple:

```text
originales = duplicados + procesados
procesados = válidos + rechazados
```

`Con faltantes` cuenta cada fila única con algún campo vacío una sola vez,
incluidas columnas adicionales. No equivale al número de rechazados: un formato
inválido puede causar rechazo sin que haya valores vacíos.

Un archivo inexistente, vacío, sin registros o con columnas obligatorias ausentes
produce un mensaje de error y código de salida 1. También se rechazan encabezados
repetidos o sin nombre, filas con distinta cantidad de campos y sintaxis CSV
incorrecta detectada por el lector. El nombre `errores_validacion` está reservado:
si aparece en el encabezado de entrada se rechaza todo el archivo. Estos errores
estructurales se detectan antes de escribir salidas; las salidas anteriores, si
existen, permanecen intactas y corresponden a la última ejecución correcta.
Un valor inválido solo rechaza su fila. Las excepciones inesperadas se propagan.

En modo carpeta se informan archivos encontrados, completados y fallidos, los
motivos de los fallos y totales de registros **solo de archivos completados**.
No se atribuyen conteos parciales a los fallidos. Un archivo rechazado por lectura
o estructura no actualiza sus salidas anteriores; se indica en el mensaje.
Los errores de acceso se informan de forma comprensible.

Códigos de salida:

- `0`: todos los archivos completados, aunque existan filas rechazadas.
- `1`: uno o más archivos fallidos, carpeta sin entradas procesables o
  configuración de destinos conflictiva. También fallo DB o ejecución consultada
  inexistente cuando se utilizan las opciones de PostgreSQL.
- `2`: argumentos inválidos, incluidas opciones de entrada simultáneas.

## PostgreSQL opcional

El servidor y una base dedicada deben existir antes de ejecutar estos comandos.
El programa no crea bases, usuarios ni servicios. Copia `.env.example` a `.env`
en la raíz del proyecto y configura localmente `PGHOST`, `PGPORT`, `PGDATABASE`,
`PGUSER`, `PGPASSWORD` y `PGTZ`. Las variables ya definidas en el entorno tienen
prioridad sobre `.env`. El ejemplo usa `PGTZ=America/Bogota`, configurable.
Los tiempos usan `TIMESTAMPTZ`; la zona controla su presentación, no el instante.
No publiques `.env` ni credenciales. Los errores SQL muestran una explicación
segura y, si está disponible, SQLSTATE; no imprimen el mensaje crudo del driver.

```bash
python main.py --init-db
python main.py --store-db
python main.py --input data/raw/clientes.xlsx --store-db
python main.py --input-dir data/raw --output-dir data/processed/lote --store-db
python main.py --history
python main.py --history 5
python main.py --run-detail 1
```

`--init-db` ejecuta `schema.sql` explícitamente y termina; repetirlo conserva los
datos. No se inicializa ni migra automáticamente durante el procesamiento.
Para esquemas incompatibles de versiones futuras se necesitará una migración
separada y explícita; repetir la inicialización no migra tablas existentes.

`--store-db` comprueba conexión y columnas del esquema antes de modificar salidas.
Tras esa comprobación crea una ejecución nueva, incluso si después no encuentra
entradas procesables. Si PostgreSQL no está disponible al inicio no puede crear
historial y termina con código 1 sin modificar los CSV.

`--history` muestra las últimas 10 ejecuciones; admite un límite entre 1 y 100,
ordenado por inicio descendente y por ID en caso de empate. `--run-detail` muestra
la ejecución y sus archivos con SHA-256, hoja, conteos o error, sin listar los
registros de clientes. Ambos son de solo lectura. `--init-db`, `--history`,
`--run-detail` y `--store-db` son mutuamente excluyentes. Los tres primeros no
admiten `--input`, `--input-dir` ni `--output-dir`.

Tablas:

- `processing_runs`: inicio, fin, modo, estado, número de archivos y seis totales.
- `processed_files`: ejecución, ruta, nombre, formato, SHA-256, hoja, estado,
  tiempos, rutas de salida, conteos completos o mensaje de fallo.
- `processed_records`: archivo, tipo `VALID`/`REJECTED`, número de fila desde 1
  dentro de su salida (sin encabezado), datos normalizados en JSONB y errores
  JSONB como lista de objetos `{"field": "email", "reason": "campo obligatorio vacío"}`.
  Los válidos usan `[]`. `data` conserva columnas adicionales y no incluye
  `errores_validacion`. JSONB no garantiza orden de claves; el orden de columnas
  se conserva en el resultado en memoria y en los CSV.

El esquema exige estados válidos, conteos no negativos y tiempos coherentes.
Los archivos completados tienen todos los conteos; los fallidos los tienen nulos
y no pueden tener registros asociados. Las claves foráneas borran en cascada
si alguien elimina explícitamente una ejecución o archivo por SQL. El programa
no ofrece comandos de borrado. Incluye solo los índices de fecha de ejecución,
archivos por ejecución y SHA-256, y registros por archivo/tipo.

Estados globales:

- `RUNNING`: ejecución iniciada y aún sin cerrar.
- `COMPLETED`: todos sus archivos completados, aunque existan filas rechazadas.
- `PARTIAL`: al menos un archivo completado y otro fallido.
- `FAILED`: ningún archivo completado, incluidas carpetas sin entradas procesables.

Los totales almacenados se calculan en PostgreSQL sumando únicamente archivos
`COMPLETED`. Cada repetición crea historial nuevo: SHA-256 no es único ni evita
procesar de nuevo. La huella se calcula sobre los bytes originales antes de leer
y validar. Si no es posible leerlos, por ejemplo un archivo inexistente, se guarda
SHA-256 nulo y el motivo; no se inventa una huella. No modifiques los archivos
concurrentemente durante el procesamiento.

Se almacenan los datos de clientes normalizados y las rutas absolutas. **Las rutas
pueden revelar nombres de usuario o carpetas locales.** No se guarda el binario
original ni la contraseña de conexión como datos del historial.

## Consistencia y fallos de almacenamiento

Cada archivo se lee y valida completamente en memoria, se escriben sus dos CSV
y después se guarda el archivo con todos sus registros en una transacción SQL.
No se releen los CSV para persistir. Si falla la escritura, se registra `FAILED`
sin registros ni conteos. Si falla SQL después de escribir los CSV, se informa
que las salidas existen pero no quedaron almacenadas y se intenta registrar el
fallo en una transacción nueva. El lote continúa y devuelve código 1.

No hay transacción distribuida entre filesystem y PostgreSQL: los CSV pueden
existir aunque falle su almacenamiento. Si la base sigue inaccesible, incluso
registrar el fallo o cerrar la ejecución puede ser imposible; se informa y una
ejecución podría quedar `RUNNING`, o faltar el detalle de un archivo fallido.
Cuando es posible cerrar, el número de fallidos incluye entradas encontradas
sin resultado almacenado, pero los totales nunca incluyen esos archivos.
Una interrupción abrupta del proceso también puede dejar `RUNNING`.

## Pruebas aisladas

Pruebas anteriores y unitarias nuevas, sin servidor PostgreSQL:

```bash
python -m unittest discover -s tests -v
```

Las pruebas con mocks están en `tests/test_database_unit.py`. Las integraciones
reales se ejecutan por separado, con binarios locales `initdb` y `pg_ctl`:

```powershell
python scripts/test_postgres.py --pg-bin "C:\Program Files\PostgreSQL\18\bin" --demo
```

En otros sistemas pasa la carpeta equivalente de binarios PostgreSQL. El ejecutor
crea un clúster temporal nuevo, escucha solo en `127.0.0.1` en un puerto libre,
genera una contraseña efímera y sobrescribe la configuración PG únicamente durante
las pruebas. Cada prueba crea una base con nombre aleatorio, y elimina solo esa
base. No usa el servicio ni ninguna base existente del usuario. Finalmente detiene
y elimina el clúster que creó. Requiere permisos para ejecutar los binarios y abrir
un puerto local; no debe ejecutarse como root en sistemas que lo prohíban.

`--demo` ejecuta además inicialización repetida, los dos ejemplos, un lote parcial,
historial, detalle y comprobaciones de SHA-256. Las integraciones incluyen un fallo
SQL real mediante un trigger creado únicamente en una base temporal, para verificar
rollback de archivo y registros. Los resultados de la verificación están en
`docs/verificacion-iteracion4.md`.
La comprobación y la preparación final para publicación se documentan en
`docs/verificacion-github.md`; el informe anterior se conserva como histórico.

Para generar la entrega limpia:

```bash
python scripts/build_zip.py
```

El ZIP usa una lista permitida de código, pruebas, documentación, esquema,
`.env.example` y ejemplos originales. Excluye `.env`, `.venv`, cachés, logs,
bases temporales y salidas generadas. No es un sistema declarado listo para producción.

## Estructura

```text
data/raw/clientes.csv       Datos ficticios de entrada
data/raw/clientes.xlsx      Ejemplo Excel con datos ficticios
data/processed/             Salida generada (ignorada por Git)
src/readers.py             Lectura CSV/XLSX y validación estructural
src/processor.py           Limpieza, validación de valores y escritura comunes
src/storage.py             PostgreSQL opcional y consultas de historial
schema.sql                 Instalación explícita e idempotente
.env.example               Configuración ficticia de ejemplo
tests/test_processor.py    Pruebas anteriores con archivos temporales
tests/test_excel_and_cli.py Pruebas de Excel, lotes y línea de comandos
tests/test_database_unit.py Pruebas DB con mocks, sin servidor
tests/integration/         Pruebas reales en bases temporales
scripts/test_postgres.py   Clúster efímero, integraciones y demostración
scripts/build_zip.py       Entrega limpia mediante lista permitida
main.py                    Opciones, destinos y resúmenes
requirements.txt           openpyxl, psycopg2-binary y python-dotenv
```

Esta iteración procesa cada archivo en memoria y está pensada para archivos
pequeños. No recupera precisión ni ceros que Excel ya haya perdido al guardar
números; la conversión parte de los valores que entrega openpyxl.
Las dos escrituras no son una transacción: un fallo de disco o permisos durante
la escritura puede dejar salidas parciales y se informa del fallo.
Los CSV conservan textos que empiezan por `=`, `+`, `-` o `@`; no neutralizan
fórmulas para hojas de cálculo. Por ejemplo, `=1+1` en `nombre` se exporta
literalmente. Al abrir salidas procedentes de entradas no confiables, importa
las columnas como texto para evitar su interpretación como fórmulas.
No incluye API, interfaz gráfica, Docker, cloud ni programación automática.
