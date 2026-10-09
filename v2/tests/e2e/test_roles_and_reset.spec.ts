import { expect, test } from "@playwright/test";
import {
  apiUrl,
  expectSuccessful,
  loginApiAsSeededRole
} from "./support/api";
import { hasBaselineRunner, restoreSeedBaseline } from "./support/baseline";
import { loginAsSeededRole, type SeededRole } from "./support/auth";

type RoleExpectation = {
  forbiddenPath?: string;
  role: SeededRole;
  visibleNavigation: string[];
};

const roleExpectations: RoleExpectation[] = [
  {
    role: "administrator",
    visibleNavigation: [
      "Overview",
      "Invitations",
      "People",
      "Companies",
      "Visits",
      "Gate kiosk",
      "Audit trail",
      "Settings"
    ]
  },
  {
    role: "compliance",
    forbiddenPath: "/api/gate/evaluations",
    visibleNavigation: [
      "Overview",
      "Invitations",
      "People",
      "Companies",
      "Visits",
      "Audit trail"
    ]
  },
  {
    role: "manager",
    forbiddenPath: "/api/gate/evaluations",
    visibleNavigation: [
      "Overview",
      "Invitations",
      "People",
      "Companies",
      "Visits",
      "Audit trail"
    ]
  },
  {
    role: "gateOperator",
    forbiddenPath: "/api/audit/events",
    visibleNavigation: ["Overview", "People", "Visits", "Gate kiosk"]
  },
  {
    role: "host",
    forbiddenPath: "/api/people",
    visibleNavigation: ["Overview", "Invitations"]
  },
  {
    role: "participant",
    forbiddenPath: "/api/sites",
    visibleNavigation: ["Overview"]
  },
  {
    role: "viewer",
    forbiddenPath: "/api/gate/evaluations",
    visibleNavigation: [
      "Overview",
      "People",
      "Companies",
      "Visits",
      "Audit trail"
    ]
  }
];

async function assertForbiddenOperation(
  role: SeededRole,
  path: string,
  request: Parameters<typeof loginApiAsSeededRole>[0]
): Promise<void> {
  await loginApiAsSeededRole(request, role);

  const response =
    path === "/api/gate/evaluations"
      ? await request.post(apiUrl(path), {
          data: {
            presentation_reference: "batch8-forbidden-operation",
            site_id: "00000000-0000-0000-0000-000000000001",
            token_reference: "opaque-forbidden-reference"
          }
        })
      : await request.get(apiUrl(path));

  expect(
    response.status(),
    `${role} must be rejected by the authoritative API permission check.`
  ).toBe(403);
}

test.describe("role-aware navigation and API authorization", () => {
  for (const expectation of roleExpectations) {
    test(`${expectation.role} sees only its authorized workspace navigation`, async ({
      page
    }) => {
      await loginAsSeededRole(page, expectation.role);

      const navigation = page.getByRole("navigation", {
        name: "Primary navigation"
      });
      await expect(navigation).toBeVisible();

      for (const label of expectation.visibleNavigation) {
        await expect(navigation.getByRole("link", { name: label })).toBeVisible();
      }

      for (const restrictedLabel of [
        "Invitations",
        "People",
        "Companies",
        "Visits",
        "Gate kiosk",
        "Audit trail",
        "Settings"
      ].filter((label) => !expectation.visibleNavigation.includes(label))) {
        await expect(
          navigation.getByRole("link", { name: restrictedLabel })
        ).toHaveCount(0);
      }
    });

    if (expectation.forbiddenPath) {
      test(`${expectation.role} cannot bypass the API with a direct forbidden request`, async ({
        request
      }) => {
        await assertForbiddenOperation(
          expectation.role,
          expectation.forbiddenPath as string,
          request
        );
      });
    }
  }

  test("administrator retains a permitted authoritative API operation", async ({
    request
  }) => {
    await loginApiAsSeededRole(request, "administrator");

    const response = await request.get(apiUrl("/api/sites"));
    await expectSuccessful(response, "Administrator site read");
  });
});

test.describe.configure({ mode: "serial" });

test.describe("deterministic reset and reseed smoke coverage", () => {
  test("restores the full demo baseline twice through the private isolated runner", async ({
    request
  }) => {
    test.skip(
      !hasBaselineRunner(),
      "The private E2E baseline runner must execute the reset-and-seed lifecycle."
    );

    await restoreSeedBaseline(request);
    await restoreSeedBaseline(request);

    await loginApiAsSeededRole(request, "administrator");
    const peopleResponse = await request.get(apiUrl("/api/people"));
    await expectSuccessful(peopleResponse, "Reading people after repeated baseline restore");

    const people = (await peopleResponse.json()) as Array<{
      first_name: string;
      last_name: string;
    }>;
    for (const [firstName, lastName] of [
      ["Alex", "van Dijk"],
      ["Sofia", "Janssen"],
      ["Milan", "de Boer"],
      ["Noah", "Peters"],
      ["Emma", "Visser"],
      ["Lucas", "Smit"]
    ]) {
      expect(
        people.some(
          (person) =>
            person.first_name === firstName && person.last_name === lastName
        )
      ).toBe(true);
    }
  });
});
