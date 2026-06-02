"use client";
import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";

const PASSCODE_LENGTH = 6;

export default function LoginPage() {
  const router = useRouter();
  const [digits, setDigits] = useState<string[]>(
    Array(PASSCODE_LENGTH).fill(""),
  );
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [shake, setShake] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  // Focus first cell on mount.
  useEffect(() => {
    inputRefs.current[0]?.focus();
  }, []);

  function handleChange(idx: number, value: string) {
    const digit = value.replace(/\D/g, "").slice(-1);
    const next = [...digits];
    next[idx] = digit;
    setDigits(next);
    setError("");

    if (digit && idx < PASSCODE_LENGTH - 1) {
      inputRefs.current[idx + 1]?.focus();
    }
    if (digit && next.every((d) => d !== "")) {
      submit(next.join(""));
    }
  }

  function handleKeyDown(idx: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace") {
      if (digits[idx]) {
        const next = [...digits];
        next[idx] = "";
        setDigits(next);
      } else if (idx > 0) {
        inputRefs.current[idx - 1]?.focus();
      }
    } else if (e.key === "ArrowLeft" && idx > 0) {
      inputRefs.current[idx - 1]?.focus();
    } else if (e.key === "ArrowRight" && idx < PASSCODE_LENGTH - 1) {
      inputRefs.current[idx + 1]?.focus();
    }
  }

  function handlePaste(e: React.ClipboardEvent) {
    e.preventDefault();
    const pasted = e.clipboardData
      .getData("text")
      .replace(/\D/g, "")
      .slice(0, PASSCODE_LENGTH);
    if (!pasted) return;
    const next = Array(PASSCODE_LENGTH).fill("");
    pasted.split("").forEach((d, i) => {
      next[i] = d;
    });
    setDigits(next);
    setError("");
    const focusIdx = Math.min(pasted.length, PASSCODE_LENGTH - 1);
    inputRefs.current[focusIdx]?.focus();
    if (pasted.length === PASSCODE_LENGTH) submit(pasted);
  }

  async function submit(code: string) {
    setLoading(true);
    setError("");

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: code }),
        signal: controller.signal,
      });

      if (res.ok) {
        router.push("/dashboard");
        router.refresh();
        return;
      }

      setError("Incorrect passcode — try again.");
      setShake(true);
      setDigits(Array(PASSCODE_LENGTH).fill(""));
      setTimeout(() => {
        setShake(false);
        inputRefs.current[0]?.focus();
      }, 500);
    } catch (err) {
      const isTimeout = err instanceof Error && err.name === "AbortError";
      setError(
        isTimeout
          ? "Request timed out — refresh the page and try again."
          : "Connection error — make sure the app is running.",
      );
      setDigits(Array(PASSCODE_LENGTH).fill(""));
      setTimeout(() => inputRefs.current[0]?.focus(), 100);
    } finally {
      clearTimeout(timeout);
      setLoading(false);
    }
  }

  function handleFormSubmit(e: React.FormEvent) {
    e.preventDefault();
    const code = digits.join("");
    if (code.length === PASSCODE_LENGTH) submit(code);
  }

  const filled = digits.filter(Boolean).length;

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-bg relative overflow-hidden">
      {/* Subtle grid background */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(to right,#fff 1px,transparent 1px),linear-gradient(to bottom,#fff 1px,transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />
      {/* Glow behind card */}
      <div className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[480px] h-[480px] rounded-full bg-blue/5 blur-3xl" />

      <div className="relative z-10 w-full max-w-sm px-4">
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-card border border-border mb-5 shadow-lg">
            <span className="text-3xl">📊</span>
          </div>
          <h1 className="text-2xl font-bold text-text tracking-tight">
            statsArbBot
          </h1>
          <p className="text-sm text-muted mt-1">
            Enter your passcode to continue
          </p>
        </div>

        <form
          onSubmit={handleFormSubmit}
          className="bg-card border border-border rounded-2xl p-8 shadow-xl space-y-6"
        >
          <div
            className={`flex justify-center gap-3 transition-all duration-150 ${
              shake ? "animate-shake" : ""
            }`}
            onPaste={handlePaste}
          >
            {digits.map((d, i) => (
              <input
                key={i}
                ref={(el) => {
                  inputRefs.current[i] = el;
                }}
                type="password"
                inputMode="numeric"
                aria-label={`Passcode digit ${i + 1}`}
                maxLength={1}
                value={d}
                onChange={(e) => handleChange(i, e.target.value)}
                onKeyDown={(e) => handleKeyDown(i, e)}
                disabled={loading}
                className={[
                  "w-11 h-14 text-center text-xl font-bold rounded-xl border-2 bg-bg text-text",
                  "focus:outline-none transition-all duration-150",
                  "disabled:opacity-40",
                  d
                    ? "border-blue text-text shadow-[0_0_0_3px_rgba(96,165,250,0.15)]"
                    : error
                      ? "border-red/60"
                      : "border-border focus:border-blue/60",
                ].join(" ")}
              />
            ))}
          </div>

          <div className="flex justify-center gap-1.5">
            {digits.map((_, i) => (
              <span
                key={i}
                className={`w-1.5 h-1.5 rounded-full transition-all duration-200 ${
                  i < filled ? "bg-blue" : "bg-border"
                }`}
              />
            ))}
          </div>

          {error && <p className="text-center text-sm text-red">{error}</p>}

          <button
            type="submit"
            disabled={filled < PASSCODE_LENGTH || loading}
            className={[
              "w-full py-3 rounded-xl font-semibold text-sm transition-all duration-150",
              filled === PASSCODE_LENGTH && !loading
                ? "bg-blue hover:bg-blue/85 text-white shadow-md"
                : "bg-white/5 text-muted cursor-not-allowed",
            ].join(" ")}
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                Verifying…
              </span>
            ) : (
              "Enter Dashboard"
            )}
          </button>
        </form>

        <p className="text-center text-xs text-muted/50 mt-6">
          Statistical Arbitrage Bot — Private Access
        </p>
      </div>
    </div>
  );
}
