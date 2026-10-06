"""Add empty reference-only curation state and audit tables; no legacy backfill."""

from sqlalchemy import Connection, Engine

from app.parent_trusted_reference_models import (
    ParentTrustedReferenceApproval,
    ParentTrustedReferenceApprovalEvent,
)


def _upgrade(connection: Connection) -> None:
    ParentTrustedReferenceApproval.__table__.create(connection, checkfirst=True)
    ParentTrustedReferenceApprovalEvent.__table__.create(connection, checkfirst=True)


def upgrade(bind: Engine | Connection) -> None:
    if isinstance(bind, Connection):
        _upgrade(bind)
    else:
        with bind.begin() as connection:
            _upgrade(connection)


def _downgrade(connection: Connection) -> None:
    ParentTrustedReferenceApprovalEvent.__table__.drop(connection, checkfirst=True)
    ParentTrustedReferenceApproval.__table__.drop(connection, checkfirst=True)


def downgrade(bind: Engine | Connection) -> None:
    if isinstance(bind, Connection):
        _downgrade(bind)
    else:
        with bind.begin() as connection:
            _downgrade(connection)
