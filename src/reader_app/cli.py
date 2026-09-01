"""Command-line entry point for Reader App."""

import argparse
import hashlib
from pathlib import Path

from flask_migrate import stamp, upgrade
from sqlalchemy import inspect, text

from reader_app import __version__, create_app
from reader_app.extensions import db
from reader_app.models import Book


def prepare_database(app) -> None:
    """Upgrade a new database or adopt and upgrade the pre-migration schema."""
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names())
        if "user" in tables:
            version = None
            if "alembic_version" in tables:
                version = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if version is None:
                stamp(revision="0001_initial")
        upgrade()
        books = db.session.scalars(db.select(Book).where(Book.content_hash.is_(None))).all()
        for book in books:
            path = Path(app.config["BOOK_UPLOAD_FOLDER"]) / book.stored_filename
            if path.is_file():
                with path.open("rb") as source:
                    book.content_hash = hashlib.file_digest(source, "sha256").hexdigest()
        db.session.commit()


def main() -> int:
    """Run the Reader web server or print its version."""
    parser = argparse.ArgumentParser(prog="reader-app")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()
    if args.version:
        print(f"Reader App {__version__}")
        return 0
    app = create_app()
    prepare_database(app)
    app.run(host=args.host, port=args.port)
    return 0
