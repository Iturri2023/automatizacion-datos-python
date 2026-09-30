import contextlib
import csv
from datetime import date, datetime
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import Workbook

import main
from src.processor import CSVValidationError, REQUIRED_COLUMNS, process_file


class ExcelAndCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "clientes.xlsx"
        self.valid = self.root / "salidas" / "validos.csv"
        self.rejected = self.root / "salidas" / "rechazados.csv"
        self.row = ["001", "Cliente Ficticio", "alfa@example.invalid", "0000001",
                    "2024-02-29", "Ciudad Norte", "12.50"]

    def workbook(self, rows, columns=REQUIRED_COLUMNS):
        book = Workbook()
        sheet = book.active
        sheet.title = "Clientes"
        if columns is not None:
            sheet.append(list(columns))
        for row in rows:
            sheet.append(row)
        return book

    def save(self, book, path=None):
        book.save(path or self.source)
        book.close()

    def csv_file(self, path, rows):
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(REQUIRED_COLUMNS)
            writer.writerows(rows)

    def output_rows(self, path):
        with path.open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = main.main([str(arg) for arg in args])
        return status, output.getvalue(), errors.getvalue()

    def test_text_equivalence_deduplication_blanks_and_first_sheet(self):
        missing = self.row.copy()
        missing[2] = ""
        spaced = self.row.copy()
        spaced[1] = "  Cliente  Ficticio "
        rows = [self.row, self.row, missing, spaced]
        book = self.workbook(rows)
        book.active.append([None] * 7)
        book.create_sheet("Ignorada").append(["=1+1"])
        self.save(book)
        csv_path = self.root / "clientes.csv"
        self.csv_file(csv_path, rows)
        originals = {path: path.read_bytes() for path in (csv_path, self.source)}
        excel_summary = process_file(self.source, self.valid, self.rejected)
        self.assertEqual(excel_summary.pop("hoja"), "Clientes")
        excel_outputs = [path.read_bytes() for path in (self.valid, self.rejected)]
        csv_summary = process_file(csv_path, self.valid, self.rejected)
        self.assertEqual(excel_summary, csv_summary)
        self.assertEqual(csv_summary, dict(originales=4, duplicados=1, procesados=3,
                                           con_faltantes=1, validos=2, rechazados=1))
        self.assertEqual(excel_outputs, [path.read_bytes() for path in (self.valid, self.rejected)])
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.output_rows(self.valid)[0]["telefono"], "0000001")

    def test_native_types_dates_and_cell_errors(self):
        rows = []
        for index in range(8):
            row = self.row.copy() + [False]
            row[0] = index + 1
            rows.append(row)
        rows[0][4], rows[0][6] = date(2024, 2, 29), 0
        rows[1][4], rows[1][6], rows[1][3] = datetime(2024, 2, 29), 12.5, 1234567
        rows[2][4] = datetime(2024, 2, 29, 0, 0, 1)
        rows[3][6] = 12.345
        rows[4][6] = True
        rows[5][6], rows[5][7] = "#DIV/0!", "#N/A"
        rows[7][6] = 1e-7
        book = self.workbook(rows, list(REQUIRED_COLUMNS) + ["nota"])
        book.active["D3"].number_format = "0000000000"
        book.active["G5"].number_format = "0.00"  # No redondear según formato visual.
        self.save(book)
        summary = process_file(self.source, self.valid, self.rejected)
        self.assertEqual((summary["validos"], summary["rechazados"]), (3, 5))
        valid = self.output_rows(self.valid)
        self.assertEqual([row["id_cliente"] for row in valid], ["1", "2", "7"])
        self.assertEqual(valid[0]["monto_compra"], "0")
        self.assertEqual(valid[0]["fecha_registro"], "2024-02-29")
        self.assertEqual(valid[0]["nota"], "FALSE")
        self.assertEqual(valid[1]["monto_compra"], "12.5")
        self.assertEqual(valid[1]["telefono"], "1234567")
        rejected = self.output_rows(self.rejected)
        self.assertEqual(rejected[0]["fecha_registro"], "2024-02-29T00:00:01")
        self.assertEqual(rejected[1]["monto_compra"], "12.345")
        self.assertEqual(rejected[2]["monto_compra"], "TRUE")
        self.assertIn("monto_compra: error de celda Excel", rejected[3]["errores_validacion"])
        self.assertIn("nota: error de celda Excel", rejected[3]["errores_validacion"])
        self.assertEqual(rejected[4]["monto_compra"], "0.0000001")

    def test_cell_error_in_duplicate_additional_column_is_not_hidden(self):
        book = self.workbook([self.row + ["#N/A"], self.row + ["#N/A"]],
                             list(REQUIRED_COLUMNS) + ["nota"])
        book.active["H2"].data_type = "s"
        self.save(book)
        summary = process_file(self.source, self.valid, self.rejected)
        self.assertEqual((summary["duplicados"], summary["rechazados"]), (1, 1))
        self.assertIn("nota: error de celda Excel", self.output_rows(self.rejected)[0]["errores_validacion"])

    def test_formula_location_and_unchanged_previous_outputs(self):
        self.save(self.workbook([self.row]))
        process_file(self.source, self.valid, self.rejected)
        previous = [path.read_bytes() for path in (self.valid, self.rejected)]
        book = self.workbook([self.row, self.row])
        book.active["G3"] = "=1+1"
        self.save(book)
        original = self.source.read_bytes()
        with self.assertRaisesRegex(CSVValidationError, "Clientes.*G3.*valores"):
            process_file(self.source, self.valid, self.rejected)
        self.assertEqual(previous, [path.read_bytes() for path in (self.valid, self.rejected)])
        self.assertEqual(self.source.read_bytes(), original)

    def test_invalid_headers_empty_books_and_data_under_unnamed_column(self):
        for columns, rows in (
            (None, []), (REQUIRED_COLUMNS, []),
            ([None] + list(REQUIRED_COLUMNS[1:]), [self.row]),
            ([123] + list(REQUIRED_COLUMNS[1:]), [self.row]),
            (list(REQUIRED_COLUMNS) + ["nombre"], [self.row + ["x"]]),
            (list(REQUIRED_COLUMNS) + ["errores_validacion"], [self.row + ["x"]]),
            (list(REQUIRED_COLUMNS) + ["#N/A"], [self.row + ["x"]]),
            (list(REQUIRED_COLUMNS[:-1]), [self.row[:-1]]),
            (REQUIRED_COLUMNS, [self.row + ["sin encabezado"]]),
        ):
            with self.subTest(columns=columns, rows=rows):
                self.save(self.workbook(rows, columns))
                with self.assertRaises(CSVValidationError):
                    process_file(self.source, self.valid, self.rejected)
                self.assertFalse(self.valid.exists())
                self.assertFalse(self.rejected.exists())

    def test_xlsx_replaces_previous_rejections(self):
        invalid = self.row.copy()
        invalid[2] = None
        self.save(self.workbook([invalid]))
        process_file(self.source, self.valid, self.rejected)
        self.assertEqual(self.output_rows(self.valid), [])
        self.save(self.workbook([self.row]))
        process_file(self.source, self.valid, self.rejected)
        self.assertEqual(self.output_rows(self.rejected), [])
        self.assertEqual(len(self.output_rows(self.valid)), 1)

    def test_batch_mixed_formats_failure_totals_order_and_preservation(self):
        inputs = self.root / "entradas"
        inputs.mkdir()
        csv_path, excel_path = inputs / "clientes.CSV", inputs / "clientes.XLSX"
        self.csv_file(csv_path, [self.row, self.row])
        invalid = self.row.copy()
        invalid[2] = None
        self.save(self.workbook([self.row, invalid]), excel_path)
        (inputs / "a_defectuoso.csv").write_text("id_cliente\n1\n", encoding="utf-8")
        (inputs / "~$temporal.xlsx").write_bytes(b"ignorar")
        (inputs / "ignorar.xlsm").write_bytes(b"ignorar")
        (inputs / "subcarpeta").mkdir()
        (inputs / "subcarpeta" / "ignorar.csv").write_text("ignorar")
        originals = {path: path.read_bytes() for path in inputs.iterdir() if path.is_file()}
        output = self.root / "resultados"
        status, stdout, stderr = self.cli("--input-dir", inputs, "--output-dir", output)
        self.assertEqual(status, 1)
        self.assertIn("a_defectuoso.csv", stderr)
        self.assertIn("No se actualizaron", stderr)
        self.assertIn("Archivos encontrados: 3", stdout)
        self.assertIn("Archivos completados: 2", stdout)
        self.assertIn("Archivos fallidos: 1", stdout)
        totals = stdout.split("Totales de registros (solo archivos completados):")[1]
        for label, value in zip(main.COUNT_LABELS.values(), [4, 1, 3, 1, 2, 1]):
            self.assertIn(f"{label}: {value}", totals)
        self.assertLess(stdout.index("clientes.CSV"), stdout.index("clientes.XLSX"))
        self.assertIn("Hoja utilizada (primera): Clientes", stdout)
        for name in ("clientes.CSV", "clientes.XLSX"):
            self.assertTrue((output / name / "validos.csv").is_file())
            self.assertTrue((output / name / "rechazados.csv").is_file())
        self.assertFalse((output / "a_defectuoso.csv").exists())
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_default_invocation_and_real_argument_exit_codes(self):
        (self.root / "data" / "raw").mkdir(parents=True)
        shutil.copyfile(main.BASE_DIR / "data" / "raw" / "clientes.csv",
                        self.root / "data" / "raw" / "clientes.csv")
        with patch.object(main, "BASE_DIR", self.root):
            status, stdout, stderr = self.cli()
        self.assertEqual((status, stderr), (0, ""))
        for label, value in zip(main.COUNT_LABELS.values(), [10, 2, 8, 3, 5, 3]):
            self.assertIn(f"{label}: {value}", stdout)
        for name in ("clientes_procesados.csv", "clientes_rechazados.csv"):
            self.assertTrue((self.root / "data" / "processed" / name).is_file())
        self.save(self.workbook([self.row]))
        command = [sys.executable, "-X", "utf8", str(main.BASE_DIR / "main.py")]
        for arguments, expected in (
            (["--input", str(self.source), "--output-dir", str(self.root / "cli")], 0),
            (["--input", str(self.root / "missing.csv")], 1),
            (["--input", str(self.source), "--input-dir", str(self.root)], 2),
            (["--unknown"], 2),
        ):
            result = subprocess.run(command + arguments, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, expected, result.stderr)

    def test_missing_empty_unsupported_corrupt_and_unreadable_inputs(self):
        for folder in (self.root / "missing", self.root):
            self.assertEqual(self.cli("--input-dir", folder)[0], 1)
        for suffix in (".xls", ".xlsm", ".xlsx"):
            path = self.root / ("defectuoso" + suffix)
            path.write_bytes(b"no es un libro")
            self.assertEqual(self.cli("--input", path)[0], 1)
        with ZipFile(self.source, "w") as archive:
            archive.writestr("arbitrary.txt", "libro incompleto")
        self.assertEqual(self.cli("--input", self.source)[0], 1)
        self.save(self.workbook([self.row]))
        with patch("src.processor.read_input", side_effect=PermissionError("Acceso denegado")):
            status, _, stderr = self.cli("--input", self.source)
        self.assertEqual(status, 1)
        self.assertIn("No se actualizaron", stderr)
        with patch("src.processor.read_input", side_effect=RuntimeError("inesperado")):
            with self.assertRaises(RuntimeError):
                self.cli("--input", self.source)
        with patch("src.processor.csv.writer", side_effect=FileNotFoundError("Destino no disponible")):
            status, _, stderr = self.cli("--input", self.source)
        self.assertEqual(status, 1)
        self.assertIn("parciales", stderr)
        self.assertNotIn("No se actualizaron", stderr)

    def test_conflicting_destinations_rejected_before_batch(self):
        self.save(self.workbook([self.row]))
        original = self.source.read_bytes()
        status, _, stderr = self.cli("--input", self.source, "--output-dir", self.root)
        self.assertEqual(status, 1)
        self.assertIn("conflictivo", stderr)
        self.assertEqual(self.source.read_bytes(), original)
        other_input = self.root / "otro.csv"
        self.csv_file(other_input, [self.row])
        # Comprueba colisiones con cualquier entrada, no solo la del mismo trabajo.
        with self.assertRaises(CSVValidationError):
            main.check_destinations([(self.source, other_input, self.rejected),
                                     (other_input, self.valid, self.root / "r.csv")])


if __name__ == "__main__":
    unittest.main()
