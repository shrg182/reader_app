"""Reader application package."""

import os
from pathlib import Path

from flask import Flask

from reader_app.extensions import csrf, db, login_manager, migrate

__version__ = "0.1.0"


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the Reader web application."""
    app = Flask(__name__, instance_relative_config=True)
    environment = os.environ.get("READER_ENV", "development").lower()
    secret_key = os.environ.get("READER_SECRET_KEY")
    if environment == "production" and not secret_key:
        raise RuntimeError("READER_SECRET_KEY is required when READER_ENV=production.")
    app.config.from_mapping(
        ENVIRONMENT=environment,
        SECRET_KEY=secret_key or "development-change-me",
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "READER_DATABASE_URI", f"sqlite:///{Path(app.instance_path) / 'reader.sqlite3'}"
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=100 * 1024 * 1024,
        BOOK_MAX_CONTENT_LENGTH=10 * 1024 * 1024,
        BACKUP_MAX_CONTENT_LENGTH=100 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=environment == "production",
        TRUSTED_HOSTS=[
            host.strip()
            for host in os.environ.get("READER_TRUSTED_HOSTS", "").split(",")
            if host.strip()
        ]
        or None,
        BOOK_UPLOAD_FOLDER=os.environ.get(
            "READER_BOOK_FOLDER", str(Path(app.instance_path) / "books")
        ),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["BOOK_UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    from reader_app.annotations import bp as annotations_bp
    from reader_app.auth import bp as auth_bp
    from reader_app.exports import bp as exports_bp
    from reader_app.library import bp as library_bp
    from reader_app.reader import bp as reader_bp
    from reader_app.restore import bp as restore_bp
    from reader_app.study import bp as study_bp

    app.register_blueprint(annotations_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(reader_bp)
    app.register_blueprint(restore_bp)
    app.register_blueprint(study_bp)

    from reader_app.errors import register_error_handlers

    register_error_handlers(app)

    if app.config.get("TESTING"):
        with app.app_context():
            db.create_all()

    return app
