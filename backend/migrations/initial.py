from src.config.database import Base, engine
from src import models


def _additive_columns():
    """为既有表补齐后加的列；只加不改，旧数据升级后仍保留原有结果。"""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    additions = {
        'jobs': [
            ('mode', "VARCHAR(20) NOT NULL DEFAULT 'evaluate'"),
            ('source_job_id', 'INTEGER NULL'),
            ('model', 'JSON NULL'),
        ],
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            existing = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def migrate():
    Base.metadata.create_all(engine)
    _additive_columns()


if __name__ == '__main__':
    migrate()
