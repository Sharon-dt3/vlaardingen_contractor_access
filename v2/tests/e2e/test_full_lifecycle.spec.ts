import { expect, test } from "@playwright/test";
import {
  apiUrl,
  expectSuccessful,
  findActiveSite,
  findActiveVisit,
  findSeededPerson,
  loginApiAsSeededRole,
  seededOpaqueReference
} from "./support/api";
import { hasBaselineRunner, restoreSeedBaseline } from "./support/baseline";
import { loginAsSeededRole } from "./support/auth";

test.describe.configure({ mode: "serial" });

test.describe("seeded invitation-to-renewal lifecycle", () => {
  test.beforeEach(async ({ request }) => {
    test.skip(
      !hasBaselineRunner(),
      "The private E2E baseline runner must restore the reset-and-seed baseline."
    );

    await restoreSeedBaseline(request);
  });

  test.afterEach(async ({ request }) => {
    if (hasBaselineRunner()) {
      await restoreSeedBaseline(request);
    }
  });

  test("restores Sofia's eligibility through verified renewal and records a later gate grant", async ({
    page,
    request
  }) => {
    await loginApiAsSeededRole(request, "administrator");

    const [sofia, site] = await Promise.all([
      findSeededPerson(request, "Sofia", "Janssen"),
      findActiveSite(request)
    ]);
    const visit = await findActiveVisit(request, sofia.id);

    const invitationsResponse = await request.get(apiUrl("/api/invitations"));
    await expectSuccessful(invitationsResponse, "Listing renewal invitations");
    const invitations = (await invitationsResponse.json()) as Array<{
      id: string;
      person_id: string | null;
      purpose: string;
      status: string;
    }>;
    const renewalInvitation = invitations.find(
      (invitation) =>
        invitation.person_id === sofia.id &&
        invitation.purpose === "Synthetic Batch 6 Sofia VCA renewal" &&
        invitation.status === "pre_registered"
    );
    expect(
      renewalInvitation,
      "The seeded lifecycle must retain Sofia's registered renewal invitation."
    ).toBeTruthy();

    const initialComplianceResponse = await request.get(
      apiUrl(`/api/visits/${visit.id}/compliance`)
    );
    await expectSuccessful(
      initialComplianceResponse,
      "Reading Sofia's initial compliance"
    );
    const initialCompliance = (await initialComplianceResponse.json()) as {
      eligible: boolean;
      checks: Array<{ code: string; status: string }>;
    };
    expect(initialCompliance.eligible).toBe(false);
    expect(
      initialCompliance.checks.find(
        (check) => check.code === "VCA_CERTIFICATE"
      )?.status
    ).toBe("expired");

    const expiryResponse = await request.post(apiUrl("/api/expiry/process"));
    await expectSuccessful(expiryResponse, "Processing expiry");

    const tasksResponse = await request.get(apiUrl("/api/revalidation/tasks"));
    await expectSuccessful(tasksResponse, "Listing re-validation tasks");
    const tasks = (await tasksResponse.json()) as Array<{
      id: string;
      person_id: string;
      source_kind: string;
      status: string;
    }>;
    const task = tasks.find(
      (candidate) =>
        candidate.person_id === sofia.id &&
        candidate.source_kind === "EVIDENCE" &&
        candidate.status === "OPEN"
    );
    expect(task, "Expiry processing must create Sofia's open evidence task.").toBeTruthy();

    const assetsResponse = await request.get(apiUrl("/api/evidence/assets"));
    await expectSuccessful(assetsResponse, "Listing synthetic evidence assets");
    const assets = (await assetsResponse.json()) as Array<{
      evidence_type: string;
      id: string;
      is_active: boolean;
    }>;
    const vcaAsset = assets.find(
      (asset) =>
        asset.evidence_type === "vca_certificate" && asset.is_active === true
    );
    expect(vcaAsset, "An active synthetic VCA asset must be available.").toBeTruthy();

    const attachedResponse = await request.post(
      apiUrl(`/api/invitations/${renewalInvitation?.id}/evidence/assets`),
      { data: { asset_id: vcaAsset?.id } }
    );
    await expectSuccessful(attachedResponse, "Attaching Sofia's renewal evidence");
    const attached = (await attachedResponse.json()) as { id: string; status: string };
    expect(attached.status).toBe("uploaded");

    const extractedResponse = await request.post(
      apiUrl(`/api/evidence/${attached.id}/extract`)
    );
    await expectSuccessful(extractedResponse, "Extracting Sofia's renewal evidence");

    const verifiedResponse = await request.post(
      apiUrl(`/api/evidence/${attached.id}/verify`),
      {
        data: {
          reason: "Verified deterministic renewal for final acceptance coverage."
        }
      }
    );
    await expectSuccessful(verifiedResponse, "Verifying Sofia's renewal evidence");
    const verified = (await verifiedResponse.json()) as {
      expiry_date: string | null;
      status: string;
    };
    expect(verified.status).toBe("verified");
    expect(verified.expiry_date).toBeTruthy();

    const completedResponse = await request.post(
      apiUrl(`/api/revalidation/tasks/${task?.id}/complete`)
    );
    await expectSuccessful(completedResponse, "Completing Sofia's re-validation");
    const completed = (await completedResponse.json()) as {
      completed_at: string | null;
      status: string;
    };
    expect(completed.status).toBe("COMPLETED");
    expect(completed.completed_at).toBeTruthy();

    const restoredComplianceResponse = await request.get(
      apiUrl(`/api/visits/${visit.id}/compliance`)
    );
    await expectSuccessful(
      restoredComplianceResponse,
      "Reading restored backend compliance"
    );
    const restoredCompliance = (await restoredComplianceResponse.json()) as {
      eligible: boolean;
      checks: Array<{ code: string; status: string }>;
    };
    expect(restoredCompliance.eligible).toBe(true);
    expect(
      restoredCompliance.checks.find(
        (check) => check.code === "VCA_CERTIFICATE"
      )?.status
    ).toBe("passed");

    // A grant requires a fresh operator-bound match against the invitation ID.
    const identityScanResponse = await request.post(
      apiUrl("/api/gate/identity-scans"),
      {
        multipart: {
          token_reference: seededOpaqueReference("sofia"),
          file: {
            name: "sofia-demo-id.pdf",
            mimeType: "application/pdf",
            buffer: Buffer.from(
              "DEMO - NOT A REAL CREDENTIAL\nInvitation ID for person_sofia\n"
            )
          }
        }
      }
    );
    await expectSuccessful(identityScanResponse, "Matching Sofia's invitation ID");
    const identityScan = (await identityScanResponse.json()) as {
      matched: boolean;
      reason_code: string;
    };
    expect(identityScan.matched).toBe(true);
    expect(identityScan.reason_code).toBe("INVITATION_ID_MATCHED");

    const grantResponse = await request.post(apiUrl("/api/gate/evaluations"), {
      data: {
        presentation_reference: "batch8-sofia-renewal-presentation",
        site_id: site.id,
        token_reference: seededOpaqueReference("sofia")
      }
    });
    await expectSuccessful(grantResponse, "Requesting Sofia's restored gate decision");
    const grant = (await grantResponse.json()) as {
      decision: string;
      identity: { mode: string } | null;
      primary_reason_code: string;
    };
    expect(grant.decision).toBe("GRANT");
    expect(grant.primary_reason_code).toBe("ACCESS_GRANTED");
    expect(grant.identity?.mode).toBe("DEMO");

    const auditResponse = await request.get(apiUrl("/api/audit/events"));
    await expectSuccessful(auditResponse, "Reading chronological audit evidence");
    const auditEvents = (await auditResponse.json()) as Array<{
      action: string;
      details: { person_id?: string; visit_id?: string };
      entity_id: string;
    }>;
    const lifecycleActions = auditEvents
      .filter(
        (event) =>
          event.details.person_id === sofia.id ||
          event.details.visit_id === visit.id
      )
      .map((event) => event.action);

    for (const action of [
      "expiry.alert_created",
      "revalidation.task_created",
      "evidence.verified",
      "revalidation.task_completed",
      "gate.granted"
    ]) {
      expect(lifecycleActions).toContain(action);
    }

    await loginAsSeededRole(page, "administrator");
    await page.goto("/visits");
    await expect(
      page.getByRole("heading", { name: "Training, approval & access workspace" })
    ).toBeVisible();
    await page.getByLabel("Person with verified invitation evidence").selectOption(visit.id);
    await expect(page.getByRole("heading", { name: "Sofia Janssen" })).toBeVisible();
  });
});
