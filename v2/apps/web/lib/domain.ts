import type { StatusTone } from "@/components/ui/status-badge";

export type Role =
  | "system_admin"
  | "compliance"
  | "site_manager"
  | "gate_operator"
  | "host"
  | "participant"
  | "viewer";

export type AuthenticatedUser = {
  id: string;
  handle: string;
  display_name: string;
  role: Role;
  permissions: string[];
};

export type SessionResponse = {
  user: AuthenticatedUser;
  expires_in_seconds: number;
};

export type Site = {
  id: string;
  seed_key: string;
  name: string;
  country_code: string;
  timezone: string;
  gate_mode: string;
  is_active: boolean;
};

export type Company = {
  id: string;
  seed_key: string;
  name: string;
  company_type: string;
  country_code: string;
  is_active: boolean;
};

export type LifeSavingRulesState = "confirmed" | "outdated" | "not_confirmed";

export type LifeSavingStatus = {
  status: LifeSavingRulesState;
  current_rules_version: number | null;
  confirmed_rules_version: number | null;
  language: string | null;
  acknowledged_at: string | null;
  method: string | null;
};

export type LifeSavingHistoryItem = {
  id: string;
  rules_version: number;
  language: string;
  statement_text: string;
  acknowledged_at: string;
  method: string;
};

export type Person = {
  id: string;
  seed_key: string;
  company_id: string;
  first_name: string;
  last_name: string;
  email: string;
  population: string;
  standing: "active" | "blocked" | "inactive";
  source_metadata: Record<string, unknown>;
  life_saving_rules?: LifeSavingStatus;
};

export type Visit = {
  id: string;
  seed_key: string;
  person_id: string;
  site_id: string;
  host_person_id: string | null;
  purpose: string;
  status: "planned" | "active" | "blocked" | "completed" | "cancelled";
  starts_at: string;
  ends_at: string;
};

export type AuditEvent = {
  id: string;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  reason: string;
  details: Record<string, unknown>;
  occurred_at: string;
};

export type InvitationStatus = "invited" | "pre_registered" | "evidence_ready";

export type Invitation = {
  id: string;
  seed_key: string;
  site_id: string;
  requested_by_id: string;
  invitee_email: string;
  population:
    | "renewi_driver"
    | "temporary_driver"
    | "external_driver"
    | "maintenance_contractor"
    | "permanent_contractor"
    | "visitor";
  company_name: string;
  purpose: string;
  starts_at: string;
  ends_at: string;
  status: InvitationStatus;
  response_status: "pending" | "accepted" | "declined";
  responded_at: string | null;
  registration_completed_at: string | null;
  delivery_status: "local_only" | "smtp_sent" | "smtp_failed";
  company_id: string | null;
  person_id: string | null;
  registered_name: string | null;
  visit_id: string | null;
  identity_document_uploaded_at: string | null;
  created_at: string;
  updated_at: string;
};

export type RegistrationResult = {
  invitation: Invitation;
  company_id: string;
  person_id: string;
  visit_id: string;
  company_created: boolean;
  person_created: boolean;
};

export type EvidenceType =
  | "id_card"
  | "driving_licence"
  | "vca_certificate"
  | "insurance_certificate";

export type EvidenceStatus =
  | "uploaded"
  | "extracted"
  | "verified"
  | "rejected"
  | "reupload_requested"
  | "superseded";

export type EvidenceAsset = {
  id: string;
  asset_key: string;
  evidence_type: EvidenceType;
  display_name: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  expected_fields: Record<string, unknown>;
  issue_date: string | null;
  expiry_date: string | null;
  is_active: boolean;
};

export type DrivingLicenceValidityAssessment = {
  assessment_status?: "appears_valid" | "appears_expired" | "needs_review";
  summary?: string;
  assessment_source?: string;
  checks?: Record<string, unknown>;
  limitations?: string[];
};

export type Evidence = {
  id: string;
  person_id: string;
  invitation_id: string | null;
  asset_id: string | null;
  evidence_type: EvidenceType;
  status: EvidenceStatus;
  filename: string;
  media_type: string;
  size_bytes: number;
  content_sha256: string;
  storage_mode: string;
  provider_mode: string;
  extracted_fields: Record<string, unknown>;
  field_confidence: Record<string, unknown>;
  validity_assessment: DrivingLicenceValidityAssessment;
  issue_date: string | null;
  expiry_date: string | null;
  review_notes: string | null;
  supersedes_id: string | null;
  uploaded_by_id: string;
  reviewed_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type TrainingQuestion = {
  id: string;
  prompt: string;
  options: string[];
};

export type TrainingModule = {
  id: string;
  code: string;
  name: string;
  language: string;
  passing_score: number;
  validity_days: number;
  questions: TrainingQuestion[];
  is_active: boolean;
};

export type TrainingOutcome = "passed" | "failed";

export type TrainingResult = {
  id: string;
  person_id: string;
  training_module_id: string;
  attempt_number: number;
  score: number;
  outcome: TrainingOutcome;
  completed_at: string;
  expires_at: string | null;
};

export type ComplianceCheckStatus =
  | "passed"
  | "missing"
  | "expired"
  | "failed"
  | "blocked";

export type ComplianceCheck = {
  code: string;
  label: string;
  kind: string;
  status: ComplianceCheckStatus;
  blocking: boolean;
  detail: string;
  requirement_id: string | null;
};

export type ComplianceEvaluation = {
  visit_id: string;
  person_id: string;
  evaluated_at: string;
  eligible: boolean;
  checks: ComplianceCheck[];
};

export type ApprovalDecision =
  | "pending"
  | "approved"
  | "rejected"
  | "correction_requested";

export type Approval = {
  id: string;
  visit_id: string;
  decision: ApprovalDecision;
  compliance_snapshot: ComplianceCheck[];
  reason: string;
  evaluated_by_id: string;
  decided_by_id: string | null;
  created_at: string;
  decided_at: string | null;
};

export type BlacklistSubjectType = "person" | "company";

export type BlacklistEntry = {
  id: string;
  subject_type: BlacklistSubjectType;
  person_id: string | null;
  company_id: string | null;
  reason: string;
  is_active: boolean;
  starts_at: string;
  ends_at: string | null;
  created_by_id: string;
  revoked_by_id: string | null;
  revoked_at: string | null;
};

export type AccessTokenStatus = "active" | "expired" | "revoked";

export type AccessToken = {
  id: string;
  visit_id: string;
  status: AccessTokenStatus;
  issued_by_id: string;
  issued_at: string;
  expires_at: string;
  revoked_by_id: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
};

export type TokenIssueResponse = {
  token: AccessToken;
  qr_payload: string;
  delivery_status: "smtp_sent" | "smtp_failed" | "local_only" | "unavailable";
};

export type GateDecision = "GRANT" | "DENY";

export type GateCheck = {
  code: string;
  label: string;
  status: "passed" | "failed";
  blocking: boolean;
  reason_code: string | null;
  detail: string;
  corrective_action: string | null;
};

export type IdentityVerification = {
  match: boolean;
  confidence: number;
  mode: string;
  provider_reference: string;
  evaluated_at: string;
};

export type GateEvaluationRequest = {
  token_reference: string;
  site_id: string;
  presentation_reference: string;
  comparison_confirmed: boolean;
};

export type GatePresentation = {
  invitation_id: string;
  person_id: string;
  person_name: string;
  email: string;
  company_name: string;
  population: string;
  purpose: string;
  site_name: string;
  starts_at: string;
  ends_at: string;
  uploads: {
    id: string | null;
    kind: "invitation_id" | "evidence";
    label: string;
    filename: string;
    media_type: string;
    status: string;
  }[];
};

export type GateDecisionResponse = {
  gate_event_id: string;
  decision: GateDecision;
  reason_codes: string[];
  reasons: string[];
  corrective_actions: string[];
  primary_reason_code: string;
  primary_reason: string;
  next_action: string;
  checks: GateCheck[];
  identity: IdentityVerification | null;
  token_id: string | null;
  visit_id: string | null;
  person_id: string | null;
  requested_site_id: string;
  occurred_at: string;
};

export type CurrentPresence = {
  gate_event_id: string | null;
  presence_event_id: string | null;
  person_id: string;
  person_name: string;
  population: string;
  id_expiry_date: string | null;
  visit_id: string | null;
  site_id: string;
  site_name: string;
  entered_at: string;
  visit_ends_at: string | null;
  decision: GateDecision;
  /** "walk_up" for someone who registered at the entrance QR; they have no visit. */
  source?: string;
  walk_up_registration_id?: string | null;
  site_key?: string | null;
};

export type PresenceEvent = {
  id: string;
  visit_id: string;
  person_id: string;
  site_id: string;
  gate_event_id: string | null;
  event_type: "entry" | "exit";
  occurred_at: string;
};

export type DashboardTotals = {
  site_count: number;
  active_visit_count: number;
  present_count: number;
  grant_count: number;
  denial_count: number;
  entry_count: number;
  exit_count: number;
};

export type DashboardSite = {
  site_id: string;
  site_name: string;
  country_code: string;
  active_visit_count: number;
  present_count: number;
  grant_count: number;
  denial_count: number;
  entry_count: number;
  exit_count: number;
};

export type DashboardDecision = {
  gate_event_id: string;
  occurred_at: string;
  site_id: string;
  site_name: string | null;
  visit_id: string | null;
  person_id: string | null;
  person_name: string | null;
  decision: GateDecision;
  reason_codes: string[];
  source?: string;
};

export type DashboardSnapshot = {
  as_of: string;
  activity_window_started_at: string;
  activity_hours: number;
  totals: DashboardTotals;
  sites: DashboardSite[];
  current_presence: CurrentPresence[];
  recent_decisions: DashboardDecision[];
};

export type DemoClock = {
  effective_at: string;
  updated_at: string;
  updated_by_id: string | null;
};

export type ExpiryProcessResult = {
  processed_at: string;
  created_alert_count: number;
  created_task_count: number;
  existing_alert_count: number;
  existing_task_count: number;
};

export type ExpiryAlert = {
  id: string;
  person_id: string;
  site_id: string;
  requirement_id: string;
  source_kind: "EVIDENCE" | "TRAINING";
  source_id: string;
  alert_code: string;
  expires_at: string;
  delivery_mode: string;
  delivery_status: string;
  provider_reference: string | null;
  created_at: string;
  created_by_id: string;
};

export type RevalidationTaskStatus = "OPEN" | "COMPLETED";

export type RevalidationTask = {
  id: string;
  person_id: string;
  site_id: string;
  requirement_id: string;
  source_kind: "EVIDENCE" | "TRAINING";
  source_id: string;
  status: RevalidationTaskStatus;
  created_at: string;
  completed_at: string | null;
  completed_by_id: string | null;
};

export type OnSiteRenewalResponse = {
  evidence_id: string;
  person_id: string;
  task_id: string;
  expiry_date: string;
  status: EvidenceStatus;
};

export type OnSiteIdRenewalResponse = {
  evidence_id: string;
  person_id: string;
  source_id: string;
  expiry_date: string;
  status: EvidenceStatus;
};

const roleLabels: Record<Role, string> = {
  system_admin: "System Admin",
  compliance: "Compliance / SHEQ",
  site_manager: "Site Manager",
  gate_operator: "Gate Operator",
  host: "Requester / Host",
  participant: "Contractor / Driver / Visitor",
  viewer: "Read-only Viewer"
};

// PUBLIC_INTERFACE
/**
 * Converts an API role value to its manager-facing label.
 */
export function roleLabel(role: Role): string {
  return roleLabels[role];
}

// PUBLIC_INTERFACE
/**
 * Converts a snake-case API enum into readable title text.
 */
export function enumLabel(value: string): string {
  return value
    .split("_")
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

// PUBLIC_INTERFACE
/**
 * Selects an accessible badge tone for a person or visit state.
 */
export function statusTone(status: string): StatusTone {
  if (
    status === "active" ||
    status === "completed" ||
    status === "verified" ||
    status === "evidence_ready" ||
    status === "passed" ||
    status === "approved"
  ) {
    return "success";
  }
  if (
    status === "blocked" ||
    status === "cancelled" ||
    status === "rejected" ||
    status === "failed" ||
    status === "expired" ||
    status === "revoked"
  ) {
    return "danger";
  }
  if (
    status === "planned" ||
    status === "invited" ||
    status === "uploaded" ||
    status === "extracted" ||
    status === "pending"
  ) {
    return "info";
  }
  if (
    status === "pre_registered" ||
    status === "reupload_requested" ||
    status === "missing" ||
    status === "correction_requested"
  ) {
    return "warning";
  }
  return "neutral";
}

// PUBLIC_INTERFACE
/**
 * Formats an API timestamp in the browser's current locale.
 */
// PUBLIC_INTERFACE
/**
 * Returns the wording and tone for a person's life-saving rules status. Text always
 * accompanies the colour so the status never depends on colour alone.
 */
export function lifeSavingBadge(state: LifeSavingRulesState): { label: string; tone: StatusTone } {
  if (state === "confirmed") return { label: "Confirmed", tone: "success" };
  if (state === "outdated") return { label: "New version to confirm", tone: "warning" };
  return { label: "Not confirmed", tone: "danger" };
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}
