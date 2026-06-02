import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

/**
 * Lightweight session check — verifies the JWT cookie on the Next.js server
 * without touching FastAPI. Used by the UI to decide whether action controls
 * should be enabled.
 */
export async function GET() {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const authenticated = await verifySession(token);
  return NextResponse.json(
    { authenticated },
    { status: authenticated ? 200 : 401 },
  );
}
