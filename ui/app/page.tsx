import { redirect } from "next/navigation";

// Root → dashboard. Middleware bounces unauthenticated users to /login.
export default function Home() {
  redirect("/dashboard");
}
