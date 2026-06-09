// Keep ui/content/TRADING_CONCEPTS.md in sync with the repo-root source of truth
// (docs/TRADING_CONCEPTS.md) at build time.
//
// Why a copy at all: the UI's Docker build context is ./ui (see ui/Dockerfile +
// docker-compose), so repo-root docs/ is NOT present when the image is built.
// The committed copy under ui/content/ is what the Guide page reads. Locally and
// in CI the full repo is checked out, so this script refreshes that copy from the
// canonical docs/ file; in Docker the source is absent and we keep the committed
// copy as-is. Runs via the `prebuild` npm hook.
import { copyFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "../../docs/TRADING_CONCEPTS.md");
const dest = resolve(here, "../content/TRADING_CONCEPTS.md");

if (existsSync(source)) {
  copyFileSync(source, dest);
  console.log("[sync-guide] refreshed content/TRADING_CONCEPTS.md from docs/");
} else {
  // Docker build (context = ./ui): docs/ is out of context — use the committed copy.
  console.log("[sync-guide] docs/ source not found; using committed copy");
}
