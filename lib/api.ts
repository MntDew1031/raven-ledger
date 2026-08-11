const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * FastAPI returns a plain string for deliberate errors and a list of field
 * problems for schema validation, so both shapes become one readable message.
 */
function detailMessage(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.length > 0) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? String((item as { msg: unknown }).msg)
          : "",
      )
      .filter(Boolean);
    if (messages.length > 0) return messages.join(". ");
  }
  return `Request failed with ${status}`;
}

/**
 * Errors produced between the browser and the API — Cloudflare, the tunnel,
 * the Next.js proxy — rather than by the API itself.
 */
function gatewayMessage(status: number): string {
  if (status === 502 || status === 504) {
    return (
      "The request timed out before the server answered. If this was an AI " +
      "request, the model is probably still loading — wait a moment and try " +
      "again."
    );
  }
  if (status === 503) {
    return "The service is temporarily unavailable. Try again shortly.";
  }
  return `The request failed upstream (HTTP ${status}).`;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_URL}${path}`, {
    credentials: "include",
    ...init,
    headers,
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const body = (await response.json()) as { detail?: unknown };
      throw new ApiError(
        detailMessage(body.detail, response.status),
        response.status,
      );
    }
    // A non-JSON body here is an infrastructure error page, not our API:
    // a proxy timeout, a gateway 502, an auth wall. Dumping the whole HTML
    // document into the UI is useless and alarming, so summarise by status.
    const body = await response.text();
    const looksLikeHtml = /^\s*<(!doctype|html)/i.test(body);
    if (looksLikeHtml || body.length > 400) {
      throw new ApiError(gatewayMessage(response.status), response.status);
    }
    throw new ApiError(
      body.trim() || `Request failed with ${response.status}`,
      response.status,
    );
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
