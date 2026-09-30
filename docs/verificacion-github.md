# Verificación para GitHub — 30 de septiembre de 2026

## Estado: LISTO PARA GITHUB como proyecto de portfolio

Copia de publicación preparada sin cambiar funcionalidad. La auditoría estática
de Work, recibida como texto, se contrastó con el inventario real. Los originales
se conservaron intactos en esta fase. No se publicaron archivos ni se configuró
ningún remoto.

## Limpieza aplicada a esta copia

Se excluyeron 737 archivos: `.venv/` (455), `.cache/` (270), ocho archivos
`__pycache__` repartidos entre raíz, `src/`, `tests/` e integración, y los cuatro
CSV generados de `data/processed/`. Tampoco se copió `dist/`, que estaba vacío.

Los cuatro outputs excluidos son `clientes_procesados.csv`,
`clientes_rechazados.csv`, `clientes.xlsx/validos.csv` y
`clientes.xlsx/rechazados.csv`. Se conserva `data/processed/.gitkeep`.

Se mantienen los 19 archivos A de Work y este informe: 20 archivos públicos.
Incluyen código, tests, scripts, esquema, configuración de ejemplo, documentación
y los dos ejemplos originales. `process_csv()` y `validate_row()` permanecen
intactos por compatibilidad. `.gitignore` y `requirements.txt` no se modificaron.

La preparación actual solo actualiza este informe y la referencia del README
al estado final. Las mejoras anteriores del README explican instalación aislada,
versiones comprobadas y límites del CSV; no alteran el programa.

## Pruebas previas ejecutadas realmente en esta conversación

Windows, Python 3.12.14 y PostgreSQL 18.3. Se creó un entorno virtual nuevo fuera
del proyecto y se instaló desde `requirements.txt`: openpyxl 3.1.5,
psycopg2-binary 2.9.10, python-dotenv 1.0.1 y et-xmlfile 2.0.0 (transitiva).
`pip check` no encontró requisitos incompatibles.

```text
python -X utf8 -m unittest discover -s tests -v
Ran 35 tests in 6.453s — OK

python -X utf8 scripts/test_postgres.py --pg-bin "C:\Program Files\PostgreSQL\18\bin" --demo
Ran 9 tests in 13.177s — OK
```

Total previo: **44 aprobadas, cero fallos, cero errores y cero omitidas**.
La descarga y el primer inicio de PostgreSQL fueron bloqueados por el sandbox;
los reintentos autorizados concluyeron correctamente. Los intentos bloqueados
no se contaron como aprobados. El clúster efímero se detuvo y eliminó.

La demostración previa ejecutó inicialización dos veces (0, 0), CSV (0), XLSX
(0), lote parcial con entrada defectuosa (1 esperado), historial (0) y detalle
(0). Comprobó SHA-256 y ausencia de la contraseña efímera en la salida.

**No se repitieron esos tests ni la demostración al preparar esta copia.** Se
compararon por SHA-256 los 14 archivos funcionales, de tests, esquema,
dependencias y datos originales con el inventario anterior a las ejecuciones:
todos coinciden. Se verificó también que esta copia conserva sus bytes.

## Comprobaciones nuevas de publicación

- Comparación del inventario real con las categorías A, B y C de Work.
- Manifiestos SHA-256 de origen y copia; respaldo original conservado.
- Comprobación real del índice Git: `git add --all`, `git ls-files --stage`,
  `git diff --cached --name-only`, archivos sin seguimiento e ignorados.
- Los 20 archivos esperados forman el índice; no se incluyen entornos, cachés,
  outputs, secretos locales ni rutas personales innecesarias.
- El contenido de cada archivo del índice coincide con el de la copia limpia.
- Revisión de patrones de secretos en archivos públicos y XML interno del XLSX.

Los manifiestos y evidencias detalladas se entregan fuera del repositorio público.
El índice local queda preparado sin commits ni remotos.

## Outputs y contraste con Work

En la fase previa se regeneraron outputs fuera del proyecto: CSV con conteos
10/2/8/3/5/3, XLSX 6/1/5/1/2/3 y lote 16/3/13/4/7/6 (originales, duplicados,
procesados, con faltantes, válidos, rechazados). Los dos outputs CSV originales
y los rechazos Excel coincidieron byte a byte con los regenerados.

Se confirmó el hallazgo de Work: el antiguo `clientes.xlsx/validos.csv` tenía
cero bytes; el código actual produce encabezado y dos filas válidas, 101 y 102.
El archivo incompleto se excluye de esta entrega. No prueba un defecto actual.

Los ejemplos permanecen intactos:

```text
clientes.csv  e20e6891dfb911180eb1b707bd07fcc7cf6b6b11c4ed3677caf926e43dc24e01
clientes.xlsx 23d8f423ba30b7c7d8889e70adacc0f34292f07cb734acfab48c90cad51945d0
```

El inventario actual de origen tiene 757 archivos frente a los 756 de Work:
la diferencia es este informe, añadido en la revisión anterior. La caché de
270 archivos incluye también dos CSV en `verificacion-sin-driver/`, no solo
la caché de uv; la exclusión completa sigue siendo la misma. Work no ejecutó
tests: los resultados anteriores proceden de la comprobación posterior real.

## Seguridad y límites

No se detectaron credenciales reales, tokens, claves privadas ni rutas personales
en los archivos públicos revisados. `.env.example` contiene un marcador y los
tests usan contraseñas sintéticas. El XLSX tiene metadatos de openpyxl y no
contiene enlaces externos ni rutas personales. No se revisó historial Git previo
porque los originales no tenían `.git`. No se certifica ausencia absoluta de
vulnerabilidades ni se hizo una auditoría de vulnerabilidades de dependencias.

Se conserva la limitación comprobada de textos CSV interpretables como fórmulas
por hojas de cálculo. También siguen vigentes los límites de memoria, primera
hoja de Excel, precisión ya perdida en origen, CSV no atómicos, falta de
transacción distribuida e historial que puede quedar RUNNING tras interrupción.

Solo se probó Python 3.12.14 y PostgreSQL 18.3. Las dependencias directas están
fijadas; et-xmlfile no está fijada en requirements. Se mantienen las versiones y
compatibilidad existentes. La entrega no se presenta como lista para producción.
