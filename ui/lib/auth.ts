/**
 * Session JWT helpers (shared by the login route, middleware, proxy, and the
 * check endpoint). The session is a signed JWT stored in an httpOnly cookie —
 * the browser never sees the passcode after login, and the token is verified on
 * every protected request. `jose` runs in both the Edge middleware and Node
 * route handlers.
 */
import { SignJWT, jwtVerify } from "jose";

export const SESSION_COOKIE = "dashboard_token";
export const SESSION_MAX_AGE = 60 * 60 * 24 * 7; // 7 days, in seconds

/**
 * Resolve the signing secret. Lazy (not module-level) on purpose: evaluating
 * this at import time would throw during `next build` (which runs with
 * NODE_ENV=production but no secret injected). In production a missing secret
 * is a hard error — the insecure dev fallback is committed to the repo, so
 * allowing it in prod would let anyone forge a session cookie.
 */
function getSecret(): Uint8Array {
  const raw = process.env.DASHBOARD_JWT_SECRET;
  if (raw) return new TextEncoder().encode(raw);
  if (process.env.NODE_ENV === "production") {
    throw new Error("DASHBOARD_JWT_SECRET must be set in production");
  }
  return new TextEncoder().encode("dev-insecure-secret-change-me");
}

/** Mint a signed session token for the operator. */
export async function signSession(): Promise<string> {
  return await new SignJWT({ sub: "operator" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("7d")
    .sign(getSecret());
}

/** Return true iff the token is a valid, unexpired session JWT. */
export async function verifySession(token?: string | null): Promise<boolean> {
  if (!token) return false;
  const secret = getSecret(); // throws in prod if misconfigured — fail loud, not open
  try {
    await jwtVerify(token, secret);
    return true;
  } catch {
    return false;
  }
}
