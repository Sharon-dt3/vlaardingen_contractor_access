import { expect, test } from "@playwright/test";
import {
  apiUrl,
  expectSuccessful,
  findActiveSite,
  findSeededPerson,
  loginApiAsSeededRole,
  seededOpaqueReference
} from "./support/api";
import { hasBaselineRunner, restoreSeedBaseline } from "./support/baseline";

type DenialScenario = {
  firstName: string;
  lastName: string;
  personKey: string;
  presentationReference: string;
  reasonCode: string;
};

const denialScenarios: DenialScenario[] = [
  {
    firstName: "Sofia",
    lastName: "Janssen",
    personKey: "sofia",
    presentationReference: "batch8-sofia-expired-evidence",
    reasonCode: "VCA_EXPIRED"
  },
  {
    firstName: "Milan",
    lastName: "de Boer",
    personKey: "milan",
    presentationReference: "batch8-milan-training-failure",
    reasonCode: "SITE_RULES_NOT_PASSED"
  },
  {
    firstName: "Noah",
    lastName: "Peters",
    personKey: "noah",
    presentationReference: "batch8-noah-blacklist",
    reasonCode: "PERSON_BLACKLISTED"
  },
  {
    firstName: "Emma",
    lastName: "Visser",
    personKey: "emma",
    presentationReference: "batch8-emma-identity-mismatch",
    reasonCode: "IDENTITY_MISMATCH"
  }
];

test.describe.configure({ mode: "serial" });

test.describe("deterministic server-authoritative gate denials", () => {
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

  for (const scenario of denialScenarios) {
    test(`${scenario.firstName} receives the documented ${scenario.reasonCode} denial`, async ({
      request
    }) => {
      await loginApiAsSeededRole(request, "administrator");

      const [person, site] = await Promise.all([
        findSeededPerson(request, scenario.firstName, scenario.lastName),
        findActiveSite(request)
      ]);

      const presenceBeforeResponse = await request.get(apiUrl("/api/presence"));
      await expectSuccessful(
        presenceBeforeResponse,
        "Reading presence before a denied decision"
      );
      const presenceBefore = (await presenceBeforeResponse.json()) as Array<{
        person_id: string;
      }>;
      expect(presenceBefore.some((entry) => entry.person_id === person.id)).toBe(false);

      // The earlier invitation step is complete in the disposable seed; the
      // operator must still scan its ID for each individual gate attempt.
      const identityScanResponse = await request.post(
        apiUrl("/api/gate/identity-scans"),
        {
          multipart: {
            token_reference: seededOpaqueReference(scenario.personKey),
            file: {
              name: `${scenario.personKey}-demo-id.pdf`,
              mimeType: "application/pdf",
              buffer: Buffer.from(
                `DEMO - NOT A REAL CREDENTIAL\nInvitation ID for person_${scenario.personKey}\n`
              )
            }
          }
        }
      );
      await expectSuccessful(identityScanResponse, "Matching the seeded invitation ID");
      const identityScan = (await identityScanResponse.json()) as {
        matched: boolean;
      };
      expect(identityScan.matched).toBe(true);

      const decisionResponse = await request.post(apiUrl("/api/gate/evaluations"), {
        data: {
          presentation_reference: scenario.presentationReference,
          site_id: site.id,
          token_reference: seededOpaqueReference(scenario.personKey)
        }
      });
      await expectSuccessful(
        decisionResponse,
        "Requesting a seeded denial decision"
      );
      const decision = (await decisionResponse.json()) as {
        corrective_actions: string[];
        decision: string;
        identity: { mode: string } | null;
        next_action: string;
        primary_reason: string;
        primary_reason_code: string;
        reason_codes: string[];
      };

      expect(decision.decision).toBe("DENY");
      expect(decision.primary_reason_code).toBe(scenario.reasonCode);
      expect(decision.reason_codes).toContain(scenario.reasonCode);
      expect(decision.primary_reason).not.toHaveLength(0);
      expect(decision.next_action).not.toHaveLength(0);
      expect(decision.corrective_actions).not.toHaveLength(0);

      if (scenario.reasonCode === "IDENTITY_MISMATCH") {
        expect(decision.identity?.mode).toBe("DEMO");
      } else {
        expect(decision.identity?.mode).toBe("DEMO");
      }

      const presenceAfterResponse = await request.get(apiUrl("/api/presence"));
      await expectSuccessful(
        presenceAfterResponse,
        "Reading presence after a denied decision"
      );
      const presenceAfter = (await presenceAfterResponse.json()) as Array<{
        person_id: string;
      }>;
      expect(presenceAfter.some((entry) => entry.person_id === person.id)).toBe(
        false
      );
    });
  }
});
