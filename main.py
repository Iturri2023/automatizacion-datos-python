"""Procesa un archivo CSV/XLSX o un lote, conservando la ejecución original."""

import argparse
import hashlib
from pathlib import Path
import sys

from src.processor import CSVValidationError, prepare_file, process_file, write_outputs
from src.storage import COUNT_COLUMNS, DatabaseError, open_database, safe_message, utc_now


BASE_DIR = Path(__file__).resolve().parent
COUNT_LABELS = {
    "originales": "Registros originales",
    "duplicados": "Duplicados eliminados",
    "procesados": "Registros procesados",
    "con_faltantes": "Registros con valores faltantes",
    "validos": "Registros válidos",
    "rechazados": "Registros rechazados",
}


def check_destinations(jobs):
    """Comprueba todo el lote antes de permitir la primera escritura."""
    inputs = [source for source, _, _ in jobs]
    destinations = [path for _, valid, rejected in jobs for path in (valid, rejected)]
    for index, destination in enumerate(destinations):
        resolved = destination.resolve()
        for source in inputs:
            if (resolved == source.resolve() or source.resolve() in resolved.parents
                    or (destination.exists() and source.exists() and destination.samefile(source))):
                raise CSVValidationError(f"Destino conflictivo con una entrada: {destination}")
        for previous in destinations[:index]:
            if (resolved == previous.resolve() or resolved in previous.resolve().parents
                    or previous.resolve() in resolved.parents
                    or (destination.exists() and previous.exists() and destination.samefile(previous))):
                raise CSVValidationError(f"Destinos conflictivos entre sí: {destination}")
        if destination.is_dir() or any(parent.exists() and not parent.is_dir()
                                       for parent in destination.parents):
            raise CSVValidationError(f"Destino conflictivo: no se puede escribir en {destination}")


def print_counts(summary):
    for key, label in COUNT_LABELS.items():
        print(f"{label}: {summary[key]}")


def positive_id(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Debe ser un entero positivo.") from None
    if number < 1 or number > 9223372036854775807:
        raise argparse.ArgumentTypeError("ID fuera del rango de enteros positivos admitidos.")
    return number


def history_limit(value):
    number = positive_id(value)
    if number > 100:
        raise argparse.ArgumentTypeError("--history admite entre 1 y 100.")
    return number


def print_run(run):
    print(f"\nEjecución {run['id']} | {run['started_at']} | {run['mode']} | {run['status']}")
    print(f"Archivos: {run['files_found']} encontrados, {run['files_completed']} completados, "
          f"{run['files_failed']} fallidos")
    print_counts({key: run[column] for key, column in COUNT_COLUMNS.items()})


def file_info(source, valid, rejected):
    return {"source_name": source.name, "source_path": str(source.resolve()),
            "source_format": source.suffix.lower().lstrip("."), "source_sha256": None,
            "sheet_name": None, "started_at": utc_now(),
            "valid_output_path": str(valid.resolve()), "rejected_output_path": str(rejected.resolve())}


def sha256_file(source):
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finish_database_run(database, run_id):
    try:
        status = database.finish_run(run_id)
        print(f"Ejecución almacenada: {run_id} | {status}")
        return True
    except DatabaseError as error:
        print(f"Error: {safe_message(error)} No se pudo cerrar la ejecución {run_id}; "
              "puede permanecer RUNNING.", file=sys.stderr)
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--input", type=Path, help="Archivo CSV o XLSX")
    selection.add_argument("--input-dir", type=Path, help="Carpeta de CSV y XLSX, sin recursión")
    parser.add_argument("--output-dir", type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--store-db", action="store_true", help="Guardar esta ejecución en PostgreSQL")
    actions.add_argument("--init-db", action="store_true", help="Crear esquema explícitamente y terminar")
    actions.add_argument("--history", nargs="?", const=10, type=history_limit, metavar="N")
    actions.add_argument("--run-detail", type=positive_id, metavar="ID")
    args = parser.parse_args(argv)
    query_only = args.init_db or args.history is not None or args.run_detail is not None
    if query_only and (args.input is not None or args.input_dir is not None or args.output_dir is not None):
        parser.error("--init-db, --history y --run-detail no admiten opciones de procesamiento.")
    args.output_dir = args.output_dir or BASE_DIR / "data" / "processed"
    database = None
    run_id = None
    if args.store_db or query_only:
        try:
            database = open_database()
            if args.init_db:
                database.initialize()
                print("Esquema PostgreSQL inicializado; se conservó el historial existente.")
                return 0
            database.check_schema()
            if args.history is not None:
                runs = database.history(args.history)
                for run in runs:
                    print_run(run)
                if not runs:
                    print("No hay ejecuciones almacenadas.")
                return 0
            if args.run_detail is not None:
                run, files = database.run_detail(args.run_detail)
                if run is None:
                    print(f"No existe la ejecución {args.run_detail}.", file=sys.stderr)
                    return 1
                print_run(run)
                for item in files:
                    print(f"\nArchivo: {item['source_name']} | {item['status']}")
                    print(f"SHA-256: {item['source_sha256'] or 'no disponible'}")
                    if item["sheet_name"]:
                        print(f"Hoja: {item['sheet_name']}")
                    if item["status"] == "COMPLETED":
                        print_counts({key: item[column] for key, column in COUNT_COLUMNS.items()})
                    else:
                        print(f"Error: {safe_message(item['error_message'])}")
                return 0
            mode = "batch" if args.input_dir is not None else ("single" if args.input is not None else "default")
            run_id = database.start_run(mode)
            print(f"Ejecución PostgreSQL: {run_id}")
        except (DatabaseError, OSError) as error:
            print(f"Error: {safe_message(error)}. No se actualizaron las salidas.", file=sys.stderr)
            return 1

    jobs = []
    try:
        if args.input_dir is not None:
            if not args.input_dir.is_dir():
                raise CSVValidationError(f"No existe la carpeta de entrada: {args.input_dir}")
            sources = sorted(
                (path for path in args.input_dir.iterdir()
                 if path.is_file() and path.suffix.lower() in (".csv", ".xlsx")
                 and not path.name.startswith("~$")),
                key=lambda path: (path.name.casefold(), path.name),
            )
            if not sources:
                raise CSVValidationError("La carpeta no contiene archivos CSV o XLSX procesables.")
        else:
            sources = [args.input if args.input is not None else BASE_DIR / "data" / "raw" / "clientes.csv"]
            if sources[0].suffix.lower() not in (".csv", ".xlsx"):
                raise CSVValidationError("Formato no admitido; utilice .csv o .xlsx.")

        for source in sources:
            if args.input is None and args.input_dir is None:
                valid = args.output_dir / "clientes_procesados.csv"
                rejected = args.output_dir / "clientes_rechazados.csv"
            else:
                valid = args.output_dir / source.name / "validos.csv"
                rejected = args.output_dir / source.name / "rechazados.csv"
            jobs.append((source, valid, rejected))
        check_destinations(jobs)
        if database:
            database.set_files_found(run_id, len(jobs))
    except (CSVValidationError, OSError, DatabaseError) as error:
        print(f"Error: {safe_message(error)}. No se actualizaron las salidas.", file=sys.stderr)
        if database:
            # Un conflicto de destinos cancela el lote completo, pero las entradas
            # ya encontradas también deben quedar identificadas en su historial.
            if jobs:
                try:
                    database.set_files_found(run_id, len(jobs))
                    for source, valid, rejected in jobs:
                        info = file_info(source, valid, rejected)
                        try:
                            info["source_sha256"] = sha256_file(source)
                        except OSError:
                            pass  # No inventar una huella cuando los bytes no son legibles.
                        database.save_file(run_id, info, error_message=safe_message(error))
                except DatabaseError as storage_error:
                    print(f"No se pudo registrar la cancelación: {safe_message(storage_error)}", file=sys.stderr)
            finish_database_run(database, run_id)
        return 1

    totals = dict.fromkeys(COUNT_LABELS, 0)
    failures = []
    for source, valid, rejected in jobs:
        info = file_info(source, valid, rejected) if database else None
        outputs_written = False
        stage = "read"
        try:
            if database:
                info["source_sha256"] = sha256_file(source)
                result = prepare_file(source)
                info["sheet_name"] = result.summary.get("hoja")
                stage = "write"
                write_outputs(result, valid, rejected)
                outputs_written = True
                database.save_file(run_id, info, result=result)
                summary = result.summary
            else:
                summary = process_file(source, valid, rejected)
        except (CSVValidationError, OSError, DatabaseError) as error:
            message = safe_message(error)
            if outputs_written:
                message += ". Las dos salidas CSV existen, pero no quedaron almacenadas en PostgreSQL."
            elif ((database and stage == "read") or isinstance(error, CSVValidationError)
                    or (isinstance(error, FileNotFoundError) and not source.exists())):
                message += ". No se actualizaron las salidas de este archivo."
            else:
                message += ". No se completaron las salidas; revise posibles archivos anteriores o parciales."
            failures.append((source, message))
            print(f"Error en {source}: {message}", file=sys.stderr)
            if database:
                try:
                    database.save_file(run_id, info, error_message=message)
                except DatabaseError as storage_error:
                    print(f"No se pudo registrar el fallo de {source.name}: {safe_message(storage_error)}", file=sys.stderr)
            continue
        print(f"\nArchivo: {source}")
        if "hoja" in summary:
            print(f"Hoja utilizada (primera): {summary['hoja']}")
        print_counts(summary)
        print(f"Archivo de válidos: {valid.resolve()}")
        print(f"Archivo de rechazados: {rejected.resolve()}")
        for key in totals:
            totals[key] += summary[key]

    if args.input_dir is not None:
        print(f"\nArchivos encontrados: {len(jobs)}")
        print(f"Archivos completados: {len(jobs) - len(failures)}")
        print(f"Archivos fallidos: {len(failures)}")
        print("Totales de registros (solo archivos completados):")
        print_counts(totals)
        for source, message in failures:
            print(f"Archivo fallido: {source}: {message}")
    if database and not finish_database_run(database, run_id):
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
