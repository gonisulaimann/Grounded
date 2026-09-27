// Postinstall: fetch the platform binary for this package version from
// the GitHub release of the same version. Version coupling is the whole
// contract: npm/grounded@X.Y.Z always runs release vX.Y.Z. Bump the two
// together (see "Releasing" below).
"use strict";
const fs = require("fs");
const https = require("https");
const path = require("path");

const { assetName } = require("./bin/grounded");

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { "User-Agent": "grounded-npm-install" } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        download(res.headers.location, dest).then(resolve, reject);
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error(`HTTP ${res.statusCode} for ${url}`));
        return;
      }
      const out = fs.createWriteStream(dest, { mode: 0o755 });
      res.pipe(out);
      out.on("finish", () => resolve());
      out.on("error", reject);
    });
    req.on("error", reject);
    req.setTimeout(120000, () => req.destroy(new Error("download timed out")));
  });
}

async function main() {
  const asset = assetName();
  if (!asset) {
    console.error("grounded: unsupported platform, skipping binary download.");
    return; // bin/grounded reports the actionable error at runtime
  }
  const version = require("./package.json").version;
  const url = `https://github.com/gonisulaimann/Grounded/releases/download/v${version}/${asset}`;
  const dest = path.join(__dirname, "bin", asset);
  fs.mkdirSync(path.join(__dirname, "bin"), { recursive: true });
  try {
    await download(url, dest);
    if (process.platform !== "win32") fs.chmodSync(dest, 0o755);
    console.log(`grounded: downloaded ${asset} (v${version})`);
  } catch (err) {
    console.error(`grounded: binary download failed: ${err.message}`);
    console.error("grounded: install will proceed; `grounded` will report this at runtime.");
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`grounded: binary download failed: ${err.message}`);
  });
}

module.exports = { assetName };
