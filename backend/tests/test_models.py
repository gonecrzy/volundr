from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.project import Project
from app.models.project_message import ProjectMessage
from app.models.revision import Revision


def test_project_and_revision_tables_can_be_created() -> None:
    engine = create_engine("sqlite:///:memory:")

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert "projects" in inspector.get_table_names()
    assert "project_messages" in inspector.get_table_names()
    assert "revisions" in inspector.get_table_names()


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
            scad_source_path="projects/bracket/revisions/1/model.scad",
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
