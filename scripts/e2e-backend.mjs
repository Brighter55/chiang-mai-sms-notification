// Boot Django for the Playwright run.
//
// Playwright's `webServer` runs this, so it must stay in the foreground and let
// itself be killed. Written in Node (not Python) because Playwright already
// requires Node, and because it resolves the backend venv interpreter itself —
// the venv never has to be activated for the E2E run to work.
//
// Safety, in layers:
//   1. The Playwright spec intercepts /api/orders/sync/ and .../send/ at the
//      network layer, so those routes never reach Django at all.
//   2. Twilio and Clover credentials are blanked here regardless. If an
//      interception ever fails to register, the request still cannot leave the
//      building as a real text message or a real Clover call.
//   3. A throwaway sqlite database, deleted on every start, so a run can never
//      touch development or production data.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backend = path.join(root, "backend");

const PORT = 8001; // not 8000 — a dev server may already be using that
const PREVIEW_ORIGINS = "http://127.0.0.1:4173,http://localhost:4173";

const candidates = [
  path.join(backend, "venv", "Scripts", "python.exe"), // Windows
  path.join(backend, "venv", "bin", "python"), // POSIX
];
const python = candidates.find(existsSync) ?? "python";

for (const db of ["e2e.sqlite3", "e2e_landing.sqlite3"]) {
  rmSync(path.join(backend, db), { force: true });
}

const env = {
  ...process.env,
  DATABASE_URL: "sqlite:///e2e.sqlite3",
  LANDING_DATABASE_URL: "sqlite:///e2e_landing.sqlite3",
  DEBUG: "True",
  SECRET_KEY: "e2e-only-not-a-real-secret",
  ALLOWED_HOSTS: "127.0.0.1,localhost",
  CORS_ALLOWED_ORIGINS: PREVIEW_ORIGINS,
  CSRF_TRUSTED_ORIGINS: PREVIEW_ORIGINS,
  // Layer 2: blanked, so no real message can be sent and no real Clover call made.
  TWILIO_ACCOUNT_SID: "",
  TWILIO_AUTH_TOKEN: "",
  TWILIO_PHONE_NUMBER: "",
  CLOVER_API_TOKEN: "",
  CLOVER_MERCHANT_ID: "",
  MERCHANT_NAME: "Chiang Mai",
};

function step(args) {
  const result = spawnSync(python, args, { cwd: backend, env, stdio: "inherit" });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

step(["manage.py", "migrate", "--noinput"]);
step(["manage.py", "migrate", "--database=landing", "--noinput"]);

// E2E_SEED_JSON points seed_e2e at a scenario file instead of the default
// fixture — how a bug that depends on specific data gets reproduced. See the
// /reproduce-bug skill.
//
// Resolved against the repo root rather than the backend cwd, so the path means
// the same thing wherever the suite is invoked from.
const seed = ["manage.py", "seed_e2e"];
if (process.env.E2E_SEED_JSON) {
  seed.push("--json-file", path.resolve(root, process.env.E2E_SEED_JSON));
}
step(seed);

// --noreload: the autoreloader forks a child that Playwright cannot kill
// cleanly, which leaves the port held after a run.
spawn(python, ["manage.py", "runserver", `127.0.0.1:${PORT}`, "--noreload"], {
  cwd: backend,
  env,
  stdio: "inherit",
});
