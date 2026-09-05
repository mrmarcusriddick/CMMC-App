from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def migrate_existing_schema() -> None:
    """Add nullable linkage fields without rewriting historical assessment evidence."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())
        migrations = {
            "assessment_runs": ("framework_release_id", "ALTER TABLE assessment_runs ADD COLUMN framework_release_id VARCHAR(36)"),
            "findings": ("framework_objective_id", "ALTER TABLE findings ADD COLUMN framework_objective_id VARCHAR(36)"),
            "managed_accounts": ("source", "ALTER TABLE managed_accounts ADD COLUMN source VARCHAR(120) DEFAULT 'MANUAL'"),
            "inventory_assets": ("source", "ALTER TABLE inventory_assets ADD COLUMN source VARCHAR(120) DEFAULT 'MANUAL'"),
        }
        for table, (column, statement) in migrations.items():
            if table in existing_tables and column not in {item["name"] for item in inspector.get_columns(table)}:
                connection.execute(text(statement))
        if "assessment_runs" in existing_tables:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_runs_framework_release ON assessment_runs (framework_release_id)"))
        if "findings" in existing_tables:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_findings_framework_objective ON findings (framework_objective_id)"))
        for table in ("managed_accounts", "inventory_assets"):
            if table in existing_tables:
                existing_columns = {item["name"] for item in inspector.get_columns(table)}
                extra_columns = {
                    "source_id": f"ALTER TABLE {table} ADD COLUMN source_id VARCHAR(240)",
                    "last_synced_at": f"ALTER TABLE {table} ADD COLUMN last_synced_at TIMESTAMP",
                }
                for column, statement in extra_columns.items():
                    if column not in existing_columns:
                        connection.execute(text(statement))
