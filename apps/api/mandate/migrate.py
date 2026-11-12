"""Explicit, transactional PostgreSQL schema upgrades and read-only startup checks."""
import argparse
import re
from importlib.resources import files
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from dotenv import load_dotenv
from sqlalchemy import CheckConstraint, inspect, text
from sqlalchemy.engine import Engine

from mandate_migrations.prototype import prototype_metadata


class SchemaStateError(RuntimeError):
    """An operator-readable schema error that contains no database credentials."""


def migration_config(connection=None):
    config = Config()
    config.set_main_option("script_location", str(files("mandate_migrations")))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _validate_schema(connection, metadata):
    inspector = inspect(connection)
    invalid_constraints = connection.scalar(text("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = current_schema() AND NOT c.convalidated"))
    if invalid_constraints:
        raise SchemaStateError("Database has unvalidated constraints; validate existing data before migrating")
    context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
    if compare_metadata(context, metadata):
        raise SchemaStateError("Database schema differs from the expected revision; inspect the schema before migrating")
    # Alembic autogeneration does not compare CHECK constraints or primary keys.
    for table in metadata.sorted_tables:
        expected_pk = [column.name for column in table.primary_key.columns]
        if inspector.get_pk_constraint(table.name)["constrained_columns"] != expected_pk:
            raise SchemaStateError("Database primary keys differ from the expected revision")
        # Baseline checks contain only conjunctions, so redundant PostgreSQL parentheses are immaterial.
        normalize = lambda value: re.sub(r'[\s()"]', "", str(value)).lower()
        expected_checks = {normalize(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
        actual_checks = {normalize(c["sqltext"]) for c in inspector.get_check_constraints(table.name)}
        if actual_checks != expected_checks:
            raise SchemaStateError("Database accounting checks differ from the expected revision")


def ensure_schema_current(engine: Engine) -> None:
    """Reject missing migrations and schema drift without writing to the database."""
    from .db import Base
    from . import models  # noqa: F401

    head = ScriptDirectory.from_config(migration_config()).get_current_head()
    with engine.connect() as connection:
        if MigrationContext.configure(connection).get_current_heads() != (head,):
            raise SchemaStateError("Database migrations are required; run python -m mandate.migrate, or use --adopt-prototype for an existing unversioned prototype")
        _validate_schema(connection, Base.metadata)


def migrate(engine: Engine, *, adopt_prototype: bool = False) -> None:
    """Upgrade a blank/versioned schema, or explicitly adopt an exact prototype."""
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(current_database() || ':' || current_schema() || :suffix, 0))"), {"suffix": ":mandate_migrations"})
        config = migration_config(connection)
        heads = MigrationContext.configure(connection).get_current_heads()
        tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
        if not heads and tables:
            if not adopt_prototype:
                raise SchemaStateError("Existing unversioned database requires backup and explicit --adopt-prototype")
            _validate_schema(connection, prototype_metadata())
            command.stamp(config, "0001_prototype")
        elif adopt_prototype:
            raise SchemaStateError("--adopt-prototype requires an unversioned prototype database")
        if heads == ("0001_prototype",):
            _validate_schema(connection, prototype_metadata())
        command.upgrade(config, "head")
        from .db import Base
        from . import models  # noqa: F401
        _validate_schema(connection, Base.metadata)


def main():
    parser = argparse.ArgumentParser(description="Upgrade Mandate's PostgreSQL schema. Back up existing data first.")
    parser.add_argument("--adopt-prototype", action="store_true", help="Validate and adopt the unversioned prototype, preserving records and expiring old sessions")
    args = parser.parse_args()
    try:
        load_dotenv(Path.cwd() / ".env")
        from .db import engine
        migrate(engine, adopt_prototype=args.adopt_prototype)
    except SchemaStateError as exc:
        parser.exit(1, str(exc) + "\n")
    except Exception:
        # Driver exceptions may contain SQL parameters or connection credentials.
        parser.exit(1, "Migration failed. No database URL is logged. Check connectivity, schema revision and drift, and whether --adopt-prototype is required.\n")
    print("Database schema is current.")


if __name__ == "__main__":
    main()
