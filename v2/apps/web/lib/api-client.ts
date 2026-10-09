// An empty base URL intentionally uses the web origin and its narrowly scoped
// Next.js proxy, keeping browser session cookies first-party in Compose.
const DEFAULT_API_BASE_URL = "";

export type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

// PUBLIC_INTERFACE
/**
 * Represents a typed HTTP failure returned by the application API.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

// PUBLIC_INTERFACE
/**
 * Returns the configured public API origin, falling back to the same-origin
 * proxy used by local and isolated Compose deployments.
 */
export function getApiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(/\/$/, "");
}

async function readResponseBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return undefined;
  }

  const contentType = response.headers.get("content-type") ?? "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

function apiErrorFromPayload(response: Response, payload: unknown): ApiError {
  let message = `The request failed with status ${response.status}.`;
  if (typeof payload === "object" && payload !== null) {
    if ("detail" in payload && typeof payload.detail === "string") {
      message = payload.detail;
    } else if ("message" in payload && typeof payload.message === "string") {
      message = payload.message;
    }
  }
  return new ApiError(message, response.status, payload);
}

// PUBLIC_INTERFACE
/**
 * Sends an authenticated API request and returns its JSON-compatible response.
 *
 * @param path API path beginning with a slash.
 * @param options Standard fetch options with an optional serializable body.
 * @returns The decoded response payload.
 * @throws ApiError when the API returns a non-success response or cannot be reached.
 */
export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  if (!path.startsWith("/")) {
    throw new Error("API request paths must begin with '/'.");
  }

  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...options,
      body,
      credentials: "include",
      headers
    });
    const payload = await readResponseBody(response);

    if (!response.ok) {
      throw apiErrorFromPayload(response, payload);
    }

    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }

    throw new ApiError(
      "The local API is unavailable. The web shell remains available while it restarts.",
      0,
      error
    );
  }
}

// PUBLIC_INTERFACE
/**
 * Sends authenticated multipart form data while allowing the browser to set its boundary.
 */
export async function apiFormRequest<T>(
  path: string,
  formData: FormData,
  options: Omit<RequestInit, "body"> = {}
): Promise<T> {
  if (!path.startsWith("/")) {
    throw new Error("API request paths must begin with '/'.");
  }

  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...options,
      body: formData,
      credentials: "include",
      headers
    });
    const payload = await readResponseBody(response);
    if (!response.ok) {
      throw apiErrorFromPayload(response, payload);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError("The private upload could not reach the local API.", 0, error);
  }
}

// PUBLIC_INTERFACE
/**
 * Retrieves an authenticated private response as a browser Blob.
 */
export async function apiBlobRequest(path: string): Promise<Blob> {
  if (!path.startsWith("/")) {
    throw new Error("API request paths must begin with '/'.");
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      credentials: "include",
      headers: { Accept: "*/*" }
    });
    if (!response.ok) {
      const payload = await readResponseBody(response);
      throw apiErrorFromPayload(response, payload);
    }
    return response.blob();
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError("The private document could not reach the local API.", 0, error);
  }
}

// PUBLIC_INTERFACE
/**
 * Retrieves private Gate upload bytes with the scanned credential in a POST
 * body, not in a URL or an embedded document frame.
 */
export async function apiPrivateBlobPost(
  path: string,
  body: { token_reference: string; site_id: string }
): Promise<Blob> {
  if (!path.startsWith("/")) {
    throw new Error("API request paths must begin with '/'.");
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "*/*" },
      body: JSON.stringify(body)
    });
    if (!response.ok) {
      throw apiErrorFromPayload(response, await readResponseBody(response));
    }
    return response.blob();
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError("The private Gate preview could not reach the local API.", 0, error);
  }
}
