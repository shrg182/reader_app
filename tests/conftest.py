from pathlib import Path

import pytest

from reader_app import create_app
from reader_app.extensions import db


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BOOK_UPLOAD_FOLDER": str(tmp_path / "books"),
            "WTF_CSRF_ENABLED": False,
        }
    )
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, username="reader", email="reader@example.com"):
    return client.post(
        "/auth/register",
        data={"username": username, "email": email, "password": "password123"},
        follow_redirects=True,
    )
