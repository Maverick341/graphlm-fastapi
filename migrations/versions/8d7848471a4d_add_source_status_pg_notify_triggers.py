"""add_source_status_pg_notify_triggers

Install PostgreSQL LISTEN/NOTIFY trigger functions and triggers that fire
on changes to the `sources` and `source_indexes` tables, publishing payloads
to the `source_status_updates` channel.

Trigger functions:  notify_source_status_update, notify_source_index_update
Triggers:           source_status_trigger, source_index_status_trigger

Revision ID: 8d7848471a4d
Revises: 96f1de273877
Create Date: 2026-05-10 20:30:04.338790
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d7848471a4d"
down_revision: Union[str, Sequence[str], None] = "96f1de273877"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Resolve SQL directory relative to this file so the migration works
# regardless of the working directory from which `alembic` is invoked:
#
#   migrations/versions/8d7848471a4d_....py  ← __file__
#   migrations/versions/                      ← parents[0]
#   migrations/                               ← parents[1]
#   graphlm-fastapi/                          ← parents[2]  (project root)
#   graphlm-fastapi/app/db/sql/               ← SQL_DIR
#
_SQL_DIR = Path(__file__).resolve().parents[2] / "app" / "db" / "sql"


def upgrade() -> None:
    sql = (_SQL_DIR / "source_status_triggers.sql").read_text()
    op.execute(sql)


def downgrade() -> None:
    sql = (_SQL_DIR / "source_status_triggers_teardown.sql").read_text()
    op.execute(sql)