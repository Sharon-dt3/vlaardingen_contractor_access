import { expect, test } from "@playwright/test";

const siteId = "00000000-0000-0000-0000-000000000001";
const firstVisitId = "00000000-0000-0000-0000-000000000011";
const secondVisitId = "00000000-0000-0000-0000-000000000022";
const timestamp = "2026-09-23T10:00:00Z";

const people = [
  {
    gate_event_id: "gate-one",
    presence_event_id: "entry-one",
    person_id: "person-one",
    person_name: "Candidate Alice",
    population: "visitor",
    visit_id: firstVisitId,
    site_id: siteId,
    site_name: "Vlaardingen",
    entered_at: timestamp,
    visit_ends_at: "2026-09-23T17:00:00Z",
    decision: "GRANT"
  },
  {
    gate_event_id: "gate-two",
    presence_event_id: "entry-two",
    person_id: "person-two",
    person_name: "Candidate Bob",
    population: "visitor",
    visit_id: secondVisitId,
    site_id: siteId,
    site_name: "Vlaardingen",
    entered_at: timestamp,
    visit_ends_at: "2026-09-23T17:00:00Z",
    decision: "GRANT"
  }
];

for (const accepted of [true, false]) {
  test(`${accepted ? "accepted" : "rejected"} exit updates only the appropriate roster row`, async ({ page }) => {
    let exitRequests = 0;
    let exited = false;
    const unexpectedRequests: string[] = [];

    await page.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const method = request.method();

      if (path !== "/auth/me" && !path.startsWith("/api/")) {
        await route.continue();
        return;
      }

      const respond = (body: unknown, status = 200) =>
        route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(body)
        });

      if (method === "GET" && path === "/auth/me") {
        await respond({
          id: "mock-manager",
          handle: "mock.manager",
          display_name: "Mock Manager",
          role: "site_manager",
          permissions: ["dashboard:read", "presence:read", "presence:write"]
        });
      } else if (method === "GET" && path === "/api/dashboard") {
        const count = exited ? 1 : 2;
        const totals = {
          site_count: 1,
          active_visit_count: 2,
          present_count: count,
          grant_count: 2,
          denial_count: 0,
          entry_count: 2,
          exit_count: exited ? 1 : 0
        };
        await respond({
          as_of: timestamp,
          activity_window_started_at: timestamp,
          activity_hours: 24,
          totals,
          sites: [{
            site_id: siteId,
            site_name: "Vlaardingen",
            country_code: "NL",
            ...totals
          }],
          current_presence: exited ? [people[1]] : people,
          recent_decisions: []
        });
      } else if (method === "GET" && path === "/api/presence") {
        await respond(exited ? [people[1]] : people);
      } else if (method === "POST" && path === "/api/presence/exits") {
        exitRequests += 1;
        const body = request.postDataJSON() as { visit_id: string };
        expect(body.visit_id).toBe(firstVisitId);
        if (accepted) {
          exited = true;
          await respond({
            id: "mock-exit",
            visit_id: firstVisitId,
            person_id: "person-one",
            site_id: siteId,
            gate_event_id: "gate-one",
            event_type: "exit",
            occurred_at: timestamp
          });
        } else {
          await respond({ detail: "Exit rejected by mocked API" }, 409);
        }
      } else {
        unexpectedRequests.push(`${method} ${path}`);
        await respond({ detail: "Unexpected API request blocked by browser test" }, 599);
      }
    });

    await page.goto("/");
    const roster = page.getByRole("region", { name: "On-site roster" });
    await expect(roster.getByRole("row", { name: /Candidate Alice/ })).toBeVisible();
    await expect(roster.getByRole("row", { name: /Candidate Bob/ })).toBeVisible();

    await roster.getByRole("row", { name: /Candidate Alice/ })
      .getByRole("button", { name: "Record exit" }).click();

    if (accepted) {
      await expect(roster.getByRole("row", { name: /Candidate Alice/ })).toHaveCount(0);
      await expect(roster.getByRole("status")).toContainText("The API recorded the exit");
    } else {
      await expect(roster.getByText("Exit rejected by mocked API")).toBeVisible();
      await expect(roster.getByRole("row", { name: /Candidate Alice/ })).toBeVisible();
    }

    await expect(roster.getByRole("row", { name: /Candidate Bob/ })).toBeVisible();
    expect(exitRequests).toBe(1);
    expect(unexpectedRequests).toEqual([]);
  });
}
