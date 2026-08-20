from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Database
from app.db.database import Base, DATABASE_URL

# ------------------------------------------------------------------
# IMPORTANT:
# Import every module that contains SQLAlchemy models.
# This registers all tables with Base.metadata so Alembic
# can detect them correctly.
# ------------------------------------------------------------------

import app.db.models
import app.auth.models

# ------------------------------------------------------------------

config = context.config

config.set_main_option(
    "sqlalchemy.url",
    DATABASE_URL,
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in offline mode.
    """

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={
            "paramstyle": "named",
        },
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in online mode.
    """

    configuration = config.get_section(config.config_ini_section)

    configuration["sqlalchemy.url"] = DATABASE_URL

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()