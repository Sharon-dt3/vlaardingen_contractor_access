"""Persisted model registry."""

from app.models.domain import (
    AuditEvent,
    Company,
    DemoScenario,
    Evidence,
    EvidenceAsset,
    EvidenceStatus,
    EvidenceType,
    Invitation,
    InvitationStatus,
    Person,
    PersonStanding,
    Population,
    Role,
    Site,
    UserAccount,
    Visit,
    VisitStatus,
)
from app.models.batch3 import (
    AccessToken,
    AccessTokenStatus,
    Approval,
    ApprovalDecision,
    BlacklistEntry,
    BlacklistSubjectType,
    ComplianceRequirement,
    ComplianceRequirementKind,
    TrainingModule,
    TrainingOutcome,
    TrainingResult,
)
from app.models.batch4 import GateDecision, GateEvent, IdentityVerification
from app.models.batch5 import PresenceEvent, PresenceEventType
from app.models.gate_identity_scan import GateIdentityScan
from app.models.life_saving import (
    LifeSavingRulesAcknowledgement,
    LifeSavingRulesVersion,
)
from app.models.accounts import AccountToken
from app.models.walk_up import SiteAccessSettings, WalkUpPending, WalkUpRegistration
from app.models.batch6 import (
    DemoClock,
    ExpiryAlert,
    ExpirySubjectKind,
    RevalidationTask,
    RevalidationTaskStatus,
)
from app.models.foundation import FoundationState
from app.models.private_erasure import PrivateErasureJob

__all__ = [
    "AccessToken",
    "AccessTokenStatus",
    "Approval",
    "ApprovalDecision",
    "AuditEvent",
    "BlacklistEntry",
    "BlacklistSubjectType",
    "Company",
    "ComplianceRequirement",
    "ComplianceRequirementKind",
    "DemoClock",
    "DemoScenario",
    "Evidence",
    "EvidenceAsset",
    "EvidenceStatus",
    "EvidenceType",
    "ExpiryAlert",
    "ExpirySubjectKind",
    "FoundationState",
    "GateDecision",
    "GateEvent",
    "GateIdentityScan",
    "IdentityVerification",
    "Invitation",
    "LifeSavingRulesAcknowledgement",
    "AccountToken",
    "SiteAccessSettings",
    "WalkUpPending",
    "WalkUpRegistration",
    "LifeSavingRulesVersion",
    "InvitationStatus",
    "Person",
    "PersonStanding",
    "Population",
    "PresenceEvent",
    "PresenceEventType",
    "PrivateErasureJob",
    "RevalidationTask",
    "RevalidationTaskStatus",
    "Role",
    "Site",
    "TrainingModule",
    "TrainingOutcome",
    "TrainingResult",
    "UserAccount",
    "Visit",
    "VisitStatus",
]
