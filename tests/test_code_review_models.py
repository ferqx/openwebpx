from __future__ import annotations

from importlib import util
from pathlib import Path

import pytest
import sqlalchemy as sa
from aegra_api.core.orm import Base
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateTable

import app.models as models
from app.models.code_review import (
    RepositoryIntegration,
    RepositoryMembership,
    RepositoryReviewConfig,
    ReviewFinding,
    ReviewFixRequest,
    ReviewFixRequestSource,
    ReviewFixRequestStatus,
    ReviewRun,
    ReviewRunStatus,
    ReviewTimelineEvent,
)


def test_code_review_models_are_exported_from_package() -> None:
    expected = {
        "RepositoryIntegration",
        "RepositoryMembership",
        "RepositoryReviewConfig",
        "ReviewRun",
        "ReviewFinding",
        "ReviewTimelineEvent",
        "ReviewFixRequest",
    }

    assert expected.issubset(set(models.__all__))
    for name in expected:
        assert getattr(models, name) is globals()[name]
    assert {
        "repository_integrations",
        "repository_memberships",
        "repository_review_configs",
        "review_runs",
        "review_findings",
        "review_timeline_events",
        "review_fix_requests",
    }.issubset(Base.metadata.tables.keys())
    assert "repository_identity_key" in RepositoryIntegration.__table__.c


def test_code_review_model_status_values_and_relationships() -> None:
    assert ReviewRun.__table__.c.status.type.enum_class is ReviewRunStatus
    assert ReviewRun.__table__.c.status.type.enums == [
        "queued",
        "analyzing",
        "completed",
        "failed",
    ]
    assert ReviewFixRequest.__table__.c.status.type.enum_class is ReviewFixRequestStatus
    assert ReviewFixRequest.__table__.c.source.type.enum_class is ReviewFixRequestSource
    assert ReviewFixRequest.__table__.c.status.type.enums == [
        "pending_approval",
        "approved",
        "rejected",
        "running",
        "completed",
        "failed",
    ]

    integration_mapper = inspect(RepositoryIntegration)
    membership_mapper = inspect(RepositoryMembership)
    config_mapper = inspect(RepositoryReviewConfig)
    run_mapper = inspect(ReviewRun)
    finding_mapper = inspect(ReviewFinding)
    timeline_mapper = inspect(ReviewTimelineEvent)
    fix_mapper = inspect(ReviewFixRequest)

    assert set(integration_mapper.relationships.keys()) == {
        "memberships",
        "review_config",
        "review_runs",
    }
    assert set(membership_mapper.relationships.keys()) == {"repository_integration"}
    assert set(config_mapper.relationships.keys()) == {"repository_integration"}
    assert set(run_mapper.relationships.keys()) == {
        "repository_integration",
        "findings",
        "timeline_events",
        "fix_requests",
    }
    assert set(finding_mapper.relationships.keys()) == {
        "review_run",
        "fix_requests",
    }
    assert set(timeline_mapper.relationships.keys()) == {"review_run"}
    assert set(fix_mapper.relationships.keys()) == {
        "review_run",
        "review_finding",
    }
    fix_request_fk = next(
        constraint
        for constraint in ReviewFixRequest.__table__.foreign_key_constraints
        if constraint.name == "fk_review_fix_requests_review_run_id_review_finding_id"
    )
    assert list(fix_request_fk.column_keys) == ["review_run_id", "review_finding_id"]
    assert [element.column.table.name for element in fix_request_fk.elements] == [
        "review_findings",
        "review_findings",
    ]
    assert [element.column.name for element in fix_request_fk.elements] == [
        "review_run_id",
        "id",
    ]

    assert isinstance(ReviewFinding.__table__.c.metadata.type, JSONB)
    assert isinstance(ReviewTimelineEvent.__table__.c.payload.type, JSONB)
    assert isinstance(ReviewFixRequest.__table__.c.result_payload.type, JSONB)


def test_code_review_schema_compiles_with_postgresql_guarantees() -> None:
    review_finding_sql = str(
        CreateTable(ReviewFinding.__table__).compile(dialect=postgresql.dialect())
    )
    review_fix_request_sql = str(
        CreateTable(ReviewFixRequest.__table__).compile(dialect=postgresql.dialect())
    )
    repository_review_config_sql = str(
        CreateTable(RepositoryReviewConfig.__table__).compile(
            dialect=postgresql.dialect()
        )
    )

    assert (
        "CONSTRAINT uq_review_findings_review_run_id_id UNIQUE (review_run_id, id)"
        in review_finding_sql
    )
    assert (
        "CONSTRAINT fk_review_fix_requests_review_run_id_review_finding_id FOREIGN KEY(review_run_id, review_finding_id) REFERENCES review_findings (review_run_id, id) ON DELETE CASCADE"
        in review_fix_request_sql
    )
    assert "CONSTRAINT uq_review_findings_review_run_id_id" in review_finding_sql
    assert (
        "CONSTRAINT uq_review_findings_review_run_id_id" not in review_fix_request_sql
    )
    assert ReviewRun.__table__.c.updated_at.server_onupdate is None
    assert ReviewFixRequest.__table__.c.updated_at.server_onupdate is None

    finding_constraint_names = {
        constraint.name
        for constraint in ReviewFinding.__table__.constraints
        if constraint.name is not None
    }
    fix_request_constraint_names = {
        constraint.name
        for constraint in ReviewFixRequest.__table__.constraints
        if constraint.name is not None
    }
    assert finding_constraint_names.isdisjoint(fix_request_constraint_names)
    assert "uq_review_findings_review_run_id_id" in finding_constraint_names
    assert (
        "fk_review_fix_requests_review_run_id_review_finding_id"
        in fix_request_constraint_names
    )
    assert (
        "review_enabled BOOLEAN DEFAULT false NOT NULL" in repository_review_config_sql
    )


def test_review_fix_request_rejects_mismatched_run_and_finding() -> None:
    fix_request = ReviewFixRequest(review_run_id=1, review_finding_id=2)

    with pytest.raises(ValueError, match="review_run_id must match"):
        fix_request.review_finding = ReviewFinding(id=3, review_run_id=99)


def test_code_review_migration_defines_expected_tables_and_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260322103000_add_code_review_platform_tables.py"
    )
    assert migration_path.exists(), migration_path

    spec = util.spec_from_file_location("test_code_review_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    created_tables: dict[str, sa.Table] = {}
    created_indexes: list[tuple[str, str, tuple[str, ...], dict[str, object]]] = []
    migration_metadata = sa.MetaData()

    def create_table(name: str, *elements: object, **kwargs: object) -> None:
        created_tables[name] = sa.Table(name, migration_metadata, *elements)

    def create_index(
        name: str, table_name: str, columns: list[str], **kwargs: object
    ) -> None:
        created_indexes.append((name, table_name, tuple(columns), kwargs))

    monkeypatch.setattr(migration.op, "create_table", create_table)
    monkeypatch.setattr(migration.op, "create_index", create_index)

    migration.upgrade()

    expected_tables = {
        "repository_integrations",
        "repository_memberships",
        "repository_review_configs",
        "review_runs",
        "review_findings",
        "review_timeline_events",
        "review_fix_requests",
    }
    assert expected_tables == set(created_tables)

    expected_indexes = {
        (
            "idx_repository_memberships_user_id_repository_integration_id",
            "repository_memberships",
            ("user_id", "repository_integration_id"),
        ),
        (
            "idx_review_runs_repository_integration_id_status",
            "review_runs",
            ("repository_integration_id", "status"),
        ),
        (
            "idx_review_fix_requests_review_run_id_status",
            "review_fix_requests",
            ("review_run_id", "status"),
        ),
    }
    assert expected_indexes.issubset(
        {
            (name, table_name, columns)
            for name, table_name, columns, _ in created_indexes
        }
    )
    assert "idx_repository_integrations_provider_external_repo_id" not in {
        name for name, _, _, _ in created_indexes
    }
    assert "idx_review_runs_idempotency_key" not in {
        name for name, _, _, _ in created_indexes
    }

    repository_integrations_sql = str(
        CreateTable(created_tables["repository_integrations"]).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "repository_identity_key" in repository_integrations_sql
    assert (
        "CONSTRAINT uq_repository_integrations_provider_external_repo_identity_key UNIQUE (provider, external_repo_id, repository_identity_key)"
        in repository_integrations_sql
    )

    review_runs_sql = str(
        CreateTable(created_tables["review_runs"]).compile(dialect=postgresql.dialect())
    )
    repository_review_configs_sql = str(
        CreateTable(created_tables["repository_review_configs"]).compile(
            dialect=postgresql.dialect()
        )
    )
    orm_review_runs_sql = str(
        CreateTable(ReviewRun.__table__).compile(dialect=postgresql.dialect())
    )
    orm_repository_review_configs_sql = str(
        CreateTable(RepositoryReviewConfig.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    review_findings_sql = str(
        CreateTable(created_tables["review_findings"]).compile(
            dialect=postgresql.dialect()
        )
    )
    review_fix_requests_sql = str(
        CreateTable(created_tables["review_fix_requests"]).compile(
            dialect=postgresql.dialect()
        )
    )

    assert (
        "CONSTRAINT uq_review_findings_review_run_id_id UNIQUE (review_run_id, id)"
        in review_findings_sql
    )
    assert "UNIQUE (idempotency_key)" in review_runs_sql
    assert "UNIQUE (repository_integration_id)" in repository_review_configs_sql
    assert "UNIQUE (idempotency_key)" in orm_review_runs_sql
    assert "UNIQUE (repository_integration_id)" in orm_repository_review_configs_sql
    assert (
        "CONSTRAINT fk_review_fix_requests_review_run_id_review_finding_id FOREIGN KEY(review_run_id, review_finding_id) REFERENCES review_findings (review_run_id, id) ON DELETE CASCADE"
        in review_fix_requests_sql
    )

    executed_sql: list[str] = []
    dropped_tables: list[str] = []
    dropped_indexes: list[str] = []

    def drop_table(name: str, **kwargs: object) -> None:
        dropped_tables.append(name)

    def drop_index(name: str, **kwargs: object) -> None:
        dropped_indexes.append(name)

    def execute(statement: object, **kwargs: object) -> None:
        executed_sql.append(str(statement))

    monkeypatch.setattr(migration.op, "drop_table", drop_table)
    monkeypatch.setattr(migration.op, "drop_index", drop_index)
    monkeypatch.setattr(migration.op, "execute", execute)

    migration.downgrade()

    assert dropped_tables == [
        "review_fix_requests",
        "review_timeline_events",
        "review_findings",
        "review_runs",
        "repository_review_configs",
        "repository_memberships",
        "repository_integrations",
    ]
    assert dropped_indexes == [
        "idx_review_fix_requests_review_run_id_status",
        "idx_review_runs_repository_integration_id_status",
        "idx_repository_memberships_user_id_repository_integration_id",
    ]
    assert executed_sql == [
        "DROP TYPE IF EXISTS review_fix_request_status",
        "DROP TYPE IF EXISTS review_fix_request_source",
        "DROP TYPE IF EXISTS review_run_status",
    ]


def test_code_review_backfill_migration_handles_jsonb_null_legacy_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260322170000_backfill_code_review_review_enabled_defaults.py"
    )
    assert migration_path.exists(), migration_path

    spec = util.spec_from_file_location(
        "test_code_review_backfill_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    executed_sql: list[str] = []

    def execute(statement: object, **kwargs: object) -> None:
        executed_sql.append(str(statement))

    monkeypatch.setattr(migration.op, "execute", execute)

    migration.upgrade()

    assert len(executed_sql) == 1
    assert "review_enabled = FALSE" in executed_sql[0]
    assert "review_triggers = 'null'::jsonb" in executed_sql[0]
    assert "auto_fix_severities = 'null'::jsonb" in executed_sql[0]
