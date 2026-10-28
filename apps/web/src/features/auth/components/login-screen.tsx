"use client";

import {
  ArrowRightIcon,
  EyeIcon,
  EyeOffIcon,
  GitCompareArrowsIcon,
  PackageCheckIcon,
  ShieldCheckIcon,
  UserRoundCheckIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ForgeLogo, ForgeMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FieldError, Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import { safeNext } from "@/lib/auth-redirect";

import { useLogin } from "../api";

const PITCH = [
  {
    icon: ShieldCheckIcon,
    title: "Linted before it is built",
    body: "Every upload gets a report of what can and cannot be expressed exactly, with the JSON pointer of each finding.",
  },
  {
    icon: GitCompareArrowsIcon,
    title: "Versions, compared",
    body: "Each spec version is compared with the last: operations added, removed and changed, and which parts changed.",
  },
  {
    icon: PackageCheckIcon,
    title: "Deterministic archives",
    body: "The same spec and options always produce the same zip, with tests that check the API matches its spec.",
  },
  {
    icon: UserRoundCheckIcon,
    title: "Your code stays yours",
    body: "Handlers, auth and config are created once and never overwritten. Only app/generated/ is rewritten.",
  },
];

export function LoginScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const login = useLogin();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const expired = params.get("reason") === "expired";

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setError(null);
    login.mutate(
      { email: email.trim(), password },
      {
        onSuccess: (session) => {
          toast.success(`Welcome back, ${session.user.name.split(" ")[0]}.`);
          router.replace(safeNext(params.get("next")));
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  return (
    <div className="grid min-h-dvh bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <div className="relative flex flex-col px-6 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <ForgeLogo />
          <ThemeToggle />
        </div>
        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[360px]">
            <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.025em]">Sign in to APIForge</h1>
            <p className="mt-1.5 text-[13.5px] text-muted-foreground">
              Turn an OpenAPI spec into a FastAPI project you can run and keep.
            </p>
            {expired && (
              <div role="status" className="mt-5 rounded-lg bg-warning-soft px-3.5 py-2.5 text-[13px] text-warning">
                Your session expired. Sign in again to pick up where you left off.
              </div>
            )}
            <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  placeholder="you@company.com"
                  className="h-10"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={!!error || undefined}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={show ? "text" : "password"}
                    autoComplete="current-password"
                    className="h-10 pr-10"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    aria-invalid={!!error || undefined}
                  />
                  <button
                    type="button"
                    onClick={() => setShow((s) => !s)}
                    aria-label={show ? "Hide password" : "Show password"}
                    className="absolute top-1/2 right-2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-subtle hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                  >
                    {show ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
                  </button>
                </div>
              </div>
              {error && <FieldError>{error}</FieldError>}
              <Button type="submit" size="lg" className="w-full" disabled={login.isPending}>
                {login.isPending ? "Signing in..." : "Sign in"}
                {!login.isPending && <ArrowRightIcon />}
              </Button>
            </form>
            <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
              Accounts are created by an owner under Users. Forgot your password? Ask an owner to reset it, or run{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">apiforge-server create-owner</code> on the server.
            </p>
          </div>
        </div>
        <p className="text-[11.5px] text-faint">Self-hosted. Your specs and generated code never leave your infrastructure.</p>
      </div>

      <aside className="relative hidden overflow-hidden bg-[var(--panel)] p-10 text-white lg:flex lg:flex-col lg:justify-between">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-90"
          style={{
            background:
              "radial-gradient(60% 50% at 80% 10%, var(--panel-glow), transparent 70%), radial-gradient(50% 45% at 10% 90%, var(--panel-glow-2), transparent 70%)",
          }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage: "linear-gradient(white 1px, transparent 1px), linear-gradient(90deg, white 1px, transparent 1px)",
            backgroundSize: "36px 36px",
          }}
        />
        <div className="relative flex items-center gap-2 text-[13px] font-medium text-white/70">
          <ForgeMark className="size-6" />
          Open-source API generator
        </div>

        <div className="relative max-w-lg">
          <h2 className="text-[34px] leading-[1.12] font-semibold tracking-[-0.03em]">
            A spec goes in.
            <br />
            <span className="text-[var(--panel-accent)]">A FastAPI project comes out.</span>
          </h2>
          <p className="mt-3 text-[14.5px] leading-relaxed text-white/65">
            Upload an OpenAPI 3.0 or 3.1 spec. APIForge lints it, compares it with the last version, and generates routers,
            models, tests and the handler stubs you fill in, as a project you run and keep.
          </p>

          <div className="mt-8 overflow-hidden rounded-2xl bg-white/[0.06] shadow-[0_20px_60px_rgba(0,0,0,0.35)] ring-1 ring-white/10 backdrop-blur">
            <div className="flex items-center justify-between px-4 pt-3 text-[12px] text-white/55">
              <span>pet-store, generation #2</span>
              <span className="rounded-full bg-[var(--panel-accent-soft)] px-2 py-0.5 font-semibold text-[var(--panel-accent)]">Succeeded</span>
            </div>
            <ul className="mt-2 space-y-1 px-4 pb-3 font-mono text-[12px] text-white/80">
              {[
                ["app/generated/routers/pets.py", "generated"],
                ["app/generated/models.py", "generated"],
                ["app/handlers/pets.py", "yours"],
                ["app/auth.py", "yours"],
                ["tests/generated/test_pets.py", "generated"],
              ].map(([path, owner]) => (
                <li key={path} className="flex items-center justify-between gap-3">
                  <span className="truncate">{path}</span>
                  <span className={owner === "yours" ? "text-[var(--panel-accent)]" : "text-white/45"}>{owner}</span>
                </li>
              ))}
            </ul>
          </div>

          <ul className="mt-8 grid gap-5 sm:grid-cols-2">
            {PITCH.map((p) => (
              <li key={p.title} className="flex gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[var(--panel-accent)]">
                  <p.icon className="size-4" />
                </span>
                <div>
                  <div className="text-[13px] font-semibold">{p.title}</div>
                  <div className="mt-0.5 text-[12.5px] leading-relaxed text-white/55">{p.body}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="relative text-[11.5px] text-white/40">MIT licensed. Part of the Euron open-source initiative.</div>
      </aside>
    </div>
  );
}
