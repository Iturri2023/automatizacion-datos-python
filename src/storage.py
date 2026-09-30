"""Persistencia opcional. No importa el driver ni conecta hasta activarla."""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path


COUNT_COLUMNS = {
    "originales": "original_count", "duplicados": "duplicate_count",
    "procesados": "processed_count", "con_faltantes": "missing_count",
    "validos": "valid_count", "rechazados": "rejected_count",
}
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


class DatabaseError(RuntimeError):
    """Fallo esperado de PostgreSQL, con un mensaje seguro para el usuario."""


def safe_message(message):
    password = os.environ.get("PGPASSWORD")
    return str(message).replace(password, "[CONTRASEÑA OCULTA]") if password else str(message)


def utc_now():
    return datetime.now(timezone.utc)


def open_database():
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise DatabaseError("Faltan dependencias DB; instale requirements.txt.") from None
    load_dotenv(SCHEMA_PATH.parent / ".env", override=False)
    return Database()


class Database:
    def __init__(self):
        try:
            import psycopg2
            from psycopg2.extras import Json, RealDictCursor
        except ImportError:
            raise DatabaseError("Falta psycopg2-binary; instale requirements.txt.") from None
        self.driver = psycopg2
        self.json = Json
        self.cursor_factory = RealDictCursor
        self.parameters = {name: os.environ[env] for name, env in (
            ("host", "PGHOST"), ("port", "PGPORT"), ("dbname", "PGDATABASE"),
            ("user", "PGUSER"), ("password", "PGPASSWORD")) if env in os.environ}
        self.parameters["connect_timeout"] = 5
        self.timezone = os.environ.get("PGTZ", "UTC")

    @contextmanager
    def transaction(self):
        connection = None
        try:
            connection = self.driver.connect(**self.parameters)
            with connection:
                with connection.cursor(cursor_factory=self.cursor_factory) as cursor:
                    cursor.execute("SELECT set_config('TimeZone', %s, false)", (self.timezone,))
                    yield cursor
        except self.driver.Error as error:
            # No incluir str(error), DSN ni parámetros: SQL puede contener datos
            # o credenciales. SQLSTATE es suficiente para clasificar el fallo.
            code = error.pgcode
            if code == "42P01" or code == "42703":
                message = "Esquema PostgreSQL ausente o incompatible; ejecute --init-db para una instalación nueva."
            elif code:
                message = f"PostgreSQL rechazó la operación (SQLSTATE {code})."
            else:
                message = "No se pudo conectar o completar la operación en PostgreSQL. Revise conexión y configuración."
            raise DatabaseError(message) from None
        finally:
            if connection is not None:
                connection.close()

    def initialize(self):
        script = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.transaction() as cursor:
            cursor.execute(script)

    def check_schema(self):
        counts = ", ".join(COUNT_COLUMNS.values())
        with self.transaction() as cursor:
            cursor.execute(f"SELECT id, started_at, finished_at, mode, status, files_found, "
                           f"files_completed, files_failed, {counts} FROM public.processing_runs LIMIT 0")
            cursor.execute(f"SELECT id, run_id, source_name, source_path, source_format, source_sha256, "
                           f"sheet_name, status, started_at, finished_at, valid_output_path, "
                           f"rejected_output_path, error_message, {counts} FROM public.processed_files LIMIT 0")
            cursor.execute("SELECT id, processed_file_id, row_type, row_number, data, validation_errors "
                           "FROM public.processed_records LIMIT 0")

    def start_run(self, mode):
        with self.transaction() as cursor:
            cursor.execute("INSERT INTO public.processing_runs (mode) VALUES (%s) RETURNING id", (mode,))
            return cursor.fetchone()["id"]

    def set_files_found(self, run_id, count):
        with self.transaction() as cursor:
            cursor.execute("UPDATE public.processing_runs SET files_found = %s WHERE id = %s", (count, run_id))

    def save_file(self, run_id, info, result=None, error_message=None):
        completed = result is not None and error_message is None
        counts = [result.summary[key] for key in COUNT_COLUMNS] if completed else [None] * 6
        values = [run_id, info["source_name"], info["source_path"], info["source_format"],
                  info.get("source_sha256"), info.get("sheet_name"),
                  "COMPLETED" if completed else "FAILED", info["started_at"], utc_now(),
                  *counts, info["valid_output_path"], info["rejected_output_path"],
                  safe_message(error_message) if error_message is not None else None]
        columns = ("run_id, source_name, source_path, source_format, source_sha256, sheet_name, "
                   "status, started_at, finished_at, " + ", ".join(COUNT_COLUMNS.values()) +
                   ", valid_output_path, rejected_output_path, error_message")
        with self.transaction() as cursor:
            cursor.execute(f"INSERT INTO public.processed_files ({columns}) "
                           f"VALUES ({', '.join(['%s'] * len(values))}) RETURNING id", values)
            file_id = cursor.fetchone()["id"]
            if completed:
                for row_type, rows in (("VALID", result.valid_rows), ("REJECTED", result.rejected_rows)):
                    for number, row in enumerate(rows, start=1):
                        cursor.execute(
                            "INSERT INTO public.processed_records "
                            "(processed_file_id, row_type, row_number, data, validation_errors) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (file_id, row_type, number, self.json(row["data"]), self.json(row["validation_errors"])),
                        )
        return file_id

    def finish_run(self, run_id):
        # La base calcula los totales: nunca sumar filas cuya transacción falló.
        aggregates = ", ".join(f"COALESCE(SUM({column}) FILTER (WHERE status = 'COMPLETED'), 0) AS {column}"
                               for column in COUNT_COLUMNS.values())
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) FILTER (WHERE status = 'COMPLETED') AS completed, "
                           f"{aggregates} FROM public.processed_files WHERE run_id = %s", (run_id,))
            totals = cursor.fetchone()
            cursor.execute("SELECT files_found FROM public.processing_runs WHERE id = %s", (run_id,))
            found = cursor.fetchone()["files_found"]
            completed = totals["completed"]
            failed = found - completed
            status = "FAILED" if completed == 0 else ("PARTIAL" if failed else "COMPLETED")
            assignments = ", ".join(f"{column} = %s" for column in COUNT_COLUMNS.values())
            cursor.execute(f"UPDATE public.processing_runs SET finished_at = CURRENT_TIMESTAMP, "
                           f"status = %s, files_completed = %s, files_failed = %s, {assignments} WHERE id = %s",
                           [status, completed, failed, *[totals[c] for c in COUNT_COLUMNS.values()], run_id])
        return status

    def history(self, limit):
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM public.processing_runs ORDER BY started_at DESC, id DESC LIMIT %s", (limit,))
            return cursor.fetchall()

    def run_detail(self, run_id):
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM public.processing_runs WHERE id = %s", (run_id,))
            run = cursor.fetchone()
            if run is None:
                return None, []
            cursor.execute("SELECT * FROM public.processed_files WHERE run_id = %s ORDER BY id", (run_id,))
            return run, cursor.fetchall()
