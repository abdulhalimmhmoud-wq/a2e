"""إعداد قاعدة البيانات (SQLAlchemy 2.x)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """WAL يسمح للقراءة أثناء الكتابة.

    SQLite بيسمح بكاتب واحد بس في نفس الوقت. المهام الخلفية بتحفظ بعد
    كل دفعة (معاملات قصيرة) عشان مايحصلش قفل طويل، والمهلة الطويلة هنا
    شبكة أمان لو اتصادف طلبان في نفس اللحظة.
    """
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """اعتمادية FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """للاستخدام داخل المهام الخلفية."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _add_missing_columns() -> None:
    """ترحيل خفيف: إضافة الأعمدة الجديدة لقواعد بيانات موجودة.

    الأداة محلية ومفيش داعي لأدوات ترحيل كاملة، لكن لازم قاعدة بيانات
    قديمة تشتغل بعد التحديث من غير ما المستخدم يفقد شغله.
    """
    from sqlalchemy import text

    # (الجدول, العمود, تعريفه, تعبير التعبئة الرجعية)
    additions = [
        ("tm_entries", "source_length", "INTEGER DEFAULT 0", "LENGTH(source_text)"),
        ("projects", "engine", "VARCHAR(20) DEFAULT 'claude'", "'claude'"),
        ("source_files", "meta", "TEXT DEFAULT '{}'", "'{}'"),
    ]

    with engine.begin() as conn:
        for table, column, definition, backfill in additions:
            existing = {
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            if not existing or column in existing:
                continue

            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
            if backfill:
                conn.execute(text(f"UPDATE {table} SET {column} = {backfill}"))
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} "
                    f"ON {table} ({column})"
                )
            )


def init_db() -> None:
    from app import models  # noqa: F401  (تسجيل الجداول)

    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
