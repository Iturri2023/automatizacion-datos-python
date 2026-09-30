import csv
from pathlib import Path
import tempfile
import unittest

from src.processor import CSVValidationError, REQUIRED_COLUMNS, process_csv


class ProcessorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "input.csv"
        self.output = Path(self.temp.name) / "processed" / "output.csv"
        self.rejected = Path(self.temp.name) / "processed" / "rejected.csv"
        self.row = ["001", "Cliente Alfa", "alfa@example.invalid", "0000001",
                    "2026-01-10", "Ciudad Norte", "12.50"]

    def write_csv(self, rows, columns=REQUIRED_COLUMNS):
        with self.source.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows)

    def read_output(self, path=None):
        with (path or self.output).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_removes_exact_duplicates_and_preserves_source(self):
        self.write_csv([self.row, self.row])
        original = self.source.read_bytes()
        result = process_csv(self.source, self.output, self.rejected)
        self.assertEqual(result, {"originales": 2, "duplicados": 1,
                                  "procesados": 1, "con_faltantes": 0, "validos": 1, "rechazados": 0})
        self.assertEqual(len(self.read_output()), 1)
        self.assertEqual(self.read_output()[0]["telefono"], "0000001")
        self.assertEqual(self.source.read_bytes(), original)

    def test_normalizes_spaces(self):
        self.row[1] = "  Cliente \t  Alfa  "
        self.row[5] = " Ciudad   Norte "
        self.write_csv([self.row])
        process_csv(self.source, self.output, self.rejected)
        row = self.read_output()[0]
        self.assertEqual(row["nombre"], "Cliente Alfa")
        self.assertEqual(row["ciudad"], "Ciudad Norte")

    def test_rejects_missing_columns(self):
        self.write_csv([], columns=["id_cliente", "nombre"])
        with self.assertRaisesRegex(CSVValidationError, "Faltan columnas obligatorias: email"):
            process_csv(self.source, self.output, self.rejected)
        self.assertFalse(self.output.exists())

    def test_counts_rows_with_missing_values_once_after_deduplication(self):
        self.row[2] = ""
        self.row[3] = "   "
        self.write_csv([self.row, self.row])
        result = process_csv(self.source, self.output, self.rejected)
        self.assertEqual(result["con_faltantes"], 1)
        self.assertEqual(self.read_output(self.rejected)[0]["telefono"], "")

    def test_rejects_missing_file(self):
        with self.assertRaisesRegex(FileNotFoundError, "No existe el archivo"):
            process_csv(self.source, self.output, self.rejected)

    def test_rejects_empty_csv_and_header_without_records(self):
        for content in ("", "\n", ",".join(REQUIRED_COLUMNS) + "\n"):
            with self.subTest(content=content):
                self.source.write_text(content, encoding="utf-8")
                with self.assertRaises(CSVValidationError):
                    process_csv(self.source, self.output, self.rejected)
                self.assertFalse(self.output.exists())

    def test_rejects_overwriting_source(self):
        self.write_csv([self.row])
        original = self.source.read_bytes()
        with self.assertRaisesRegex(CSVValidationError, "distinta del archivo original"):
            process_csv(self.source, self.source, self.rejected)
        self.assertEqual(self.source.read_bytes(), original)

    def test_rejects_wrong_field_count(self):
        self.write_csv([self.row[:-1]])
        with self.assertRaisesRegex(CSVValidationError, "6 campos; se esperaban 7"):
            process_csv(self.source, self.output, self.rejected)
        self.assertFalse(self.output.exists())

    def test_deduplicates_before_normalizing(self):
        variant = self.row.copy()
        variant[1] = "  Cliente Alfa  "
        self.write_csv([self.row, variant])
        result = process_csv(self.source, self.output, self.rejected)
        self.assertEqual(result["duplicados"], 0)
        self.assertEqual(result["procesados"], 2)

    def test_value_formats(self):
        cases = {
            "email": (
                ["alfa@example.invalid", "a@b.c", "a+b@sub.example.invalid"],
                ["a", "a@@b.c", "@b.c", "a@", "a@bc", "a@.b", "a@b.",
                 "a@b..c", "a b@c.d", "a@b c.d"],
            ),
            "telefono": (
                ["0000000", "+0000000", "123456789012345", "+123456789012345"],
                ["123456", "1234567890123456", "+", "12+345678", "++1234567",
                 "123-4567", "(123)4567", "123 4567", "１２３４５６７", "١٢٣٤٥٦٧"],
            ),
            "fecha_registro": (
                ["2024-02-29", "2000-02-29", "0001-01-01", "9999-12-31"],
                ["2023-02-29", "1900-02-29", "2026-04-31", "2026-13-01",
                 "2026-01-00", "0000-01-01", "2026-1-01", "01/01/2026",
                 "20260101", "2026-01-01T00:00:00", "２０２６-01-01"],
            ),
            "monto_compra": (
                ["0", "0.00", "12", "12.5", "12.50", "0012.50"],
                ["-1", "+1", "12,50", "$12", "1e3", "NaN", "Infinity",
                 "12.", ".50", "12.500", "1 000", "１２", "١٢"],
            ),
        }
        for field, (valid, invalid) in cases.items():
            for accepted, values in ((True, valid), (False, invalid)):
                for value in values:
                    with self.subTest(field=field, value=value):
                        row = dict(zip(REQUIRED_COLUMNS, self.row))
                        row[field] = value
                        self.write_csv([list(row.values())])
                        result = process_csv(self.source, self.output, self.rejected)
                        if accepted:
                            self.assertEqual(result["validos"], 1)
                            self.assertEqual(self.read_output()[0][field], value)
                            self.assertEqual(self.read_output(self.rejected), [])
                        else:
                            self.assertEqual(result["rechazados"], 1)
                            self.assertEqual(self.read_output(), [])
                            errors = self.read_output(self.rejected)[0]["errores_validacion"].split("; ")
                            self.assertEqual(len(errors), 1)
                            self.assertTrue(errors[0].startswith(field + ": "))

    def test_all_required_fields_empty_have_only_required_error(self):
        self.write_csv([[" \t "] * len(REQUIRED_COLUMNS)])
        result = process_csv(self.source, self.output, self.rejected)
        errors = self.read_output(self.rejected)[0]["errores_validacion"].split("; ")
        self.assertEqual(errors, [f"{name}: campo obligatorio vacío" for name in REQUIRED_COLUMNS])
        self.assertEqual(result["con_faltantes"], 1)
        self.assertEqual(result["validos"], 0)
        self.assertEqual(result["rechazados"], 1)
        self.assertEqual(self.read_output(), [])
        with self.output.open(encoding="utf-8", newline="") as stream:
            self.assertEqual(next(csv.reader(stream)), list(REQUIRED_COLUMNS))

    def test_partition_preserves_column_order_text_and_counts(self):
        columns = ["nota"] + list(reversed(REQUIRED_COLUMNS))
        good = ["   "] + list(reversed(self.row))
        invalid = self.row.copy()
        invalid[0] = "002"
        invalid[2] = " correo-invalido "
        invalid[4] = "2023-02-29"
        invalid[6] = "-1"
        bad = [" dato   ficticio "] + list(reversed(invalid))
        self.write_csv([good, bad, good], columns)
        original = self.source.read_bytes()
        result = process_csv(self.source, self.output, self.rejected)
        self.assertEqual(result, {"originales": 3, "duplicados": 1, "procesados": 2,
                                  "con_faltantes": 1, "validos": 1, "rechazados": 1})
        self.assertEqual(result["originales"], result["duplicados"] + result["procesados"])
        self.assertEqual(result["procesados"], result["validos"] + result["rechazados"])
        valid = self.read_output()[0]
        rejected = self.read_output(self.rejected)[0]
        self.assertEqual(list(valid), columns)
        self.assertEqual(list(rejected), columns + ["errores_validacion"])
        self.assertEqual(valid["nota"], "")
        self.assertEqual(valid["id_cliente"], "001")
        self.assertEqual(valid["telefono"], "0000001")
        self.assertEqual(valid["monto_compra"], "12.50")
        self.assertEqual(rejected["nota"], "dato ficticio")
        self.assertEqual(rejected["email"], "correo-invalido")
        self.assertEqual([error.split(":")[0] for error in
                          rejected["errores_validacion"].split("; ")],
                         ["email", "fecha_registro", "monto_compra"])
        self.assertEqual(self.source.read_bytes(), original)

    def test_second_execution_clears_stale_rejections(self):
        invalid = self.row.copy()
        invalid[2] = "invalido"
        self.write_csv([invalid])
        process_csv(self.source, self.output, self.rejected)
        self.assertEqual(len(self.read_output(self.rejected)), 1)
        self.write_csv([self.row])
        result = process_csv(self.source, self.output, self.rejected)
        self.assertEqual(result["validos"], 1)
        self.assertEqual(result["rechazados"], 0)
        self.assertEqual(len(self.read_output()), 1)
        self.assertEqual(self.read_output(self.rejected), [])
        with self.rejected.open(encoding="utf-8", newline="") as stream:
            self.assertEqual(next(csv.reader(stream)), list(REQUIRED_COLUMNS) + ["errores_validacion"])

    def test_structural_errors_leave_both_previous_outputs_untouched(self):
        self.write_csv([self.row])
        process_csv(self.source, self.output, self.rejected)
        originals = [path.read_bytes() for path in (self.output, self.rejected)]
        for columns, rows in (
            (list(REQUIRED_COLUMNS) + ["errores_validacion"], [self.row + [""]]),
            (list(REQUIRED_COLUMNS) + ["nombre"], [self.row + [""]]),
            (list(REQUIRED_COLUMNS) + [""], [self.row + [""]]),
            (list(REQUIRED_COLUMNS), [self.row, self.row[:-1]]),
        ):
            with self.subTest(columns=columns, rows=rows):
                self.write_csv(rows, columns)
                with self.assertRaises(CSVValidationError) as context:
                    process_csv(self.source, self.output, self.rejected)
                if "errores_validacion" in columns:
                    self.assertIn("reservado", str(context.exception))
                self.assertEqual([path.read_bytes() for path in (self.output, self.rejected)], originals)

    def test_rejects_conflicting_output_paths(self):
        self.write_csv([self.row])
        original = self.source.read_bytes()
        for valid_path, rejected_path in ((self.output, self.source), (self.output, self.output)):
            with self.subTest(valid=valid_path, rejected=rejected_path):
                with self.assertRaises(CSVValidationError):
                    process_csv(self.source, valid_path, rejected_path)
        self.assertEqual(self.source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
