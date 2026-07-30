from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.project import Project
from app.models.project_message import ProjectMessage
from app.models.printability_profile import SavedPrintabilityProfile
from app.models.revision import Revision
from app.models.validation_finding import ValidationFinding


def test_project_and_revision_tables_can_be_created() -> None:
    engine = create_engine("sqlite:///:memory:")

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert "projects" in inspector.get_table_names()
    assert "project_messages" in inspector.get_table_names()
    assert "printability_profiles" in inspector.get_table_names()
    assert "revisions" in inspector.get_table_names()
    assert "validation_findings" in inspector.get_table_names()


def test_cadquery_native_persistence_columns_are_canonical() -> None:
    engine = create_engine("sqlite:///:memory:")

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    revision_columns = {column["name"] for column in inspector.get_columns("revisions")}
    assert {
        "cad_backend",
        "source_language",
        "source_path",
        "source_hash",
        "source_contract_version",
        "execution_manifest_path",
    }.issubset(revision_columns)
    assert "scad_source_path" not in revision_columns

    output_columns = {column["name"] for column in inspector.get_columns("revision_outputs")}
    assert {
        "entrypoint",
        "step_path",
        "step_hash",
        "brep_path",
        "brep_hash",
        "topology_metadata_json",
        "expected_solid_count",
        "detected_solid_count",
        "allow_disconnected_solids",
        "mesh_metadata_json",
        "execution_command_json",
    }.issubset(output_columns)
    assert "module_name" not in output_columns
    assert "compile_command_json" not in output_columns

    attempt_columns = {column["name"] for column in inspector.get_columns("generation_attempts")}
    assert {
        "ruleset_version",
        "cad_backend",
        "source_language",
        "source_contract_version",
    }.issubset(attempt_columns)
    assert "gemini_ruleset_version" not in attempt_columns

    source_validation_columns = {
        column["name"] for column in inspector.get_columns("source_validation_results")
    }
    assert {
        "validator_id",
        "cad_backend",
        "source_language",
    }.issubset(source_validation_columns)

    geometric_columns = {
        column["name"] for column in inspector.get_columns("geometric_analysis_results")
    }
    assert "analysis_kind" in geometric_columns


def test_project_can_reference_active_revision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(
            name="Bracket",
            slug="bracket",
            original_intent="Make a simple mounting bracket.",
        )
        session.add(project)
        session.flush()

        revision = Revision(
            project_id=project.id,
            revision_number=1,
            source_type="manual_edit",
            user_instruction="Initial cube fixture.",
            cad_backend="cadquery",
            source_language="python",
            source_path="projects/bracket/revisions/1/source.py",
            source_hash="0" * 64,
            source_contract_version="cadquery-v1",
            status="succeeded",
            is_accepted=True,
        )
        session.add(revision)
        session.flush()

        project.active_revision_id = revision.id
        project_id = project.id
        revision_id = revision.id
        session.commit()

    with Session(engine) as session:
        stored = session.get(Project, project_id)
        assert stored is not None
        assert stored.active_revision_id == revision_id
