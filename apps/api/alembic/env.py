"""Use the caller's connection so adoption and upgrades commit together."""
from alembic import context

from mandate.db import Base
from mandate import models  # noqa: F401

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use python -m mandate.migrate; direct Alembic upgrades bypass adoption checks")
context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
with context.begin_transaction():
    context.run_migrations()
