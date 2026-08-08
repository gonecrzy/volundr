from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.project import Project
from app.models.project_message import ProjectMessage
from app.models.clarification_answer import ClarificationAnswer
from app.models.clarification_question import ClarificationQuestion
from app.models.design_specification import DesignSpecification
from app.models.requirement_ledger import PhysicalTestObservation, RequirementDelta, RequirementLedgerEntry
from app.services.projects.requirement_ledger import RequirementLedgerStore, active_requirements


def test_requirement_ledger_persists_deltas_and_physical_observations() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(name="Holder", slug="holder", original_intent="Make a holder")
        session.add(project)
        session.flush()
        store = RequirementLedgerStore(session)
        store.ensure_from_specification(
            project_id=project.id,
            specification={
                "explicit_requirements": [
                    {
                        "requirement_id": "bottle_diameter",
                        "type": "exact_dimension",
                        "value": 81,
                        "unit": "mm",
                        "kind": "dimension",
                        "operator": "exact",
                    }
                ]
            },
            originating_message="Create a holder for an 81 mm bottle.",
        )
        store.apply_delta(
            project_id=project.id,
            changes=[
                {
                    "operation": "change",
                    "requirement_id": "bottle_clearance_per_side",
                    "type": "clearance",
                    "value": 0.5,
                    "unit": "mm",
                    "source": "physical_test_feedback",
                }
            ],
            originating_message="The printed fit is too tight. Add 0.5 mm clearance per side.",
            observation={
                "source": "physical_test_feedback",
                "observation_type": "fit_too_tight",
                "observation": "The printed fit is too tight.",
            },
        )
        session.commit()
        project_id = project.id

    with Session(engine) as session:
        ledger = RequirementLedgerStore(session).load(project_id)
        active = active_requirements(ledger)
        assert {item["requirement_id"] for item in active} == {
            "bottle_diameter",
            "bottle_clearance_per_side",
        }
        diameter = next(item for item in active if item["requirement_id"] == "bottle_diameter")
        assert diameter["kind"] == "dimension"
        assert diameter["operator"] == "exact"
        assert session.scalar(select(RequirementDelta.project_id).where(RequirementDelta.project_id == project_id))
        assert session.scalar(
            select(PhysicalTestObservation.observation_type).where(
                PhysicalTestObservation.project_id == project_id
            )
        ) == "fit_too_tight"


def test_existing_ledger_semantics_are_reconciled_without_rewriting_history() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(name="Capacity", slug="capacity", original_intent="Make a holder")
        session.add(project)
        session.flush()
        store = RequirementLedgerStore(session)
        store.ensure_from_specification(
            project_id=project.id,
            specification={
                "explicit_requirements": [
                    {
                        "requirement_id": "storage_capacity",
                        "type": "explicit_count",
                        "value": 5,
                        "unit": "count",
                    }
                ]
            },
            originating_message="The old interpretation",
        )
        reconciled = store.ensure_from_specification(
            project_id=project.id,
            specification={
                "explicit_requirements": [
                    {
                        "requirement_id": "storage_capacity",
                        "type": "capacity",
                        "kind": "capacity",
                        "operator": "up_to",
                        "value": 5,
                        "unit": "item",
                        "object_type": "storage_bin",
                        "raw_evidence": "can hold up to 5 storage bins",
                    }
                ]
            },
            originating_message="The clarified semantic request",
        )
        rows = list(
            session.scalars(
                select(RequirementLedgerEntry).where(
                    RequirementLedgerEntry.project_id == project.id
                )
            )
        )
        assert len(rows) == 2
        active = active_requirements(reconciled)
        assert len(active) == 1
        assert active[0]["operator"] == "up_to"
        assert active[0]["object_type"] == "storage_bin"
        assert any(row.status == "superseded" for row in rows)


def test_ledger_preserves_contract_policy_fields_from_design_specification() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(name="Policy holder", slug="policy-holder", original_intent="Make a holder")
        session.add(project)
        session.flush()
        ledger = RequirementLedgerStore(session).ensure_from_specification(
            project_id=project.id,
            specification={
                "functional_requirements": [
                    {
                        "id": "secure_retention",
                        "description": "Keep the object secure during use.",
                        "source": "user",
                        "type": "qualitative_behavior",
                        "classification": "review_required",
                        "verification_policy": "review_only",
                    }
                ]
            },
            originating_message="Keep the object secure during use.",
        )

        item = active_requirements(ledger)[0]
        assert item["classification"] == "review_required"
        assert item["verification_policy"] == "review_only"


def test_legacy_clarification_provenance_is_reconciled_and_reloaded() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(name="Clarified holder", slug="clarified-holder", original_intent="Make a holder")
        session.add(project)
        session.flush()
        specification = DesignSpecification(
            project_id=project.id,
            version_number=1,
            schema_version="1.0",
            prompt_template_version="test",
            ruleset_version="test",
            provider="test",
            user_instruction="Make a holder",
            specification_path="specification.json",
            content_hash="0" * 64,
            outcome="generation_ready",
            generation_ready=True,
        )
        session.add(specification)
        session.flush()
        question = ClarificationQuestion(
            project_id=project.id,
            design_specification_id=specification.id,
            question="How should it be mounted?",
        )
        session.add(question)
        session.flush()
        answer = ClarificationAnswer(
            project_id=project.id,
            question_id=question.id,
            design_specification_id=specification.id,
            question_text=question.question,
            answer="wall mounted",
        )
        session.add(answer)
        session.add(
            ProjectMessage(
                project_id=project.id,
                role="user",
                content="wall mounted",
                client_message_id="clarification-message-1",
            )
        )
        session.flush()
        store = RequirementLedgerStore(session)
        store.apply_delta(
            project_id=project.id,
            changes=[
                {
                    "operation": "add",
                    "requirement_id": "mounting_method",
                    "type": "feature_presence",
                    "kind": "feature",
                    "operator": "present",
                    "value": True,
                    "source": "volundr_proposal",
                }
            ],
            originating_message="wall mounted",
        )
        corrected = store.reconcile_clarification_provenance(project.id)
        session.commit()
        assert corrected == 1
        ledger = store.load(project.id)
        item = active_requirements(ledger)[0]
        assert item["source"] == "clarification_user"
        assert item["explicit"] is True
        assert item["provenance"]["project_message_id"]

    with Session(engine) as session:
        reloaded = active_requirements(RequirementLedgerStore(session).load(project.id))
        assert reloaded[0]["source"] == "clarification_user"
        assert reloaded[0]["provenance"]["normalization_rule"] == "legacy_clarification_provenance_reconciled"
