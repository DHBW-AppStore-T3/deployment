"""Alembic environment: migrates the database named by ``DATABASE_URL``.

Run by ``alembic upgrade head`` (the API pod's init container, ``make``
targets); the target metadata are the shared models, so autogenerate and
``make migrations-check`` compare against ``appstore_shared.models``.
"""

from logging.config import fileConfig
from sqlalchemy import text, engine_from_config
from sqlalchemy import pool
from alembic import context

# The Alembic Config object (values from alembic.ini).
config = context.config

# Logging setup from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The models' metadata, for autogenerate and the migrations check.
from appstore_api.database import Base

# Import the models module so that all model classes are registered
# on Base.metadata. Avoid importing specific model names here because
# models may be renamed/removed; importing the module is more robust
# for autogenerate.
try:
    import importlib

    importlib.import_module("appstore_api.models")
except Exception:
    # If models cannot be imported here (e.g. during certain checks),
    # we still set target_metadata to Base.metadata so offline mode can run.
    pass

target_metadata = Base.metadata

# The URL comes from the environment like the API's (config only via env);
# whatever alembic.ini says is overridden.
from appstore_api.config import settings

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (``alembic upgrade --sql``): emit SQL instead of executing it.

    Configured with just the URL, so no DBAPI connection is needed.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database, serialised by an advisory lock.

    Type and server-default changes are compared too, so the migrations
    check catches them.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
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
            # Every API pod migrates in its init container; with several
            # replicas starting at once, the lock makes them take turns (the
            # later ones then find nothing to do). Transaction-scoped, so it
            # is released with the commit.
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('appstore-api:migrations'))"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
