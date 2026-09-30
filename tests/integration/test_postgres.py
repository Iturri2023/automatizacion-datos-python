"""Integración REAL. Ejecutar mediante scripts/test_postgres.py, no con mocks de SQL."""

import contextlib
import hashlib
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from openpyxl import Workbook

import main
from src.storage import Database, DatabaseError


@unittest.skipUnless(os.environ.get("ISOLATED_POSTGRES_TEST") == "1",
                     "Requiere el clúster temporal de scripts/test_postgres.py")
class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        from psycopg2 import sql
        self.driver, self.sql = psycopg2, sql
        self.name = "test_automatizacion_" + uuid4().hex
        self.admin_parameters = {"host": os.environ["PGHOST"], "port": os.environ["PGPORT"],
                                 "user": os.environ["PGUSER"], "dbname": "postgres",
                                 "password": os.environ["PGPASSWORD"]}
        # Conectar solo al servidor efímero que creó el ejecutor.
        self.assertEqual(os.environ["PGHOST"], "127.0.0.1")
        connection = psycopg2.connect(**self.admin_parameters)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.name)))
        finally:
            connection.close()
        self.addCleanup(self.drop_owned_database)
        env_patch = patch.dict(os.environ, {"PGDATABASE": self.name})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = Database()
        self.db.initialize()
        self.source = main.BASE_DIR / "data" / "raw" / "clientes.csv"

    def drop_owned_database(self):
        # Nombre generado por este setUp, jamás tomado de PGDATABASE del usuario.
        assert self.name.startswith("test_automatizacion_") and len(self.name) == 52
        connection = self.driver.connect(**self.admin_parameters)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(self.sql.SQL("DROP DATABASE {}").format(self.sql.Identifier(self.name)))
        finally:
            connection.close()

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main.main([str(arg) for arg in args])
        self.assertNotIn(os.environ["PGPASSWORD"], out.getvalue() + err.getvalue())
        return status, out.getvalue(), err.getvalue()

    def store(self, source=None):
        return self.cli("--store-db", "--input", source or self.source, "--output-dir", self.root / "out")

    def query(self, query, parameters=()):
        with self.db.transaction() as cursor:
            cursor.execute(query, parameters)
            return cursor.fetchall()

    def test_single_json_hash_repeat_history_and_idempotent_initialization(self):
        original = self.source.read_bytes()
        self.assertEqual(self.store()[0], 0)
        run = self.db.history(1)[0]
        self.assertEqual((run["status"], run["valid_count"], run["rejected_count"]), ("COMPLETED", 5, 3))
        _, files = self.db.run_detail(run["id"])
        self.assertEqual(files[0]["source_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(self.source.read_bytes(), original)
        rows = self.query("SELECT * FROM public.processed_records ORDER BY id")
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]["validation_errors"], [])
        self.assertEqual(rows[0]["data"]["telefono"], "0000000001")
        self.assertEqual(rows[-1]["validation_errors"], [
            {"field": "ciudad", "reason": "campo obligatorio vacío"},
            {"field": "monto_compra", "reason": "campo obligatorio vacío"}])
        self.assertNotIn("errores_validacion", rows[-1]["data"])
        self.assertEqual(self.cli("--init-db")[0], 0)
        self.assertEqual(self.cli("--init-db")[0], 0)
        self.assertEqual(len(self.query("SELECT * FROM public.processed_records")), 8)
        self.assertEqual(self.store()[0], 0)
        newest = self.db.history(1)[0]
        self.assertGreater(newest["id"], run["id"])
        self.assertEqual(len(self.db.history(10)), 2)
        self.assertEqual(self.cli("--history", "1")[1].count("Ejecución "), 1)
        status, output, _ = self.cli("--run-detail", newest["id"])
        self.assertEqual(status, 0)
        self.assertIn(files[0]["source_sha256"], output)
        self.assertNotIn("Cliente Alfa", output)
        self.assertEqual(self.cli("--run-detail", "999999")[0], 1)

    def test_complete_and_partial_batches_sum_only_completed_files(self):
        inputs = self.root / "in"
        inputs.mkdir()
        for name in ("clientes.csv", "clientes.xlsx"):
            shutil.copyfile(main.BASE_DIR / "data" / "raw" / name, inputs / name)
        self.assertEqual(self.cli("--store-db", "--input-dir", inputs, "--output-dir", self.root / "out")[0], 0)
        self.assertEqual(self.db.history(1)[0]["status"], "COMPLETED")
        (inputs / "a_defectuoso.csv").write_text("id_cliente\n999\n", encoding="utf-8")
        self.assertEqual(self.cli("--store-db", "--input-dir", inputs, "--output-dir", self.root / "out")[0], 1)
        run = self.db.history(1)[0]
        self.assertEqual((run["status"], run["files_completed"], run["files_failed"]), ("PARTIAL", 2, 1))
        self.assertEqual([run[key] for key in ("original_count", "duplicate_count", "processed_count",
                                              "missing_count", "valid_count", "rejected_count")], [16, 3, 13, 4, 7, 6])
        _, files = self.db.run_detail(run["id"])
        failed = files[0]
        self.assertIsNone(failed["original_count"])
        self.assertIsNotNone(failed["source_sha256"])
        self.assertIn("Faltan columnas", failed["error_message"])
        self.assertEqual(self.query("SELECT * FROM public.processed_records WHERE processed_file_id=%s",
                                    (failed["id"],)), [])

    def test_failed_missing_and_empty_directory_executions(self):
        source = self.root / "missing.csv"
        self.assertEqual(self.store(source)[0], 1)
        run = self.db.history(1)[0]
        self.assertEqual((run["status"], run["files_completed"], run["files_failed"]), ("FAILED", 0, 1))
        _, files = self.db.run_detail(run["id"])
        self.assertIsNone(files[0]["source_sha256"])
        self.assertIsNone(files[0]["valid_count"])
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(self.cli("--store-db", "--input-dir", empty)[0], 1)
        self.assertEqual(self.db.history(1)[0]["status"], "FAILED")
        self.assertEqual(self.db.history(1)[0]["files_found"], 0)

    def test_excel_error_and_additional_columns_are_json_objects(self):
        source = self.root / "errors.xlsx"
        book = Workbook()
        book.active.title = "Datos"
        book.active.append(["id_cliente", "nombre", "email", "telefono", "fecha_registro", "ciudad", "monto_compra", "nota"])
        book.active.append(["001", " Ficticio ", "a@example.invalid", "0000001", "2026-01-01", "Ciudad", "0", "#N/A"])
        book.save(source)
        book.close()
        before = source.read_bytes()
        self.assertEqual(self.store(source)[0], 0)
        row = self.query("SELECT * FROM public.processed_records")[0]
        self.assertEqual(row["data"]["nota"], "#N/A")
        self.assertEqual(row["data"]["nombre"], "Ficticio")
        self.assertEqual(row["validation_errors"], [{"field": "nota", "reason": "error de celda Excel (#N/A)"}])
        self.assertEqual(self.query("SELECT sheet_name FROM public.processed_files")[0]["sheet_name"], "Datos")
        self.assertEqual(source.read_bytes(), before)

    def test_write_failure_has_no_counts_or_records(self):
        with patch("main.write_outputs", side_effect=PermissionError("Fallo de disco simulado")):
            self.assertEqual(self.store()[0], 1)
        self.assertEqual(self.db.history(1)[0]["status"], "FAILED")
        self.assertEqual(self.query("SELECT * FROM public.processed_records"), [])
        row = self.query("SELECT * FROM public.processed_files")[0]
        self.assertEqual(row["status"], "FAILED")
        self.assertIsNone(row["processed_count"])

    def test_actual_sql_failure_rolls_back_file_and_records_then_batch_continues(self):
        # Trigger de prueba SOLO en esta base efímera: falla después de insertar
        # al menos una fila, para comprobar rollback real y no solo un mock.
        with self.db.transaction() as cursor:
            cursor.execute("""CREATE FUNCTION fail_test_row() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.data->>'id_cliente' = '002' THEN
                RAISE EXCEPTION 'fallo SQL de prueba'; END IF; RETURN NEW; END $$;
                CREATE TRIGGER fail_test BEFORE INSERT ON public.processed_records
                FOR EACH ROW EXECUTE FUNCTION fail_test_row();""")
        inputs = self.root / "in"
        inputs.mkdir()
        shutil.copyfile(self.source, inputs / "clientes.csv")
        shutil.copyfile(main.BASE_DIR / "data" / "raw" / "clientes.xlsx", inputs / "clientes.xlsx")
        status, _, stderr = self.cli("--store-db", "--input-dir", inputs, "--output-dir", self.root / "out")
        self.assertEqual(status, 1)
        self.assertIn("salidas CSV existen, pero no quedaron almacenadas", stderr)
        self.assertTrue((self.root / "out" / "clientes.csv" / "validos.csv").exists())
        run = self.db.history(1)[0]
        self.assertEqual((run["status"], run["processed_count"]), ("PARTIAL", 5))
        _, files = self.db.run_detail(run["id"])
        self.assertEqual([row["status"] for row in files], ["FAILED", "COMPLETED"])
        self.assertIsNone(files[0]["processed_count"])
        self.assertEqual(len(self.query("SELECT * FROM public.processed_records")), 5)

    def test_schema_constraints_cascade_and_no_partial_records(self):
        self.assertEqual(self.store()[0], 0)
        run = self.db.history(1)[0]
        _, files = self.db.run_detail(run["id"])
        for query, params in (
            ("UPDATE public.processing_runs SET valid_count=-1 WHERE id=%s", (run["id"],)),
            ("UPDATE public.processing_runs SET status='INVALID' WHERE id=%s", (run["id"],)),
            ("UPDATE public.processing_runs SET finished_at=started_at-interval '1 second' WHERE id=%s", (run["id"],)),
            ("UPDATE public.processed_files SET original_count=NULL WHERE id=%s", (files[0]["id"],)),
        ):
            with self.subTest(query=query), self.assertRaises(DatabaseError):
                with self.db.transaction() as cursor:
                    cursor.execute(query, params)
        with self.db.transaction() as cursor:
            cursor.execute("DELETE FROM public.processing_runs WHERE id=%s", (run["id"],))
        self.assertEqual(self.query("SELECT * FROM public.processed_files"), [])
        self.assertEqual(self.query("SELECT * FROM public.processed_records"), [])

    def test_missing_schema_and_authentication_fail_before_outputs(self):
        output = self.root / "out" / "clientes.csv" / "validos.csv"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"salida anterior")
        with self.db.transaction() as cursor:
            cursor.execute("ALTER TABLE public.processed_records RENAME TO records_temporarily_unavailable")
        status, _, error = self.store()
        self.assertEqual(status, 1)
        self.assertIn("Esquema", error)
        self.assertEqual(output.read_bytes(), b"salida anterior")
        self.assertEqual(self.db.history(10), [])
        with patch.dict(os.environ, {"PGPASSWORD": "wrong_synthetic_password"}):
            status, _, error = self.store()
        self.assertEqual(status, 1)
        self.assertNotIn("wrong_synthetic_password", error)
        self.assertEqual(output.read_bytes(), b"salida anterior")

    def test_default_mode_and_destination_conflict_are_traced(self):
        self.assertEqual(self.cli("--store-db", "--output-dir", self.root / "default")[0], 0)
        self.assertEqual(self.db.history(1)[0]["mode"], "default")
        self.assertTrue((self.root / "default" / "clientes_procesados.csv").exists())
        source = self.root / "clientes.csv"
        shutil.copyfile(self.source, source)
        original = source.read_bytes()
        status, _, _ = self.cli("--store-db", "--input", source, "--output-dir", self.root)
        self.assertEqual(status, 1)
        run = self.db.history(1)[0]
        self.assertEqual((run["status"], run["files_found"], run["files_failed"]), ("FAILED", 1, 1))
        _, files = self.db.run_detail(run["id"])
        self.assertEqual(files[0]["source_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
