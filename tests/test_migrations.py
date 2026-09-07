import hashlib

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import upgrade
from sqlalchemy import text

from reader_app import create_app
from reader_app.cli import prepare_database
from reader_app.extensions import db
from reader_app.models import Book


@pytest.mark.parametrize('baseline', [False, True])
def test_database_upgrade_preserves_data_and_matches_models(tmp_path, baseline):
    app = create_app({
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "migration.sqlite3"}',
        'BOOK_UPLOAD_FOLDER': str(tmp_path / 'books'),
    })
    if baseline:
        with app.app_context():
            upgrade(revision='0001_initial')
            db.session.execute(text("INSERT INTO user VALUES "
                                    "(1, 'reader', 'reader@example.com', 'hash', CURRENT_TIMESTAMP)"))
            db.session.execute(text("INSERT INTO book VALUES "
                                    "(1, 1, '旧书', NULL, NULL, 'book.txt', 'book.txt', 'txt', "
                                    "CURRENT_TIMESTAMP)"))
            db.session.execute(text("INSERT INTO reading_progress VALUES "
                                    "(1, 1, 1, '{\"progress\": 0.4}', CURRENT_TIMESTAMP)"))
            # Exercise adoption of a database from before version tracking existed.
            db.session.execute(text('DELETE FROM alembic_version'))
            db.session.commit()
        (tmp_path / 'books' / 'book.txt').write_bytes(b'original book')
    prepare_database(app)
    prepare_database(app)
    with app.app_context():
        with db.engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), db.metadata) == []
        if baseline:
            book = db.session.get(Book, 1)
            assert book.title == '旧书'
            assert book.content_hash == hashlib.sha256(b'original book').hexdigest()
            assert '0.4' in book.progress.locator
        db.session.remove()
        db.engine.dispose()
