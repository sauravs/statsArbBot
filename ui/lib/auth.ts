/**
 * Session JWT helpers (shared by the login route, middleware, proxy, and the
 * check endpoint). The session is a signed JWT stored in an httpOnly cookie —
 * the browser never sees the passcode after login, and the token is verified on
 * every protected request. `jose` runs in both the Edge middleware and Node
 * route handlers.
 */
import { SignJWT, jwtVerify } from "jose";

const SECRET = new TextEncoder().encode(
  process.env.DASHBOARD_JWT_SECRET ?? "dev-insecure-secret-change-me",
);

export const SESSION_COOKIE = "dashboard_token";
export const SESSION_MAX_AGE = 60 * 60 * 24 * 7; // 7 days, in seconds

/** Mint a signed session token for the operator. */
export async function signSession(): Promise<string> {
  return await new SignJWT({ sub: "operator" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("7d")
    .sign(SECRET);
}

/** Return true iff the token is a valid, unexpired session JWT. */
export async function verifySession(token?: string | null): Promise<boolean> {
  if (!token) return false;
  try {
    await jwtVerify(token, SECRET);
    return true;
  } catch {
    return false;
  }
}
