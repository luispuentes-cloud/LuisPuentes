// Diagnose whether Node can reach Cursor's API over TLS.
//
// The cursor-sdk bridge is a Node process. Node uses its own bundled CA list
// and ignores the Windows certificate store, so corporate TLS inspection makes
// Node fail where PowerShell succeeds. A 401 here is SUCCESS: it means the
// connection and TLS handshake completed.
//
//   node tools\node_tls_check.js

const targets = [
  "https://api.cursor.com/v1/me",
  "https://api2.cursor.sh/",
  "https://cursor.com/",
];

function describe(err) {
  const parts = [];
  let e = err;
  let depth = 0;
  while (e && depth < 5) {
    if (e.message) parts.push(e.message);
    if (e.code) parts.push(`code=${e.code}`);
    e = e.cause;
    depth += 1;
  }
  return parts.join(" | ");
}

const TLS_CODES = [
  "UNABLE_TO_VERIFY_LEAF_SIGNATURE",
  "SELF_SIGNED_CERT_IN_CHAIN",
  "DEPTH_ZERO_SELF_SIGNED_CERT",
  "CERT_UNTRUSTED",
  "ERR_TLS_CERT_ALTNAME_INVALID",
  "CERT_HAS_EXPIRED",
  "UNABLE_TO_GET_ISSUER_CERT_LOCALLY",
];

async function main() {
  console.log(`node ${process.version}`);
  console.log(`NODE_EXTRA_CA_CERTS=${process.env.NODE_EXTRA_CA_CERTS || "(unset)"}`);
  console.log("");

  let tlsFailures = 0;

  for (const url of targets) {
    try {
      const res = await fetch(url, {
        method: "GET",
        headers: { Authorization: "Bearer diagnostic-not-a-real-key" },
        signal: AbortSignal.timeout(20000),
      });
      console.log(`ok   ${url} -> HTTP ${res.status} (connection + TLS fine)`);
    } catch (err) {
      const detail = describe(err);
      const isTls = TLS_CODES.some((c) => detail.includes(c));
      if (isTls) tlsFailures += 1;
      console.log(`FAIL ${url} -> ${detail}`);
    }
  }

  console.log("");
  if (tlsFailures > 0) {
    console.log("VERDICT: TLS interception. Node does not trust the intercepting root CA.");
    console.log("Fix: export the corporate root CA to a .pem and set NODE_EXTRA_CA_CERTS");
    console.log("     to that file before launching the orchestrator console.");
  } else {
    console.log("VERDICT: no TLS-trust failure detected against these hosts.");
    console.log("If the bridge still fails, the blocked host may differ from the ones above.");
  }
}

main();
