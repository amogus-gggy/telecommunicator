#!/usr/bin/env python3
"""Build a server zip package for deployment.

This script creates a zip archive containing the server code (app/),
alembic migrations, and required config files. Used by GitHub Actions
to produce a downloadable server package.
"""

import sys
import zipfile
from pathlib import Path


def build_server_package(output_path: str = "telecommunicator_server.zip") -> None:
    project = Path(__file__).resolve().parent.parent

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Server Python files
        for pattern in ["app/**/*.py", "*.py", "*.txt", "*.json", "*.ini"]:
            for file_path in project.glob(pattern):
                if "__pycache__" in str(file_path):
                    continue
                if str(file_path).startswith(str(project / "client")):
                    continue
                if str(file_path).startswith(str(project / "tests")):
                    continue
                arc_name = file_path.relative_to(project)
                zf.write(file_path, arc_name)

        # Alembic directory
        alembic_dir = project / "alembic"
        if alembic_dir.exists():
            for file_path in alembic_dir.rglob("*"):
                if "__pycache__" in str(file_path) or file_path.is_dir():
                    continue
                arc_name = file_path.relative_to(project)
                zf.write(file_path, arc_name)

    print(f"Built {output_path}")


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "telecommunicator_server.zip"
    build_server_package(output)
