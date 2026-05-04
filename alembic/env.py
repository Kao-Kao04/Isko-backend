from logging.config import fileConfig
from sqlalchemy import create_engine, pool
from alembic import context

from app.config import settings
from app.database import Base
import app.models  # noqa: F401 — ensures all models are registered

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_sync_url() -> str:
    url = settings.DATABASE_URL
    # Alembic uses psycopg2 (sync); strip asyncpg driver if present
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    # Supabase requires SSL; psycopg2 doesn't negotiate it automatically
    if "sslmode" not in url:
        url += "?sslmode=require"
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=get_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_sync_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
