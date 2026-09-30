"""Genera una entrega por lista permitida: nunca incluye entornos ni credenciales."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent.parent


def build():
    files = [ROOT / name for name in (
        "main.py", "README.md", "requirements.txt", "schema.sql", ".env.example", ".gitignore",
        "data/raw/clientes.csv", "data/raw/clientes.xlsx", "data/processed/.gitkeep",
    )]
    for folder in ("src", "tests", "scripts"):
        files.extend((ROOT / folder).rglob("*.py"))
    files.extend((ROOT / "docs").glob("*.md"))
    destination = ROOT / "dist" / "automatizacion-datos-python-iteracion4.zip"
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in sorted(files):
            relative = path.relative_to(ROOT)
            if any(part in (".venv", "__pycache__", ".cache", ".git") for part in relative.parts):
                raise ValueError(f"Ruta no permitida: {relative}")
            archive.write(path, Path("automatizacion-datos-python") / relative)
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            assert Path(name).name != ".env"
            assert not name.endswith((".pyc", ".log"))
            assert "/data/processed/" not in name or name.endswith("/.gitkeep")
        print(f"ZIP verificado: {destination} ({len(archive.namelist())} archivos)")


if __name__ == "__main__":
    build()
