import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const API_KEY = process.env.DASHBOARD_PASSWORD ?? "";

async function handler(
  req: NextRequest,
  { params }: { params: { path: string[] } },
) {
  // Verify the session JWT before forwarding anything upstream.
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!(await verifySession(token))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const path = params.path.join("/");
  const search = req.nextUrl.search;
  const url = `${API_URL}/${path}${search}`;
  const method = req.method;
  const body =
    method !== "GET" && method !== "HEAD" ? await req.text() : undefined;

  try {
    const upstream = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        // The backend trusts only the proxy via this shared key.
        "X-API-Key": API_KEY,
      },
      body,
    });

    const data = await upstream.json().catch(() => ({}));
    return NextResponse.json(data, { status: upstream.status });
  } catch {
    return NextResponse.json(
      { error: "Cannot reach API server. Is FastAPI running?" },
      { status: 503 },
    );
  }
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const DELETE = handler;
