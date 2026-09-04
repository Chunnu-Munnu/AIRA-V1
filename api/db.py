"""Database engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .tables import Base

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # a dropped MySQL connection must not surface as a 500
    pool_recycle=3600,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()
    _upgrade_timestamp_precision()


# ─────────────────────────────────────────────────────────────────────────────
# create_all() creates missing TABLES but never alters an existing one. As the
# product grows a column at a time - a `reviewed_at` on medical_document, a
# `state` on a care task - the model and the live table drift apart silently
# until a query 500s in the demo.
#
# This walks every mapped table, compares its columns against
# information_schema, and issues ADD COLUMN for anything the model has that the
# database does not. It is deliberately one-directional: it never drops or
# retypes a column, because that is where data gets lost. Anything more
# invasive than "a new nullable column appeared" is still a hand-written
# migration.
# ─────────────────────────────────────────────────────────────────────────────
def _add_missing_columns() -> None:
    if not engine.url.get_backend_name().startswith("mysql"):
        return

    from sqlalchemy.schema import CreateColumn

    dialect = engine.dialect
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            rows = conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
                ),
                {"t": table.name},
            ).all()
            if not rows:  # table does not exist yet; create_all handles it
                continue
            existing = {r[0].lower() for r in rows}
            for column in table.columns:
                if column.name.lower() in existing:
                    continue
                ddl = str(CreateColumn(column).compile(dialect=dialect)).strip()
                conn.execute(text(f"ALTER TABLE `{table.name}` ADD COLUMN {ddl}"))


# ─────────────────────────────────────────────────────────────────────────────
# MySQL's DATETIME defaults to whole seconds. Two rows written inside the same
# second therefore carry the SAME created_at, and `ORDER BY created_at DESC`
# becomes an arbitrary choice between them.
#
# This is not cosmetic. "The latest assessment" is the value the patient
# dashboard, the clinician queue and the Handoff Card are all built from. A tie
# there means a patient can be shown a stale tier - we saw exactly that: a
# record that had reached HIGH displayed as MODERATE, because an assessment
# written a fraction of a second earlier sorted equal and won.
#
# Microsecond precision removes the tie at the source. Ordering is then a
# total order, and every read path agrees on which row is newest.
# ─────────────────────────────────────────────────────────────────────────────
_PRECISION_SQL = """
    SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE
      FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND DATA_TYPE = 'datetime'
       AND DATETIME_PRECISION = 0
"""


def _upgrade_timestamp_precision() -> None:
    if not engine.url.get_backend_name().startswith("mysql"):
        return
    with engine.begin() as conn:
        stale = conn.execute(text(_PRECISION_SQL)).all()
        for table, column, nullable in stale:
            null_sql = "NULL" if nullable == "YES" else "NOT NULL"
            conn.execute(
                text(f"ALTER TABLE `{table}` MODIFY `{column}` DATETIME(6) {null_sql}")
            )


def ping() -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT VERSION()")).scalar_one()
