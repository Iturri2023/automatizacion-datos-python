"""Pruebas unitarias: no requieren ni conectan a un servidor PostgreSQL."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import main
from src.processor import prepare_file
from src.storage import Database, DatabaseError


class DatabaseUnitTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = main.BASE_DIR / "data" / "raw" / "clientes.csv"
        self.db = Mock()
        self.db.start_run.return_value = 123
        self.db.finish_run.return_value = "COMPLETED"

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = main.main([str(arg) for arg in args])
        return status, output.getvalue(), errors.getvalue()

    def processing_args(self):
        return ["--input", self.source, "--output-dir", self.root, "--store-db"]

    def test_normal_processing_never_opens_database(self):
        with patch("main.open_database", side_effect=AssertionError("No debe conectar")):
            self.assertEqual(self.cli("--input", self.source, "--output-dir", self.root)[0], 0)

    def test_connection_and_schema_fail_before_outputs(self):
        sentinel = self.root / "clientes.csv" / "validos.csv"
        sentinel.parent.mkdir()
        sentinel.write_bytes(b"salida anterior")
        for stage in ("connection", "schema"):
            with self.subTest(stage=stage):
                self.db.check_schema.side_effect = DatabaseError("Esquema ausente") if stage == "schema" else None
                with patch("main.open_database", return_value=self.db,
                           side_effect=DatabaseError("Conexion fallida") if stage == "connection" else None):
                    status, _, _ = self.cli(*self.processing_args())
                self.assertEqual(status, 1)
                self.assertEqual(sentinel.read_bytes(), b"salida anterior")
        self.db.start_run.assert_not_called()

    def test_structured_result_keeps_columns_and_multiple_errors(self):
        result = prepare_file(self.source)
        self.assertEqual(result.valid_rows[0]["validation_errors"], [])
        self.assertEqual(result.rejected_rows[-1]["validation_errors"], [
            {"field": "ciudad", "reason": "campo obligatorio vacío"},
            {"field": "monto_compra", "reason": "campo obligatorio vacío"},
        ])
        self.assertNotIn("errores_validacion", result.rejected_rows[-1]["data"])

    def test_writing_failure_saves_only_failed_file(self):
        with patch("main.open_database", return_value=self.db), \
                patch("main.write_outputs", side_effect=PermissionError("Sin permiso")):
            status, _, errors = self.cli(*self.processing_args())
        self.assertEqual(status, 1)
        self.assertIn("parciales", errors)
        self.db.save_file.assert_called_once()
        self.assertNotIn("result", self.db.save_file.call_args.kwargs)
        self.assertIn("error_message", self.db.save_file.call_args.kwargs)

    def test_database_failure_after_writes_is_reported_and_recorded(self):
        self.db.save_file.side_effect = [DatabaseError("SQL fallido"), 1]
        with patch("main.open_database", return_value=self.db):
            status, _, errors = self.cli(*self.processing_args())
        self.assertEqual(status, 1)
        self.assertIn("salidas CSV existen, pero no quedaron almacenadas", errors)
        self.assertTrue((self.root / "clientes.csv" / "validos.csv").is_file())
        self.assertEqual(len(self.db.save_file.call_args_list), 2)
        self.assertIn("error_message", self.db.save_file.call_args_list[-1].kwargs)

    def test_unavailable_database_reports_failed_history_and_finalization(self):
        self.db.save_file.side_effect = DatabaseError("Sin conexion")
        self.db.finish_run.side_effect = DatabaseError("Sin conexion")
        with patch("main.open_database", return_value=self.db):
            status, _, errors = self.cli(*self.processing_args())
        self.assertEqual(status, 1)
        self.assertIn("No se pudo registrar", errors)
        self.assertIn("RUNNING", errors)

    def test_no_processable_inputs_still_creates_failed_run(self):
        with patch("main.open_database", return_value=self.db):
            status, _, _ = self.cli("--input-dir", self.root, "--store-db")
        self.assertEqual(status, 1)
        self.db.start_run.assert_called_once_with("batch")
        self.db.finish_run.assert_called_once_with(123)
        self.db.save_file.assert_not_called()

    def test_argument_conflicts_and_history_limits(self):
        invalid = (["--history", "0"], ["--history", "101"], ["--history", "abc"],
                   ["--run-detail", "0"], ["--history", "--store-db"],
                   ["--init-db", "--store-db"], ["--history", "--input", "a.csv"],
                   ["--run-detail", "1", "--output-dir", "salidas"],
                   ["--init-db", "--input-dir", "data/raw"])
        with patch("main.open_database") as connect:
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(SystemExit) as context:
                    self.cli(*args)
                self.assertEqual(context.exception.code, 2)
            connect.assert_not_called()
        self.db.history.return_value = []
        with patch("main.open_database", return_value=self.db):
            self.assertEqual(self.cli("--history")[0], 0)
            self.db.history.assert_called_with(10)
            self.assertEqual(self.cli("--history", "100")[0], 0)
            self.db.history.assert_called_with(100)

    def test_password_redacted_and_driver_exception_not_exposed(self):
        secret = "synthetic_password_for_test_only"
        with patch.dict(os.environ, {"PGPASSWORD": secret}), \
                patch("main.open_database", side_effect=DatabaseError("Fallo " + secret)):
            status, stdout, stderr = self.cli(*self.processing_args())
        self.assertEqual(status, 1)
        self.assertNotIn(secret, stdout + stderr)
        db = Database()
        with patch.object(db.driver, "connect", side_effect=db.driver.OperationalError(secret)):
            with self.assertRaises(DatabaseError) as context:
                db.check_schema()
        self.assertNotIn(secret, str(context.exception))
        self.assertTrue(context.exception.__suppress_context__)

    def test_unexpected_errors_are_not_silenced(self):
        with patch("main.open_database", return_value=self.db), \
                patch("main.prepare_file", side_effect=RuntimeError("Error de programación")):
            with self.assertRaises(RuntimeError):
                self.cli(*self.processing_args())


if __name__ == "__main__":
    unittest.main()
