"""Validación y limpieza compartidas para registros CSV y XLSX."""

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re

from src.readers import CSVValidationError, ERROR_COLUMN, REQUIRED_COLUMNS, read_input


def structured_errors(values, cell_errors=None):
    """Devuelve todos los motivos de rechazo de una fila ya normalizada."""
    cell_errors = cell_errors or {}
    errors = [{"field": field, "reason": reason} for field, reason in cell_errors.items()]
    for field in REQUIRED_COLUMNS:
        if field in cell_errors:
            continue
        value = values[field]
        reason = None
        if not value:
            reason = "campo obligatorio vacío"
        elif field == "email":
            parts = value.split("@")
            if (len(parts) != 2 or not all(parts)
                    or any(char.isspace() for char in value)
                    or "." not in parts[-1]
                    or not all(parts[-1].split("."))):
                reason = "formato de email inválido"
        elif field == "telefono":
            if not re.fullmatch(r"\+?[0-9]{7,15}", value):
                reason = "debe contener entre 7 y 15 dígitos ASCII, con + inicial opcional"
        elif field == "fecha_registro":
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                reason = "debe tener formato YYYY-MM-DD"
            else:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    reason = "fecha de calendario inválida"
        elif field == "monto_compra":
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
                reason = "debe contener dígitos ASCII y punto opcional con uno o dos decimales"
        if reason:
            errors.append({"field": field, "reason": reason})
    return errors


def validate_row(values, cell_errors=None):
    """Interfaz textual conservada para consumidores anteriores."""
    return [f"{error['field']}: {error['reason']}" for error in structured_errors(values, cell_errors)]


@dataclass
class ProcessingResult:
    columns: list
    valid_rows: list
    rejected_rows: list
    summary: dict


def check_output_paths(input_path, output_path, rejected_path):
    input_path = Path(input_path)
    output_path = Path(output_path)
    rejected_path = Path(rejected_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"No existe el archivo de entrada: {input_path}")
    for destination in (output_path, rejected_path):
        if (input_path.resolve() == destination.resolve()
                or (destination.exists() and input_path.samefile(destination))):
            raise CSVValidationError("Cada salida debe ser distinta del archivo original.")
    if (output_path.resolve() == rejected_path.resolve()
            or (output_path.exists() and rejected_path.exists()
                and output_path.samefile(rejected_path))):
        raise CSVValidationError("Las rutas de ambas salidas deben ser distintas.")

def prepare_file(input_path):
    """Lee y valida completamente sin escribir salidas ni acceder a PostgreSQL."""
    valid_rows = []
    rejected_rows = []
    try:
        columns, input_rows, sheet = read_input(input_path)
    except OSError as error:
        raise CSVValidationError(f"No se pudo leer {input_path}: {error}") from error
    # La clave solo usa texto antes de normalizar. Acumular errores de celda
    # impide que un duplicado textual oculte un error de Excel posterior.
    unique_rows = {}
    for row, cell_errors in input_rows:
        unique_rows.setdefault(tuple(row), {}).update(cell_errors)
    missing_count = 0
    for row, cell_errors in unique_rows.items():
        cleaned = [" ".join(value.split()) for value in row]
        missing_count += int(any(value == "" for value in cleaned))
        data = dict(zip(columns, cleaned))
        errors = structured_errors(data, cell_errors)
        if errors:
            rejected_rows.append({"data": data, "validation_errors": errors})
        else:
            valid_rows.append({"data": data, "validation_errors": []})

    processed_count = len(valid_rows) + len(rejected_rows)
    summary = {
        "originales": len(input_rows),
        "duplicados": len(input_rows) - processed_count,
        "procesados": processed_count,
        "con_faltantes": missing_count,
        "validos": len(valid_rows),
        "rechazados": len(rejected_rows),
    }
    if sheet is not None:
        summary["hoja"] = sheet
    return ProcessingResult(columns, valid_rows, rejected_rows, summary)


def write_outputs(result, output_path, rejected_path):
    """Escribe ambos CSV desde el resultado en memoria. No es transaccional."""
    for path, rows, rejected in ((Path(output_path), result.valid_rows, False),
                                 (Path(rejected_path), result.rejected_rows, True)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.writer(destination)
            writer.writerow(result.columns + ([ERROR_COLUMN] if rejected else []))
            for row in rows:
                values = [row["data"][column] for column in result.columns]
                if rejected:
                    values.append("; ".join(f"{error['field']}: {error['reason']}"
                                            for error in row["validation_errors"]))
                writer.writerow(values)


def process_file(input_path, output_path, rejected_path):
    """Interfaz compatible: procesa, escribe y devuelve los seis conteos."""
    check_output_paths(input_path, output_path, rejected_path)
    result = prepare_file(input_path)
    write_outputs(result, output_path, rejected_path)
    return result.summary


def process_csv(input_path, output_path, rejected_path):
    """Punto de entrada conservado para los consumidores de la Iteración 2."""
    return process_file(input_path, output_path, rejected_path)
