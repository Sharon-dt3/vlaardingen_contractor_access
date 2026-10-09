"""Database lifecycle commands for migrations and deterministic demo state."""

from __future__ import annotations

import argparse
import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import get_settings
from app.database.session import SessionLocal, engine
from app.life_saving_content import SAMPLE_RULES_CONTENT, SAMPLE_RULES_VERSION
from app.models import (
    AccessToken,
    AccessTokenStatus,
    Approval,
    ApprovalDecision,
    AuditEvent,
    BlacklistEntry,
    BlacklistSubjectType,
    Company,
    ComplianceRequirement,
    ComplianceRequirementKind,
    DemoScenario,
    Evidence,
    EvidenceAsset,
    EvidenceStatus,
    EvidenceType,
    FoundationState,
    Invitation,
    InvitationStatus,
    LifeSavingRulesAcknowledgement,
    LifeSavingRulesVersion,
    Person,
    PersonStanding,
    Population,
    Role,
    Site,
    TrainingModule,
    TrainingOutcome,
    TrainingResult,
    UserAccount,
    Visit,
    VisitStatus,
)
from app.providers.storage import LocalStorage, put_private_reference
from app.security import deterministic_demo_salt, hash_password
from app.services.life_saving import content_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "services" / "api" / "alembic.ini"
MIGRATION_DIRECTORY = PROJECT_ROOT / "database" / "migrations"
DEMO_NAMESPACE = uuid.UUID("27f60552-86f3-4abf-b693-b98499494452")
SeedModel = TypeVar(
    "SeedModel",
    AccessToken,
    Approval,
    AuditEvent,
    BlacklistEntry,
    Company,
    DemoScenario,
    Evidence,
    EvidenceAsset,
    LifeSavingRulesAcknowledgement,
    LifeSavingRulesVersion,
    Person,
    Site,
    TrainingModule,
    TrainingResult,
    UserAccount,
    Visit,
)


def _demo_id(seed_key: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NAMESPACE, seed_key)


def _seed_record(database: Any, model: type[SeedModel], values: dict[str, Any]) -> None:
    database.merge(model(**values))


# PUBLIC_INTERFACE
def migrate_database() -> None:
    """Upgrade the configured database to the latest Alembic revision."""

    configuration = Config(str(ALEMBIC_INI))
    configuration.set_main_option("script_location", str(MIGRATION_DIRECTORY))
    command.upgrade(configuration, "head")


# PUBLIC_INTERFACE
def seed_database() -> None:
    """Create or reconcile the deterministic Batch 2 demo domain."""

    settings = get_settings()
    if not settings.demo_seed_password:
        raise RuntimeError("DEMO_SEED_PASSWORD must be available for local seeding.")
    seed_password = settings.demo_seed_password.get_secret_value()
    if not seed_password:
        raise RuntimeError("DEMO_SEED_PASSWORD must not be empty.")

    seeded_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Keep every seeded scenario inside one shared, already-open visit window.
    # Staggered future starts would cause the gate's intentional visit-window
    # precedence to mask the intended compliance, blacklist, and identity cases.
    visit_start = datetime.now(timezone.utc) - timedelta(minutes=1)
    visit_end = visit_start + timedelta(hours=10)
    site_id = _demo_id("site_vlaardingen")

    companies = [
        ("company_demo_logistics", "Delta Demo Logistics B.V.", "logistics_supplier"),
        (
            "company_demo_maintenance",
            "Northstar Demo Maintenance B.V.",
            "maintenance_supplier",
        ),
        ("company_demo_agency", "Harbor Demo Staffing B.V.", "employment_agency"),
        (
            "company_demo_permanent",
            "Circular Demo Services B.V.",
            "permanent_contractor",
        ),
        ("company_demo_visitors", "Independent Demo Visitors", "visitor_placeholder"),
        ("company_demo_renewi", "Renewi Demo Operations", "internal_demo"),
    ]
    people = [
        (
            "person_alex",
            "Alex",
            "van Dijk",
            Population.EXTERNAL_DRIVER,
            "company_demo_logistics",
            PersonStanding.ACTIVE,
            "happy_path",
        ),
        (
            "person_sofia",
            "Sofia",
            "Janssen",
            Population.MAINTENANCE_CONTRACTOR,
            "company_demo_maintenance",
            PersonStanding.ACTIVE,
            "expired_evidence",
        ),
        (
            "person_milan",
            "Milan",
            "de Boer",
            Population.VISITOR,
            "company_demo_visitors",
            PersonStanding.ACTIVE,
            "training_failure",
        ),
        (
            "person_noah",
            "Noah",
            "Peters",
            Population.EXTERNAL_DRIVER,
            "company_demo_logistics",
            PersonStanding.ACTIVE,
            "blacklist",
        ),
        (
            "person_emma",
            "Emma",
            "Visser",
            Population.PERMANENT_CONTRACTOR,
            "company_demo_permanent",
            PersonStanding.ACTIVE,
            "identity_mismatch",
        ),
        (
            "person_lucas",
            "Lucas",
            "Smit",
            Population.EXTERNAL_DRIVER,
            "company_demo_logistics",
            PersonStanding.ACTIVE,
            "revalidation",
        ),
        (
            "person_eva",
            "Eva",
            "Mulder",
            Population.RENEWI_DRIVER,
            "company_demo_renewi",
            PersonStanding.ACTIVE,
            "population_reference",
        ),
        (
            "person_sam",
            "Sam",
            "Meijer",
            Population.TEMPORARY_DRIVER,
            "company_demo_agency",
            PersonStanding.ACTIVE,
            "population_reference",
        ),
        (
            "person_ruben",
            "Ruben",
            "Bakker",
            Population.MAINTENANCE_CONTRACTOR,
            "company_demo_maintenance",
            PersonStanding.ACTIVE,
            "life_saving_rules_missing",
        ),
    ]
    # Demo authentication has one account; people and scenarios remain for workflows.
    roles = [
        ("admin.demo", "Demo System Administrator", Role.SYSTEM_ADMIN, None),
    ]
    scenarios = [
        ("happy_path", "Happy path", "Eligible person ready for a grant."),
        (
            "expired_evidence",
            "Expired evidence",
            "Expired required identity evidence blocks access.",
        ),
        (
            "training_failure",
            "Training failure",
            "Latest required site-rules attempt did not pass.",
        ),
        ("blacklist", "Blacklist", "An active person-level blacklist blocks access."),
        (
            "identity_mismatch",
            "Identity mismatch",
            "Presented synthetic identity does not match registration.",
        ),
        (
            "revalidation",
            "Re-validation",
            "Evidence crosses expiry and can be renewed deterministically.",
        ),
        (
            "life_saving_rules_missing",
            "Life-saving rules not confirmed",
            "Everything else is in order, but the contractor has not confirmed the life-saving rules.",
        ),
        (
            "full_demo",
            "Full demo",
            "All people, roles, scenarios, and baseline events are restored.",
        ),
    ]

    with SessionLocal.begin() as database:
        database.merge(
            FoundationState(
                key="demo-foundation",
                seed_version="batch-3-v1",
                seeded_at=seeded_at,
            )
        )
        _seed_record(
            database,
            Site,
            {
                "id": site_id,
                "seed_key": "site_vlaardingen",
                "name": "Vlaardingen",
                "country_code": "NL",
                "timezone": "Europe/Amsterdam",
                "gate_mode": "software_kiosk",
                "is_active": True,
            },
        )
        for seed_key, name, company_type in companies:
            _seed_record(
                database,
                Company,
                {
                    "id": _demo_id(seed_key),
                    "seed_key": seed_key,
                    "name": name,
                    "company_type": company_type,
                    "country_code": "NL",
                    "is_active": True,
                },
            )

        for (
            seed_key,
            first_name,
            last_name,
            population,
            company_key,
            standing,
            scenario,
        ) in people:
            _seed_record(
                database,
                Person,
                {
                    "id": _demo_id(seed_key),
                    "seed_key": seed_key,
                    "company_id": _demo_id(company_key),
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{seed_key.removeprefix('person_')}@example.invalid",
                    "population": population,
                    "standing": standing,
                    "source_metadata": {
                        "mode": "DEMO",
                        "scenario": scenario,
                        "synthetic": True,
                    },
                },
            )
        database.flush()

        host_person_id = _demo_id("person_eva")
        for (
            seed_key,
            _,
            _,
            _,
            _,
            standing,
            scenario,
        ) in people:
            visit_status = (
                VisitStatus.BLOCKED
                if standing is PersonStanding.BLOCKED
                else VisitStatus.ACTIVE
            )
            _seed_record(
                database,
                Visit,
                {
                    "id": _demo_id(f"visit_{seed_key}"),
                    "seed_key": f"visit_{seed_key}",
                    "person_id": _demo_id(seed_key),
                    "site_id": site_id,
                    "host_person_id": (
                        host_person_id if seed_key == "person_milan" else None
                    ),
                    "purpose": f"Synthetic {scenario.replace('_', ' ')} demonstration",
                    "status": visit_status,
                    "starts_at": visit_start,
                    "ends_at": visit_end,
                },
            )

        for handle, display_name, role, person_key in roles:
            _seed_record(
                database,
                UserAccount,
                {
                    "id": _demo_id(f"account_{handle}"),
                    "handle": handle,
                    "display_name": display_name,
                    "password_hash": hash_password(
                        seed_password,
                        salt=deterministic_demo_salt(handle),
                    ),
                    "role": role,
                    "person_id": _demo_id(person_key) if person_key else None,
                    "is_active": True,
                },
            )

        for seed_key, name, description in scenarios:
            _seed_record(
                database,
                DemoScenario,
                {
                    "id": _demo_id(f"scenario_{seed_key}"),
                    "seed_key": seed_key,
                    "name": name,
                    "description": description,
                    "baseline": {
                        "version": "batch-3-v1",
                        "synthetic": True,
                    },
                    "is_active": True,
                },
            )
        database.flush()

        storage = LocalStorage(settings.storage_local_path)
        synthetic_assets = [
            (
                "demo_id_card_v1",
                EvidenceType.ID_CARD,
                "Demo identity card",
                "demo_id_card_v1.txt",
                {
                    "holder_name": "Alex van Dijk",
                    "document_number": "DEMO-ID-1001",
                    "nationality": "NL",
                    "issue_date": "2026-01-01",
                    "expiry_date": "2031-01-01",
                },
                date(2026, 1, 1),
                date(2031, 1, 1),
            ),
            (
                "demo_nl_driving_licence_v1",
                EvidenceType.DRIVING_LICENCE,
                "Demo Dutch-style driving licence",
                "demo_nl_driving_licence_v1.txt",
                {
                    "holder_name": "Alex van Dijk",
                    "document_number": "DEMO-DL-2001",
                    "categories": ["B", "C", "CE"],
                    "code_95": True,
                    "issue_date": "2025-06-01",
                    "expiry_date": "2030-06-01",
                },
                date(2025, 6, 1),
                date(2030, 6, 1),
            ),
            (
                "demo_vca_certificate_v1",
                EvidenceType.VCA_CERTIFICATE,
                "Demo VCA certificate",
                "demo_vca_certificate_v1.txt",
                {
                    "holder_name": "Sofia Janssen",
                    "certificate_number": "DEMO-VCA-3001",
                    "provider": "Demo Safety Institute",
                    "issue_date": "2026-01-15",
                    "expiry_date": "2029-01-15",
                },
                date(2026, 1, 15),
                date(2029, 1, 15),
            ),
            (
                "demo_insurance_certificate_v1",
                EvidenceType.INSURANCE_CERTIFICATE,
                "Demo company insurance certificate",
                "demo_insurance_certificate_v1.txt",
                {
                    "company_name": "Delta Demo Logistics B.V.",
                    "policy_number": "DEMO-POLICY-4001",
                    "insurer": "Demo Mutual Insurance",
                    "issue_date": "2026-01-01",
                    "expiry_date": "2027-01-01",
                },
                date(2026, 1, 1),
                date(2027, 1, 1),
            ),
        ]
        for (
            asset_key,
            evidence_type,
            display_name,
            filename,
            expected_fields,
            issue_date,
            expiry_date,
        ) in synthetic_assets:
            content = (
                "DEMO — NOT A REAL CREDENTIAL\n"
                f"Asset: {asset_key}\n"
                f"Type: {evidence_type.value}\n"
                "All names, identifiers, dates, and organizations are fictional.\n"
            ).encode("utf-8")
            stored = put_private_reference(database, storage, content)
            _seed_record(
                database,
                EvidenceAsset,
                {
                    "id": _demo_id(f"evidence_asset_{asset_key}"),
                    "asset_key": asset_key,
                    "evidence_type": evidence_type,
                    "display_name": display_name,
                    "filename": filename,
                    "media_type": "text/plain",
                    "size_bytes": stored.size_bytes,
                    "content_sha256": stored.sha256,
                    "storage_reference": stored.reference,
                    "expected_fields": expected_fields,
                    "issue_date": issue_date,
                    "expiry_date": expiry_date,
                    "is_active": True,
                },
            )

        training_modules = [
            (
                "sheq_basics",
                "SHEQ Basics",
                "en",
                80,
                365,
                [
                    {
                        "id": "ppe",
                        "prompt": (
                            "Which action is required before entering a "
                            "controlled work area?"
                        ),
                        "options": [
                            "Wear the required personal protective equipment",
                            "Start work immediately",
                            "Share a gate token",
                        ],
                        "correct_option": 0,
                    },
                    {
                        "id": "incident",
                        "prompt": "What should you do after observing an unsafe condition?",
                        "options": [
                            "Ignore it if no one is hurt",
                            "Report it through the site safety process",
                            "Wait until the end of the month",
                        ],
                        "correct_option": 1,
                    },
                ],
            ),
            (
                "vlaardingen_site_rules",
                "Vlaardingen Site Rules",
                "en",
                80,
                365,
                [
                    {
                        "id": "gate",
                        "prompt": "What is required when entering Vlaardingen?",
                        "options": [
                            "Present the assigned opaque access token",
                            "Use another visitor's QR card",
                            "Enter without recording arrival",
                        ],
                        "correct_option": 0,
                    },
                    {
                        "id": "escort",
                        "prompt": "What must a visitor do outside approved areas?",
                        "options": [
                            "Follow site signage and host instructions",
                            "Access any operational area",
                            "Ignore barrier markings",
                        ],
                        "correct_option": 0,
                    },
                ],
            ),
        ]
        for code, name, language, passing_score, validity_days, questions in training_modules:
            _seed_record(
                database,
                TrainingModule,
                {
                    "id": _demo_id(f"training_module_{code}"),
                    "code": code,
                    "name": name,
                    "language": language,
                    "passing_score": passing_score,
                    "validity_days": validity_days,
                    "questions": questions,
                    "is_active": True,
                },
            )

        # Compliance requirements reference these module IDs, so persist parents first.
        database.flush()

        for population in Population:
            for code, label, module_code in (
                ("SHEQ_BASICS", "SHEQ Basics", "sheq_basics"),
                (
                    "VLAARDINGEN_SITE_RULES",
                    "Vlaardingen Site Rules",
                    "vlaardingen_site_rules",
                ),
            ):
                _seed_record(
                    database,
                    ComplianceRequirement,
                    {
                        "id": _demo_id(
                            f"compliance_{population.value.lower()}_{code.lower()}"
                        ),
                        "site_id": site_id,
                        "population": population,
                        "code": code,
                        "label": label,
                        "requirement_kind": ComplianceRequirementKind.TRAINING,
                        "evidence_type": None,
                        "training_module_id": _demo_id(
                            f"training_module_{module_code}"
                        ),
                        "is_required": True,
                        "is_blocking": True,
                        "is_active": True,
                    },
                )

        # Everyone entering Vlaardingen must have confirmed the life-saving rules in
        # force. The wording is sample text until Renewi supplies its own.
        rules_id = _demo_id(f"life_saving_rules_v{SAMPLE_RULES_VERSION}")
        _seed_record(
            database,
            LifeSavingRulesVersion,
            {
                "id": rules_id,
                "version": SAMPLE_RULES_VERSION,
                "content": SAMPLE_RULES_CONTENT,
                "is_current": True,
                "published_at": seeded_at,
            },
        )
        _seed_record(
            database,
            ComplianceRequirement,
            {
                "id": _demo_id("compliance_all_life_saving_rules"),
                "site_id": site_id,
                "population": None,
                "code": "LIFE_SAVING_RULES",
                "label": "Life-saving rules confirmed",
                "requirement_kind": ComplianceRequirementKind.LIFE_SAVING_RULES,
                "evidence_type": None,
                "training_module_id": None,
                "is_required": True,
                "is_blocking": True,
                "is_active": True,
            },
        )
        database.flush()

        admin_id = _demo_id("account_admin.demo")
        evidence_requirements = {
            Population.EXTERNAL_DRIVER: (
                (
                    "DRIVING_LICENCE",
                    "Verified driving licence",
                    EvidenceType.DRIVING_LICENCE,
                ),
            ),
            Population.RENEWI_DRIVER: (
                ("DRIVING_LICENCE", "Verified driving licence", EvidenceType.DRIVING_LICENCE),
            ),
            Population.TEMPORARY_DRIVER: (
                ("DRIVING_LICENCE", "Verified driving licence", EvidenceType.DRIVING_LICENCE),
            ),
            Population.MAINTENANCE_CONTRACTOR: (
                ("ID_CARD", "Verified identity card", EvidenceType.ID_CARD),
            ),
            Population.PERMANENT_CONTRACTOR: (
                ("ID_CARD", "Verified identity card", EvidenceType.ID_CARD),
            ),
            Population.VISITOR: (
                ("ID_CARD", "Verified identity card", EvidenceType.ID_CARD),
            ),
        }
        for population, requirements in evidence_requirements.items():
            for code, label, evidence_type in requirements:
                _seed_record(
                    database,
                    ComplianceRequirement,
                    {
                        "id": _demo_id(
                            f"compliance_{population.value.lower()}_{code.lower()}"
                        ),
                        "site_id": site_id,
                        "population": population,
                        "code": code,
                        "label": label,
                        "requirement_kind": ComplianceRequirementKind.EVIDENCE,
                        "evidence_type": evidence_type,
                        "training_module_id": None,
                        "is_required": True,
                        "is_blocking": True,
                        "is_active": True,
                    },
                )

        # These records deliberately use current relative dates so each reset
        # recreates resolvable gate scenarios regardless of the calendar day.
        gate_now = datetime.now(timezone.utc)
        # The gate now checks the completed invitation workflow as well as
        # compliance. Give each deterministic persona a linked, accepted
        # invitation and a private synthetic ID for single-use gate matching.
        for person_key in (
            "person_alex",
            "person_sofia",
            "person_milan",
            "person_noah",
            "person_emma",
            "person_ruben",
        ):
            person = next(item for item in people if item[0] == person_key)
            company = next(item for item in companies if item[0] == person[4])
            invitation_key = (
                "invitation_sofia_vca_renewal"
                if person_key == "person_sofia"
                else f"invitation_{person_key}"
            )
            identity_content = (
                f"DEMO - NOT A REAL CREDENTIAL\n"
                f"Invitation ID for {person_key}\n"
            ).encode("utf-8")
            stored_identity = put_private_reference(database, storage, identity_content)
            _seed_record(
                database,
                Invitation,
                {
                    "id": _demo_id(invitation_key),
                    "seed_key": invitation_key,
                    "site_id": site_id,
                    "requested_by_id": admin_id,
                    "invitee_email": f"{person_key.removeprefix('person_')}@example.invalid",
                    "population": person[3],
                    "company_name": company[1],
                    "purpose": (
                        "Synthetic Batch 6 Sofia VCA renewal"
                        if person_key == "person_sofia"
                        else f"Synthetic {person[6].replace('_', ' ')} demonstration"
                    ),
                    "starts_at": visit_start,
                    "ends_at": visit_end,
                    "status": InvitationStatus.PRE_REGISTERED,
                    "company_id": _demo_id(person[4]),
                    "person_id": _demo_id(person_key),
                    "visit_id": _demo_id(f"visit_{person_key}"),
                    "response_status": "accepted",
                    "responded_at": gate_now,
                    "identity_document_sha256": stored_identity.sha256,
                    "identity_document_storage_reference": stored_identity.reference,
                    "identity_document_media_type": "application/pdf",
                    "identity_document_uploaded_at": gate_now,
                    "created_at": gate_now,
                    "updated_at": gate_now,
                },
            )
        gate_people = (
            ("person_alex", "happy_path"),
            ("person_sofia", "expired_evidence"),
            ("person_milan", "training_failure"),
            ("person_noah", "blacklist"),
            ("person_emma", "identity_mismatch"),
            ("person_ruben", "life_saving_rules_missing"),
        )
        # Every Batch 4 gate scenario needs one resolvable token after reset.
        # Fixed record IDs and merge-based seeding preserve the one-active-token
        # invariant across repeated seed runs without creating duplicates.
        active_token_people = (
            "person_alex",
            "person_sofia",
            "person_milan",
            "person_noah",
            "person_emma",
            "person_ruben",
        )
        evidence_rows = (
            ("person_alex", EvidenceType.ID_CARD, gate_now.date() + timedelta(days=365)),
            (
                "person_alex",
                EvidenceType.DRIVING_LICENCE,
                gate_now.date() + timedelta(days=365),
            ),
            ("person_sofia", EvidenceType.ID_CARD, gate_now.date() - timedelta(days=1)),
            ("person_milan", EvidenceType.ID_CARD, gate_now.date() + timedelta(days=365)),
            ("person_noah", EvidenceType.ID_CARD, gate_now.date() + timedelta(days=365)),
            (
                "person_noah",
                EvidenceType.DRIVING_LICENCE,
                gate_now.date() + timedelta(days=365),
            ),
            ("person_emma", EvidenceType.ID_CARD, gate_now.date() + timedelta(days=365)),
            ("person_ruben", EvidenceType.ID_CARD, gate_now.date() + timedelta(days=365)),
        )
        for person_key, evidence_type, expiry_date in evidence_rows:
            _seed_record(
                database,
                Evidence,
                {
                    "id": _demo_id(f"evidence_{person_key}_{evidence_type.value}"),
                    "person_id": _demo_id(person_key),
                    "invitation_id": None,
                    "asset_id": None,
                    "evidence_type": evidence_type,
                    "status": EvidenceStatus.VERIFIED,
                    "filename": f"{person_key}_{evidence_type.value}_demo.txt",
                    "media_type": "text/plain",
                    "size_bytes": 128,
                    "content_sha256": hashlib.sha256(
                        f"{person_key}:{evidence_type.value}".encode("utf-8")
                    ).hexdigest(),
                    "storage_reference": f"seeded/{person_key}/{evidence_type.value}",
                    "storage_mode": "LOCAL",
                    "provider_mode": "DEMO",
                    "extracted_fields": {"synthetic": True},
                    "field_confidence": {},
                    "issue_date": gate_now.date() - timedelta(days=30),
                    "expiry_date": expiry_date,
                    "review_notes": "Deterministic Batch 4 gate scenario evidence.",
                    "supersedes_id": None,
                    "uploaded_by_id": admin_id,
                    "reviewed_by_id": admin_id,
                    "created_at": gate_now,
                    "updated_at": gate_now,
                },
            )

        for person_key, _ in gate_people:
            for module_code in ("sheq_basics", "vlaardingen_site_rules"):
                site_rules_failed = (
                    person_key == "person_milan"
                    and module_code == "vlaardingen_site_rules"
                )
                _seed_record(
                    database,
                    TrainingResult,
                    {
                        "id": _demo_id(f"training_{person_key}_{module_code}"),
                        "person_id": _demo_id(person_key),
                        "training_module_id": _demo_id(
                            f"training_module_{module_code}"
                        ),
                        "attempt_number": 1,
                        "score": 50 if site_rules_failed else 100,
                        "outcome": (
                            TrainingOutcome.FAILED
                            if site_rules_failed
                            else TrainingOutcome.PASSED
                        ),
                        "answers": {},
                        "completed_at": gate_now,
                        "expires_at": (
                            None
                            if site_rules_failed
                            else gate_now + timedelta(days=365)
                        ),
                    },
                )
            _seed_record(
                database,
                Approval,
                {
                    "id": _demo_id(f"approval_{person_key}"),
                    "visit_id": _demo_id(f"visit_{person_key}"),
                    "decision": ApprovalDecision.APPROVED,
                    "compliance_snapshot": [],
                    "reason": "Seeded prior approval for deterministic gate scenario.",
                    "evaluated_by_id": admin_id,
                    "decided_by_id": admin_id,
                    "created_at": gate_now,
                    "decided_at": gate_now,
                },
            )

        english = SAMPLE_RULES_CONTENT["translations"]["en"]
        dutch = SAMPLE_RULES_CONTENT["translations"]["nl"]
        for person_key, *_ in people:
            if person_key == "person_ruben":
                continue
            language, translation = (
                ("nl", dutch) if person_key in {"person_eva", "person_sam"} else ("en", english)
            )
            _seed_record(
                database,
                LifeSavingRulesAcknowledgement,
                {
                    "id": _demo_id(f"life_saving_ack_{person_key}"),
                    "person_id": _demo_id(person_key),
                    "rules_version_id": rules_id,
                    "language": language,
                    "statement_text": translation["statement"],
                    "content_sha256": content_sha256(translation),
                    "acknowledged_at": gate_now,
                    "method": "seeded_demo",
                    "invitation_id": None,
                },
            )

        for person_key in active_token_people:
            reference = (
                f"renewi-access:demo:{person_key.removeprefix('person_')}:"
                "opaque-reference"
            )
            _seed_record(
                database,
                AccessToken,
                {
                    "id": _demo_id(f"token_{person_key}"),
                    "visit_id": _demo_id(f"visit_{person_key}"),
                    "reference_hash": hashlib.sha256(
                        reference.encode("utf-8")
                    ).hexdigest(),
                    "status": AccessTokenStatus.ACTIVE,
                    "issued_by_id": admin_id,
                    "issued_at": gate_now,
                    "expires_at": gate_now + timedelta(hours=8),
                    "revoked_by_id": None,
                    "revoked_at": None,
                    "revoke_reason": None,
                },
            )

        _seed_record(
            database,
            BlacklistEntry,
            {
                "id": _demo_id("blacklist_person_noah"),
                "subject_type": BlacklistSubjectType.PERSON,
                "person_id": _demo_id("person_noah"),
                "company_id": None,
                "reason": "Deterministic Batch 4 active blacklist scenario.",
                "is_active": True,
                "starts_at": gate_now,
                "ends_at": None,
                "created_by_id": admin_id,
                "revoked_by_id": None,
                "revoked_at": None,
            },
        )

        for index, (
            seed_key,
            first_name,
            last_name,
            _,
            _,
            _,
            scenario,
        ) in enumerate(people):
            _seed_record(
                database,
                AuditEvent,
                {
                    "id": _demo_id(f"audit_seed_{seed_key}"),
                    "actor_id": admin_id,
                    "action": "demo.person.seeded",
                    "entity_type": "person",
                    "entity_id": str(_demo_id(seed_key)),
                    "reason": (
                        f"Created fictional {first_name} {last_name} for the "
                        f"{scenario.replace('_', ' ')} baseline."
                    ),
                    "details": {
                        "mode": "DEMO",
                        "scenario": scenario,
                        "synthetic": True,
                    },
                    "occurred_at": seeded_at + timedelta(minutes=index),
                },
            )


# PUBLIC_INTERFACE
def reset_database() -> None:
    """Clear application tables while retaining Alembic revision history.

    Table names come exclusively from PostgreSQL's inspected schema and are
    quoted by the active dialect before use.
    """

    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = [
            name
            for name in inspector.get_table_names(schema="public")
            if name != "alembic_version"
        ]
        if not table_names:
            return

        preparer = connection.dialect.identifier_preparer
        qualified_tables = ", ".join(
            f"{preparer.quote_schema('public')}.{preparer.quote(name)}"
            for name in sorted(table_names)
        )
        connection.exec_driver_sql(
            f"TRUNCATE TABLE {qualified_tables} RESTART IDENTITY CASCADE"
        )


# PUBLIC_INTERFACE
def main() -> None:
    """Parse and execute a database lifecycle command."""

    parser = argparse.ArgumentParser(
        description="Manage the Renewi demo database lifecycle."
    )
    parser.add_argument(
        "command",
        choices=("migrate", "seed", "reset"),
        help="Lifecycle command to execute.",
    )
    arguments = parser.parse_args()
    selected_command: Literal["migrate", "seed", "reset"] = arguments.command

    commands = {
        "migrate": migrate_database,
        "seed": seed_database,
        "reset": reset_database,
    }
    commands[selected_command]()


if __name__ == "__main__":
    main()
