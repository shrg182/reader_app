"""Database models for users, books, and reading state."""

from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from reader_app.extensions import db, login_manager


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(UserMixin, db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    books: Mapped[list["Book"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    preference: Mapped["ReaderPreference | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Book(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    file_type: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    asset_root: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    owner: Mapped[User] = relationship(back_populates="books")
    progress: Mapped["ReadingProgress | None"] = relationship(
        back_populates="book", cascade="all, delete-orphan", uselist=False
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    vocabulary: Mapped[list["VocabularyEntry"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    chapters: Mapped[list["BookChapter"]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="BookChapter.ordinal"
    )


class ReadingProgress(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "book_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id"), index=True)
    locator: Mapped[str] = mapped_column(Text, default='{"progress": 0}')
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    book: Mapped[Book] = relationship(back_populates="progress")


class BookChapter(db.Model):
    __table_args__ = (UniqueConstraint("book_id", "ordinal"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id"), index=True)
    ordinal: Mapped[int]
    identifier: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    source_path: Mapped[str] = mapped_column(String(1000))
    content_html: Mapped[str] = mapped_column(Text)
    book: Mapped[Book] = relationship(back_populates="chapters")


class Annotation(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("book_chapter.id"), nullable=True)
    start_offset: Mapped[int]
    end_offset: Mapped[int]
    selected_text: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="yellow")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    book: Mapped[Book] = relationship(back_populates="annotations")


class VocabularyEntry(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("book_chapter.id"), nullable=True)
    start_offset: Mapped[int]
    end_offset: Mapped[int]
    term: Mapped[str] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(32), default="")
    definition: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    book: Mapped[Book] = relationship(back_populates="vocabulary")


class ReaderPreference(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True, index=True)
    theme: Mapped[str] = mapped_column(String(16), default="sepia")
    font_family: Mapped[str] = mapped_column(String(16), default="serif")
    font_size: Mapped[int] = mapped_column(default=18)
    line_height: Mapped[int] = mapped_column(default=185)
    column_width: Mapped[int] = mapped_column(default=760)
    user: Mapped[User] = relationship(back_populates="preference")


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))
