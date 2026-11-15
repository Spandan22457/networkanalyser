"""
Alembic environment.

The database URL comes from :mod:`monitor.core.config`, never from
``alembic.ini``, so migrations always target the same absolute file the
application uses.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from monitor.core.config import settings
from monitor.storage.database import Base, import_models


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url)

import_models()
target_metadata = Base.metadata


def _configure_kwargs() -> dict:
    return {
        "target_metadata": target_metadata,
        # SQLite cannot ALTER most columns, so migrations rebuild the table
        # instead.  A server database supports real ALTERs; batch mode would
        # only make the emitted SQL harder to read.
        "render_as_batch": settings.is_sqlite,
        "compare_type": True,
        "compare_server_default": True,
    }


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sqlalchemy_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_kwargs(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            **_configure_kwargs(),
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
