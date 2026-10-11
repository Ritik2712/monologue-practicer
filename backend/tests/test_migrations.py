from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.config import BACKEND_DIR
from app.db import Base, make_engine


def test_migrations_build_exactly_the_tables_the_code_expects(tmp_path):
    """Fails if a model was changed without writing a migration for it."""
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)

    command.upgrade(config, "head")

    engine = make_engine(url)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()

    assert {"jobs", "analyses", "worker_state"} <= tables
    assert differences == []
