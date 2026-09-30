"""Arranca un clúster PostgreSQL efímero y ejecuta integraciones reales aisladas.

No usa servidores, servicios ni bases existentes. Requiere binarios PostgreSQL.
"""

import argparse
from contextlib import contextmanager
import io
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@contextmanager
def temporary_server(bin_dir):
    suffix = ".exe" if os.name == "nt" else ""
    initdb, pg_ctl = (bin_dir / (name + suffix) for name in ("initdb", "pg_ctl"))
    if not initdb.is_file() or not pg_ctl.is_file():
        raise RuntimeError("No se encontraron initdb y pg_ctl en --pg-bin.")
    previous = os.environ.copy()
    password = secrets.token_urlsafe(32)
    env = {key: value for key, value in previous.items() if not key.startswith("PG")}
    with tempfile.TemporaryDirectory(prefix="automatizacion_pg_test_") as directory:
        root = Path(directory).resolve()
        # Solo este directorio recién creado se eliminará al salir.
        assert root.parent == Path(tempfile.gettempdir()).resolve()
        data = root / "cluster"
        pwfile = root / "password.txt"
        pwfile.write_text(password, encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        def command(arguments):
            # pg_ctl puede dejar handles heredados abiertos en Windows. Un archivo
            # evita esperar indefinidamente por EOF de los pipes del servidor.
            command_log = root / "command.log"
            with command_log.open("wb") as output:
                result = subprocess.run([str(arg) for arg in arguments], env=env,
                                        stdout=output, stderr=subprocess.STDOUT, timeout=60,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result.returncode:
                detail = command_log.read_text(encoding="utf-8", errors="replace").replace(password, "[OCULTA]")
                raise RuntimeError(f"Falló {Path(arguments[0]).name}: {detail}")

        command([initdb, "-D", data, "-U", "test_runner", "--auth=scram-sha-256",
                 "--pwfile", pwfile, "--encoding=UTF8", "--locale=C"])
        started = False
        try:
            command([pg_ctl, "-D", data, "-l", root / "server.log", "-o",
                     f"-h 127.0.0.1 -p {port}", "-w", "start"])
            started = True
            os.environ.clear()
            os.environ.update(env)
            os.environ.update(PGHOST="127.0.0.1", PGPORT=str(port), PGUSER="test_runner",
                              PGPASSWORD=password, PGDATABASE="postgres", PGTZ="America/Bogota",
                              ISOLATED_POSTGRES_TEST="1")
            print("PostgreSQL temporal iniciado en loopback; servidor y bases del usuario sin utilizar.", flush=True)
            yield
        finally:
            os.environ.clear()
            os.environ.update(previous)
            if started:
                command([pg_ctl, "-D", data, "-m", "fast", "-w", "stop"])
    print("Clúster temporal detenido y eliminado.")


def demonstration():
    import contextlib
    import hashlib
    import psycopg2
    from psycopg2 import sql
    import main

    name = "demo_automatizacion_" + uuid4().hex
    admin = psycopg2.connect(dbname="postgres")
    admin.autocommit = True
    created = False
    previous_db = os.environ["PGDATABASE"]
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created = True
        os.environ["PGDATABASE"] = name
        with tempfile.TemporaryDirectory(prefix="demo_historial_") as directory:
            root = Path(directory)
            inputs = root / "in"
            inputs.mkdir()
            originals = {}
            for filename in ("clientes.csv", "clientes.xlsx"):
                source = ROOT / "data" / "raw" / filename
                originals[source] = source.read_bytes()
                shutil.copyfile(source, inputs / filename)
            (inputs / "a_defectuoso.csv").write_text("id_cliente\n999\n", encoding="utf-8")
            commands = [(["--init-db"], 0), (["--init-db"], 0)]
            for filename in ("clientes.csv", "clientes.xlsx"):
                commands.append((["--store-db", "--input", str(inputs / filename),
                                  "--output-dir", str(root / "out")], 0))
            commands.extend([
                (["--store-db", "--input-dir", str(inputs), "--output-dir", str(root / "out")], 1),
                (["--history"], 0), (["--run-detail", "3"], 0),
            ])
            for arguments, expected in commands:
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    status = main.main(arguments)
                text = output.getvalue()
                assert os.environ["PGPASSWORD"] not in text
                print("\nDEMO:", " ".join(arguments), "| código", status)
                print(text)
                assert status == expected
            for path, original in originals.items():
                assert path.read_bytes() == original
                assert (inputs / path.name).read_bytes() == original
                print(f"SHA-256 verificado: {path.name}: {hashlib.sha256(original).hexdigest()}")
            print("Demostración real completada; ninguna contraseña apareció en la salida.")
    finally:
        os.environ["PGDATABASE"] = previous_db
        if created:
            assert name.startswith("demo_automatizacion_")
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        admin.close()


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True, help="Carpeta de initdb y pg_ctl")
    parser.add_argument("--demo", action="store_true", help="Ejecutar también ejemplos y consultas reales")
    args = parser.parse_args()
    with temporary_server(args.pg_bin):
        tests = unittest.defaultTestLoader.discover(str(ROOT / "tests" / "integration"))
        result = unittest.TextTestRunner(verbosity=2).run(tests)
        if not result.wasSuccessful():
            return 1
        if args.demo:
            demonstration()
    return 0


if __name__ == "__main__":
    sys.exit(run())
