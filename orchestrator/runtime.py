from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable
from uuid import uuid4

from .models import AgentConfig, ContextEnvelope, FailureKind, RunOutcome


_BUSY_AGENT_TEXT = "already has active run"


class StartupError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AgentBusyError(StartupError):
    """The agent still owns an unfinished run and cannot accept a new one.

    `create_agent` also opens run #1, so an agent whose first send failed keeps
    that run active for good. Recoverable only by moving to a fresh agent.
    """


@runtime_checkable
class AgentRuntime(Protocol):
    async def create_agent(self, config: AgentConfig, context: ContextEnvelope) -> str: ...

    async def resume_agent(self, agent_id: str, config: AgentConfig, context: ContextEnvelope) -> str: ...

    async def run_task(
        self,
        agent_id: str,
        prompt: str,
        *,
        idempotency_key: str | None = None,
        on_started: Callable[[str], None] | None = None,
    ) -> RunOutcome: ...

    async def dispose_agent(self, agent_id: str) -> None: ...

    async def close(self) -> None: ...


@dataclass
class FakeAgentState:
    agent_id: str
    config: AgentConfig
    context: ContextEnvelope
    disposed: bool = False
    runs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakeRuntime:
    """In-memory runtime for tests; never invokes a real model."""

    agents: dict[str, FakeAgentState] = field(default_factory=dict)
    run_results: dict[str, RunOutcome | Exception] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    resumed: list[str] = field(default_factory=list)
    disposed: list[str] = field(default_factory=list)
    closed: bool = False

    async def create_agent(self, config: AgentConfig, context: ContextEnvelope) -> str:
        agent_id = f"fake-{uuid4().hex[:8]}"
        self.agents[agent_id] = FakeAgentState(agent_id=agent_id, config=config, context=context)
        self.created.append(agent_id)
        return agent_id

    async def resume_agent(self, agent_id: str, config: AgentConfig, context: ContextEnvelope) -> str:
        if agent_id not in self.agents:
            raise StartupError(f"Unknown agent {agent_id}")
        state = self.agents[agent_id]
        state.config = config
        state.context = context
        state.disposed = False
        self.resumed.append(agent_id)
        return agent_id

    async def run_task(
        self,
        agent_id: str,
        prompt: str,
        *,
        idempotency_key: str | None = None,
        on_started: Callable[[str], None] | None = None,
    ) -> RunOutcome:
        if agent_id not in self.agents:
            raise StartupError(f"Unknown agent {agent_id}")
        state = self.agents[agent_id]
        if state.disposed:
            raise StartupError(f"Agent {agent_id} is disposed")
        run_id = f"run-{uuid4().hex[:8]}"
        if on_started:
            on_started(run_id)
        state.runs.append({"run_id": run_id, "prompt": prompt, "idempotency_key": idempotency_key})
        key = idempotency_key or run_id
        configured = self.run_results.get(key) or self.run_results.get(agent_id) or self.run_results.get("*")
        if isinstance(configured, Exception):
            raise configured
        if configured:
            return RunOutcome(
                agent_id=agent_id,
                run_id=run_id,
                status=configured.status,
                failure_kind=configured.failure_kind,
                error_message=configured.error_message,
                result_text=configured.result_text,
            )
        return RunOutcome(agent_id=agent_id, run_id=run_id, status="finished", result_text="ok")

    async def dispose_agent(self, agent_id: str) -> None:
        if agent_id in self.agents:
            self.agents[agent_id].disposed = True
        self.disposed.append(agent_id)

    async def close(self) -> None:
        self.closed = True


def _ensure_bridge_ca_trust() -> str | None:
    """Point Node at the corporate root CA bundle, if one has been exported.

    The cursor-sdk bridge is a Node subprocess. Node ignores the Windows
    certificate store, so networks that terminate TLS (PwC perimeter security
    here) make every bridge call fail with `Network request failed`. The bridge
    inherits this process's environment, so setting the variable before launch
    is what actually reaches Node. Generate the bundle with
    `tools/export_corp_ca.ps1`.
    """
    import os

    existing = os.environ.get("NODE_EXTRA_CA_CERTS")
    if existing and Path(existing).is_file():
        return existing

    bundle = Path.home() / ".cursor" / "corp-ca.pem"
    if bundle.is_file():
        os.environ["NODE_EXTRA_CA_CERTS"] = str(bundle)
        return str(bundle)
    return None


class CursorSDKRuntime:
    """Adapter around cursor_sdk AsyncClient for local supervised runs."""

    def __init__(
        self,
        client: Any,
        *,
        api_key: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._live_agents: dict[str, Any] = {}
        self._api_key = api_key
        self._config_overrides = config_overrides or {}

    @classmethod
    async def connect(
        cls,
        workspace: str,
        *,
        api_key: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> CursorSDKRuntime:
        from cursor_sdk import AsyncClient, LocalAgentOptions

        _ensure_bridge_ca_trust()
        client = await AsyncClient.launch_bridge(
            workspace=workspace,
            local=LocalAgentOptions(cwd=workspace, setting_sources=[]),
        )
        runtime = cls(
            client,
            api_key=api_key,
            config_overrides=config_overrides,
        )
        return runtime

    async def close(self) -> None:
        for agent in list(self._live_agents.values()):
            await agent.close()
        self._live_agents.clear()
        # cursor-sdk 1.0.30 is asymmetric: AsyncAgent exposes close(),
        # while AsyncClient exposes aclose().
        await self._client.aclose()

    def _build_options(self, config: AgentConfig) -> dict[str, Any]:
        merged = AgentConfig.from_dict(
            {**config.to_dict(), **self._config_overrides}
        )
        local_opts: dict[str, Any] = {
            "cwd": merged.cwd or ".",
            "setting_sources": merged.setting_sources,
        }
        if merged.sandbox:
            local_opts["sandbox_options"] = merged.sandbox
        options: dict[str, Any] = {
            "model": merged.model,
            "local": local_opts,
        }
        if self._api_key or merged.api_key:
            options["api_key"] = self._api_key or merged.api_key
        if merged.mcp_servers:
            options["mcp_servers"] = merged.mcp_servers
        if merged.tools:
            options["tools"] = merged.tools
        if merged.disallowed_tools:
            options["disallowed_tools"] = merged.disallowed_tools
        return options

    async def create_agent(self, config: AgentConfig, context: ContextEnvelope) -> str:
        from cursor_sdk import CursorAgentError

        options = self._build_options(config)
        try:
            agent = await self._client.create_agent(options)
        except CursorAgentError as err:
            raise StartupError(
                str(getattr(err, "message", err)),
                retryable=bool(getattr(err, "is_retryable", False)),
            ) from err
        except TypeError as err:
            raise StartupError(str(err), retryable=False) from err
        self._live_agents[agent.agent_id] = agent
        return agent.agent_id

    async def resume_agent(self, agent_id: str, config: AgentConfig, context: ContextEnvelope) -> str:
        from cursor_sdk import CursorAgentError

        options = self._build_options(config)
        try:
            agent = await self._client.resume_agent(agent_id, options)
        except CursorAgentError as err:
            raise StartupError(
                str(getattr(err, "message", err)),
                retryable=bool(getattr(err, "is_retryable", False)),
            ) from err
        except TypeError as err:
            raise StartupError(str(err), retryable=False) from err
        self._live_agents[agent_id] = agent
        return agent_id

    async def run_task(
        self,
        agent_id: str,
        prompt: str,
        *,
        idempotency_key: str | None = None,
        on_started: Callable[[str], None] | None = None,
    ) -> RunOutcome:
        from cursor_sdk import AgentBusyError as SdkAgentBusyError
        from cursor_sdk import CursorAgentError

        agent = self._live_agents.get(agent_id)
        if agent is None:
            raise StartupError(
                f"No live handle for agent {agent_id}; resume it with full configuration first"
            )
        try:
            # Local send in cursor-sdk v1 rejects Idempotency-Key. Store-level
            # uniqueness still uses the parameter; do not forward it.
            _ = idempotency_key
            run = await agent.send(prompt)
            run_id = run.id
            if on_started:
                on_started(run_id)
        except CursorAgentError as err:
            message = str(getattr(err, "message", err))
            # Only cloud 409s carry the `agent_busy` code. The local run store
            # raises a plain error, so the message is the only signal there.
            if isinstance(err, SdkAgentBusyError) or _BUSY_AGENT_TEXT in message:
                raise AgentBusyError(message) from err
            raise StartupError(
                message,
                retryable=bool(getattr(err, "is_retryable", False)),
            ) from err

        try:
            result = await run.wait()
        except CursorAgentError as err:
            raise StartupError(
                str(getattr(err, "message", err)),
                retryable=bool(getattr(err, "is_retryable", False)),
            ) from err

        if result.status == "error":
            return RunOutcome(
                agent_id=agent_id,
                run_id=result.id or run_id,
                status="error",
                failure_kind=FailureKind.RUN,
                error_message=result.result or "run failed",
            )
        return RunOutcome(
            agent_id=agent_id,
            run_id=result.id or run_id,
            status=result.status,
            result_text=result.result,
        )

    async def dispose_agent(self, agent_id: str) -> None:
        agent = self._live_agents.pop(agent_id, None)
        if agent is not None:
            await agent.close()
