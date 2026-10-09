import {
  expect,
  type APIRequestContext,
  type APIResponse
} from "@playwright/test";
import {
  SEEDED_ROLE_HANDLES,
  type SeededRole
} from "./auth";

type Person = {
  id: string;
  first_name: string;
  last_name: string;
};

type Site = {
  id: string;
  is_active: boolean;
  name: string;
};

type Visit = {
  id: string;
  person_id: string;
  status: string;
};

function apiBaseUrl(): string {
  return process.env.API_BASE_URL ?? "http://api:8000";
}

function configuredDemoPassword(): string {
  const password = process.env.E2E_DEMO_PASSWORD;

  if (!password) {
    throw new Error(
      "E2E_DEMO_PASSWORD is required for authenticated e2e API requests."
    );
  }

  return password;
}

// PUBLIC_INTERFACE
/**
 * Sign a Playwright API context in as a seeded role through the public demo API.
 *
 * @param request - Isolated Playwright API context that retains the session cookie.
 * @param role - Seeded role that owns the desired public API permissions.
 */
export async function loginApiAsSeededRole(
  request: APIRequestContext,
  role: SeededRole = "administrator"
): Promise<void> {
  const response = await request.post(`${apiBaseUrl()}/auth/login`, {
    data: {
      handle: SEEDED_ROLE_HANDLES[role],
      password: configuredDemoPassword()
    }
  });

  expect(response.status(), "Seeded API login must succeed.").toBe(200);
}

/**
 * Require a successful API response without including its potentially sensitive
 * body in a Playwright assertion message.
 */
export async function expectSuccessful(
  response: APIResponse,
  operation: string
): Promise<void> {
  expect(response.ok(), `${operation} must return a success status.`).toBe(true);
}

/**
 * Find a deterministic person record by its fictional display name.
 */
export async function findSeededPerson(
  request: APIRequestContext,
  firstName: string,
  lastName: string
): Promise<Person> {
  const response = await request.get(`${apiBaseUrl()}/api/people`);
  await expectSuccessful(response, "Listing seeded people");

  const people = (await response.json()) as Person[];
  const person = people.find(
    (candidate) =>
      candidate.first_name === firstName && candidate.last_name === lastName
  );

  expect(person, `The seeded ${firstName} ${lastName} record must exist.`).toBeTruthy();
  return person as Person;
}

/**
 * Resolve an active deterministic visit for a person.
 */
export async function findActiveVisit(
  request: APIRequestContext,
  personId: string
): Promise<Visit> {
  const response = await request.get(`${apiBaseUrl()}/api/visits`);
  await expectSuccessful(response, "Listing seeded visits");

  const visits = (await response.json()) as Visit[];
  const visit = visits.find(
    (candidate) =>
      candidate.person_id === personId && candidate.status.toLowerCase() === "active"
  );

  expect(visit, "The seeded person must have an active visit.").toBeTruthy();
  return visit as Visit;
}

/**
 * Resolve the active Vlaardingen-compatible deterministic site.
 */
export async function findActiveSite(
  request: APIRequestContext
): Promise<Site> {
  const response = await request.get(`${apiBaseUrl()}/api/sites`);
  await expectSuccessful(response, "Listing seeded sites");

  const sites = (await response.json()) as Site[];
  const site = sites.find((candidate) => candidate.is_active);

  expect(site, "The deterministic seed must include an active site.").toBeTruthy();
  return site as Site;
}

/**
 * Build a seeded opaque token reference only for submission to the gate API.
 *
 * The reference is never asserted, emitted in a test message, or attached to
 * a diagnostic artifact.
 */
export function seededOpaqueReference(personKey: string): string {
  return `renewi-access:demo:${personKey}:opaque-reference`;
}

/**
 * Return the Compose-internal API URL for direct public API test requests.
 */
export function apiUrl(path: string): string {
  return `${apiBaseUrl()}${path}`;
}
