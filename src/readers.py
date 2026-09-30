"""Lectura de CSV y XLSX a valores de texto, sin modificar los originales."""

import csv
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


REQUIRED_COLUMNS = (
    "id_cliente", "nombre", "email", "telefono", "fecha_registro", "ciudad",
    "monto_compra",
)
ERROR_COLUMN = "errores_validacion"


class CSVValidationError(ValueError):
    """Error estructural de entrada; nombre conservado por compatibilidad."""


def validate_columns(columns):
    if not columns:
        raise CSVValidationError("El archivo está vacío o no tiene encabezado.")
    if any(not isinstance(name, str) or not name.strip() for name in columns):
        raise CSVValidationError("El encabezado contiene columnas no textuales o sin nombre.")
    if len(set(columns)) != len(columns):
        raise CSVValidationError("El encabezado contiene columnas repetidas.")
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise CSVValidationError("Faltan columnas obligatorias: " + ", ".join(missing))
    if ERROR_COLUMN in columns:
        raise CSVValidationError(f"El nombre de columna {ERROR_COLUMN} está reservado.")


def read_csv(path):
    rows = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, strict=True)
            columns = next(reader, [])
            validate_columns(columns)
            for row in reader:
                if not row:
                    continue
                if len(row) != len(columns):
                    raise CSVValidationError(
                        f"La fila que termina en la línea {reader.line_num} tiene "
                        f"{len(row)} campos; se esperaban {len(columns)}."
                    )
                rows.append((row, {}))
    except (csv.Error, UnicodeError) as error:
        raise CSVValidationError(f"No se pudo leer el CSV UTF-8: {error}") from error
    return columns, rows, None


def excel_text(value, field):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        if field == "fecha_registro" and value.time() == time(0):
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        # str evita introducir los artefactos binarios de Decimal(float).
        # No se cuantiza ni redondea; solo se eliminan ceros decimales finales.
        text = format(Decimal(str(value)), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    return str(value)


def read_xlsx(path):
    try:
        # Abrir como binario permite extensiones .XLSX en cualquier plataforma.
        with path.open("rb") as source:
            workbook = load_workbook(source, read_only=True, data_only=False)
            try:
                if not workbook.worksheets:
                    raise CSVValidationError("El libro no contiene hojas de cálculo.")
                sheet = workbook.worksheets[0]
                sheet.reset_dimensions()  # No confiar en dimensiones guardadas incorrectas.
                cells = list(sheet.iter_rows())
                for row in cells:
                    for cell in row:
                        if cell.data_type == "f":
                            raise CSVValidationError(
                                f"Fórmula en hoja '{sheet.title}', celda {cell.coordinate}. "
                                "Reemplácela por valores."
                            )
                # Ignorar columnas finales sin contenido (por ejemplo, solo formato).
                width = max((index + 1 for row in cells for index, cell in enumerate(row)
                             if cell.value is not None), default=0)
                header = list(cells[0]) if cells else []
                if any(cell.data_type == "e" for cell in header):
                    raise CSVValidationError("El encabezado contiene un error de celda Excel; use texto.")
                columns = [header[i].value if i < len(header) else None for i in range(width)]
                validate_columns(columns)
                rows = []
                for row in cells[1:]:
                    if all(cell.value is None for cell in row):
                        continue
                    values = []
                    errors = {}
                    for index, field in enumerate(columns):
                        cell = row[index] if index < len(row) else None
                        value = cell.value if cell else None
                        values.append(excel_text(value, field))
                        if cell and cell.data_type == "e":
                            errors[field] = f"error de celda Excel ({value})"
                    rows.append((values, errors))
                return columns, rows, sheet.title
            finally:
                workbook.close()
    except CSVValidationError:
        raise
    except (BadZipFile, InvalidFileException, KeyError, ValueError, SyntaxError) as error:
        raise CSVValidationError(f"No se pudo leer el archivo XLSX: {error}") from error


def read_input(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No existe el archivo de entrada: {path}")
    readers = {".csv": read_csv, ".xlsx": read_xlsx}
    if path.suffix.lower() not in readers:
        raise CSVValidationError("Formato no admitido; utilice .csv o .xlsx (no .xls ni .xlsm).")
    columns, rows, sheet = readers[path.suffix.lower()](path)
    if not rows:
        raise CSVValidationError("El archivo no contiene registros de datos.")
    return columns, rows, sheet
