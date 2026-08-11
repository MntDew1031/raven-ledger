import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const LEGACY_SESSION_COOKIE = "raven_session";
const HARDENED_SESSION_COOKIE = "__Host-raven_session";
// A production-built frontend can legitimately sit in front of a disposable
// development backend. NODE_ENV describes how Next was built, not how the API
// issues cookies. Only these two known names are accepted; an arbitrary env
// value must not become a cookie lookup or deletion target.
const SESSION_COOKIE =
  process.env.SESSION_COOKIE_NAME === LEGACY_SESSION_COOKIE
    ? LEGACY_SESSION_COOKIE
    : process.env.SESSION_COOKIE_NAME === HARDENED_SESSION_COOKIE
      ? HARDENED_SESSION_COOKIE
      : process.env.NODE_ENV === "production"
        ? HARDENED_SESSION_COOKIE
        : LEGACY_SESSION_COOKIE;
const API_INTERNAL_URL =
  process.env.API_INTERNAL_URL ?? "http://backend:8000";

/** Reachable without a session. */
const ANONYMOUS_PATHS = new Set(["/login", "/register"]);
/** Reachable with or without a session; the page handles both states. */
const INVITE_PATH = "/join";
const INVITE_PREFIX = "/join/";

function isAnonymousPath(pathname: string) {
  return (
    ANONYMOUS_PATHS.has(pathname) ||
    pathname === INVITE_PATH ||
    pathname.startsWith(INVITE_PREFIX)
  );
}

function loginRedirect(request: NextRequest, clearSession = false) {
  const loginUrl = new URL("/login", request.url);
  const returnTo = `${request.nextUrl.pathname}${request.nextUrl.search}`;

  if (returnTo !== "/") {
    loginUrl.searchParams.set("next", returnTo);
  }

  const response = NextResponse.redirect(loginUrl);
  if (clearSession) {
    response.cookies.delete(SESSION_COOKIE);
  }
  if (SESSION_COOKIE !== LEGACY_SESSION_COOKIE) {
    response.cookies.delete(LEGACY_SESSION_COOKIE);
  }
  return response;
}

async function sessionIsValid(request: NextRequest) {
  const cookieHeader = request.headers.get("cookie");
  if (!cookieHeader) {
    return false;
  }

  const response = await fetch(`${API_INTERNAL_URL}/api/v1/auth/me`, {
    cache: "no-store",
    headers: { cookie: cookieHeader },
    signal: AbortSignal.timeout(3_000),
  });

  return response.ok;
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const anonymousPath = isAnonymousPath(pathname);
  const isInvitePage =
    pathname === INVITE_PATH || pathname.startsWith(INVITE_PREFIX);
  const session = request.cookies.get(SESSION_COOKIE)?.value;

  if (!session) {
    return anonymousPath ? NextResponse.next() : loginRedirect(request);
  }

  try {
    const validSession = await sessionIsValid(request);

    if (!validSession) {
      return anonymousPath
        ? NextResponse.next()
        : loginRedirect(request, true);
    }

    // A signed-in visitor still needs to read an invitation, so that it can
    // explain which account the invitation belongs to.
    if (anonymousPath && !isInvitePage) {
      return NextResponse.redirect(new URL("/", request.url));
    }

    return NextResponse.next();
  } catch {
    return new NextResponse("Raven Ledger is temporarily unavailable.", {
      headers: { "Content-Type": "text/plain; charset=utf-8" },
      status: 503,
    });
  }
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
