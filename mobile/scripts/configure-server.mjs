// 在建置 APK / Xcode 專案前，把伺服器網址寫進 capacitor.config.json 與 www/server-config.js。
//
//   ANLA_SERVER_URL=https://anla.example.tw node scripts/configure-server.mjs
//   node scripts/configure-server.mjs https://anla.example.tw
//
// 規則：
//   * 正式使用必須是 HTTPS。
//   * http:// 只允許區網／本機位址（10.x、172.16-31.x、192.168.x、127.x、localhost、*.local），
//     且會開啟 Android cleartext；iOS 另需在 Info.plist 設定 ATS 例外（見 docs/PLATFORMS.md）。
//   * 未提供網址時移除 server.url：App 只會顯示 www/index.html 的「尚未設定伺服器」說明頁。
//   * 加上 --require 時，未提供網址視為錯誤（正式發佈用）。
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const configPath = join(root, "capacitor.config.json");
const serverJsPath = join(root, "www", "server-config.js");

const args = process.argv.slice(2);
const requireUrl = args.includes("--require");
const raw = (args.find((a) => !a.startsWith("--")) || process.env.ANLA_SERVER_URL || "").trim();

function isLanHost(host) {
  if (host === "localhost" || host.endsWith(".local")) return true;
  const m = host.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

const config = JSON.parse(readFileSync(configPath, "utf8"));
config.server = config.server || {};
let serverUrl = "";

if (!raw) {
  if (requireUrl) {
    console.error("錯誤：未設定 ANLA_SERVER_URL。");
    process.exit(1);
  }
  delete config.server.url;
  config.server.cleartext = false;
  console.warn("警告：未設定 ANLA_SERVER_URL，App 將只顯示「尚未設定伺服器」說明頁。");
} else {
  let url;
  try {
    url = new URL(raw);
  } catch {
    console.error(`錯誤：伺服器網址格式不正確：${raw}`);
    process.exit(1);
  }
  if (url.protocol === "https:") {
    config.server.cleartext = false;
  } else if (url.protocol === "http:" && isLanHost(url.hostname)) {
    config.server.cleartext = true;
    console.warn(`注意：${url.origin} 是區網 HTTP，只適合開發／現場展示，請勿用於正式發佈。`);
  } else {
    console.error(`錯誤：${url.origin} 不是 HTTPS，也不是區網位址；正式部署請使用 HTTPS。`);
    process.exit(1);
  }
  serverUrl = url.origin + url.pathname.replace(/\/+$/, "");
  config.server.url = serverUrl;
}

writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n");
writeFileSync(
  serverJsPath,
  "// 由 scripts/configure-server.mjs 產生；未設定時為空字串。\n" +
    `window.ANLA_SERVER_URL = ${JSON.stringify(serverUrl)};\n`
);
console.log(`capacitor.config.json server.url = ${serverUrl || "(未設定)"}, cleartext = ${config.server.cleartext}`);
