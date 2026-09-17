"""Standalone Cursor SDK smoke test.

Matches the orchestrator's real path (`AsyncClient.launch_bridge` then
`create_agent` / `send` / `wait`). A bare `AsyncClient()` is invalid in
cursor-sdk 1.0.30 and is not what the orchestrator does.

    cd C:\\Users\\lpuentes001\\.cursor\\orchestrator
    $env:CURSOR_API_KEY = "<paste the real key, not this placeholder>"
    python tools\\sdk_smoke.py

Exits 0 only if a local agent was created and a run finished.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

_PLACEHOLDER_MARKERS = ("<", ">", "your key", "your_key", "paste")


def _preflight() -> str | None:
    raw = os.environ.get("CURSOR_API_KEY", "")
    key = raw.strip()
    if not key:
        print("FAIL preflight: CURSOR_API_KEY is not set in this shell.")
        print("      Set the REAL key in the SAME window you run this from.")
        print("      Do not paste the placeholder string from the instructions.")
        return None
    looks_placeholder = len(key) < 20 or any(m in key.lower() for m in _PLACEHOLDER_MARKERS)
    if looks_placeholder:
        print(
            f"FAIL preflight: CURSOR_API_KEY looks like a placeholder "
            f"(len={len(key)}), not a Cursor user/service key."
        )
        print("      Re-paste the key from Cursor Dashboard -> Integrations.")
        print("      Do not wrap it in quotes that include the angle-bracket example.")
        return None
    print(f"ok   api key present (len={len(key)})")

    try:
        import cursor_sdk
    except Exception as exc:  # pragma: no cover - import diagnostics
        print(f"FAIL preflight: cannot import cursor_sdk: {exc}")
        return None
    version = getattr(cursor_sdk, "__version__", None)
    print(f"ok   cursor_sdk {version or '1.0.x (no __version__ attr)'}")

    bridge = Path(cursor_sdk.__file__).parent / "_vendor" / "bridge"
    manifest = bridge / "manifest.json"
    if not manifest.is_file():
        print(f"FAIL preflight: bridge manifest missing at {manifest}")
        return None

    entry = json.loads(manifest.read_text(encoding="utf-8"))
    entrypoint = bridge / entry.get("entrypoint", "")
    if not entrypoint.is_file():
        print(f"FAIL preflight: bridge entrypoint missing at {entrypoint}")
        return None
    print(f"ok   bridge entrypoint {entrypoint.name} (bridge {entry.get('bridgeVersion')})")

    from orchestrator.runtime import _ensure_bridge_ca_trust

    ca = _ensure_bridge_ca_trust()
    if ca:
        print(f"ok   NODE_EXTRA_CA_CERTS -> {ca}")
    else:
        print("warn no corp CA bundle found. If this network inspects TLS, the")
        print("     bridge will fail 'Network request failed'. Generate one with:")
        print("     powershell -ExecutionPolicy Bypass -File tools\\export_corp_ca.ps1")
    return key


def _explain(exc: BaseException) -> None:
    text = str(exc)
    print("     Interpretation:")
    if "missing_bridge_endpoint" in text:
        print("       Bare AsyncClient() was used. 1.0.30 requires")
        print("       AsyncClient.launch_bridge(...) or connect(base_url, auth_token).")
        print("       The orchestrator already uses launch_bridge; this is a")
        print("       harness bug if you still see it after this rewrite.")
    elif "missing_api_key" in text:
        print("       Key not visible to this process, or not forwarded on create.")
    elif "Network request failed" in text:
        print("       Bridge launched; its outbound call to Cursor failed.")
        print("       Key rejected, Privacy Mode, or allowlisting — not orchestrator.")
    elif "ENOENT" in text or "spawn" in text.lower():
        print("       Bridge binary could not launch.")
    else:
        print("       See traceback. This is still SDK/bridge, not the console.")


async def _run(workspace: Path, api_key: str) -> int:
    from cursor_sdk import AsyncClient, LocalAgentOptions

    probe = workspace / "probe.txt"
    probe.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    client = None
    agent = None
    try:
        client = await AsyncClient.launch_bridge(
            workspace=str(workspace),
            local=LocalAgentOptions(cwd=str(workspace), setting_sources=[]),
        )
        print("ok   launch_bridge (local cursor-sdk-bridge is up)")

        try:
            agent = await client.create_agent(
                {
                    "model": "composer-2.5",
                    "api_key": api_key,
                    "local": {
                        "cwd": str(workspace),
                        "setting_sources": [],
                    },
                }
            )
        except Exception as exc:
            print(f"FAIL create_agent: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            _explain(exc)
            return 1

        agent_id = getattr(agent, "agent_id", None)
        print(f"ok   agent created id={agent_id}")

        try:
            run = await agent.send(
                "Read probe.txt and reply with only the number of lines it contains."
            )
            run_id = getattr(run, "id", None)
            print(f"ok   send accepted run_id={run_id}")
            result = await run.wait()
        except Exception as exc:
            print(f"FAIL send/wait: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            _explain(exc)
            return 1

        status = getattr(result, "status", None)
        text = getattr(result, "result", None)
        print(f"{'ok  ' if status == 'finished' else 'FAIL'} wait status={status} result={text!r}")
        return 0 if agent_id and status == "finished" else 1
    except Exception as exc:
        print(f"FAIL launch_bridge: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        _explain(exc)
        return 1
    finally:
        if agent is not None:
            try:
                await agent.close()
            except Exception as exc:  # pragma: no cover - cleanup
                print(f"warn agent.close: {exc}")
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:  # pragma: no cover - cleanup
                print(f"warn client.aclose: {exc}")


def main() -> int:
    key = _preflight()
    if not key:
        return 1
    with tempfile.TemporaryDirectory(prefix="sdk-smoke-") as tmp:
        workspace = Path(tmp)
        print(f"ok   disposable workspace {workspace}")
        return asyncio.run(_run(workspace, key))


if __name__ == "__main__":
    code = main()
    print("RESULT: PASS" if code == 0 else "RESULT: FAIL")
    sys.exit(code)
