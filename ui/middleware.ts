import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

// Only page routes pass through this middleware (the matcher below excludes
// all /api/*), so /login is the sole public path. API routes do their own auth.
const PUBLIC_PATHS = ["/login"];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const valid = await verifySession(token);

  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));

  // Unauthenticated user hitting a protected route → send to /login.
  if (!valid && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  // Already-authenticated user hitting /login → send to /dashboard.
  if (valid && pathname.startsWith("/login")) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // Guard all app routes except Next internals, static files, and /api/*
  // (API routes do their own auth: /api/auth is public, /api/proxy verifies).
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/).*)"],
};
