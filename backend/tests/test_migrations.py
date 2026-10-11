from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

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

    assert {
        "jobs",
        "analyses",
        "worker_state",
        "feedback",
        "calibration_versions",
        "calibration_state",
        "feedback_summary",
    } <= tables
    assert differences == []


def test_jobs_stored_before_coaching_existed_become_analysis_jobs(tmp_path):
    url = f"sqlite:///{tmp_path / 'older.db'}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "04a480e7bbb1")  # the schema before coaching

    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO jobs (id, status, cancel_requested, attempt, profile, language_hint,"
                " retain_audio, error_retryable, created_at, updated_at) VALUES ('old', 'succeeded',"
                " 0, 1, 'custom', 'auto', 0, 0, '2026-10-10 10:00:00', '2026-10-10 10:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO analyses (id, job_id, created_at, profile, language, duration_seconds,"
                " schema_version, settings_version, revision, result) VALUES ('a1', 'old',"
                " '2026-10-10 10:00:00', 'custom', 'en', 9.0, 1, 1, 1, '{}')"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = make_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT kind FROM jobs")).scalar_one() == "analysis"
        assert connection.execute(text("SELECT coaching FROM analyses")).scalar_one() is None
        # Everything stored before references existed is one of the user's own takes.
        assert connection.execute(text("SELECT role FROM jobs")).scalar_one() == "take"
        assert connection.execute(text("SELECT role, title, waveform FROM analyses")).one() == (
            "take",
            None,
            None,
        )
        # Results from before calibration were made with the defaults (version 1), and
        # each is the first and only result of its own recording.
        assert connection.execute(
            text("SELECT calibration_version, root_id, revision, revision_reason FROM analyses")
        ).one() == (1, "a1", 1, None)
        assert connection.execute(text("SELECT source_analysis_id FROM jobs")).scalar_one() is None
    engine.dispose()
