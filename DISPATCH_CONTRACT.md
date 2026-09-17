# Dispatch contract

What may be handed to a headless agent, and what must stay in a session.

Dispatch exists so the operator stops opening a chat session for every
mechanical errand. It is not a way to get judgment work done while you sleep.
A dispatched task runs without a human reading the intermediate steps, so the
only tasks worth dispatching are the ones where a wrong answer is *obvious*.

Measured on 2026-09-09: asked how many lines were in a 5-line file, headless
`composer-2.5` answered 5, 8, and 6 across three runs, and once ignored the
JSON response contract entirely. Assume that error rate when deciding.

## The test

Dispatch only if **all five** are true.

1. **Bounded.** One objective, completable in a single agent run. If it needs a
   second decision after the first result, it is a conversation, not a task.
2. **Evidence-pointed.** Exact paths. A headless agent cannot resolve "the
   value file" or "the latest deck" — it has no idea which one you mean, and it
   will pick one and sound certain. The `--evidence` flag is mandatory for
   dispatch for this reason.
3. **Verifiable.** You can check the answer without redoing the work: an exact
   value, a count, a list, a quoted line, a cell reference. If checking it
   costs as much as doing it, dispatch bought you nothing.
4. **Read-only, or a write you would approve anyway.** Write-capable tasks stop
   for approval before touching anything; that gate is not optional and not a
   substitute for judgment.
5. **Cheap to be wrong.** If a wrong answer would flow into a client
   deliverable without someone noticing, do it in a session instead.

## Never dispatch

- Judgment and strategy — "align the value case", "what should the target be".
- Anything needing accumulated session context. The agent starts cold.
- Numerical model construction. Same rule as subagents: precision work stays
  where the reasoning chain is.
- Executive or client-facing writing.
- Decision log updates. The dispatch overhead exceeds the work.
- Anything where you cannot state the acceptance test before sending it.

## How to write one

```powershell
py -3 "$HOME/.cursor/skills/operating-system/scripts/inbox_send.py" `
  --executable --evidence "<exact path>" `
  "<Workspace>" "<Target Lane>" "<From Lane>" "<bounded objective>"
```

Say what the answer should look like inside the objective — "reply with the
integer and the filename you read" beats "count the lines". Keep it under 600
characters; if it does not fit, it is probably not bounded.

## What comes back

The agent replies through the governed contract
(`summary` / `status` / `evidence` / `proposed_messages`), stored on the task
and visible in the console and the snapshot.

- `structured: false` means the model ignored the response contract. Treat the
  answer as unverified regardless of how reasonable it reads.
- Any message the agent proposes is **held**, never executed. An agent cannot
  schedule the next agent; a human promotes it or it expires.

## What is enforced, and what is not

Mechanical, enforced in code:

- Coordination is the default; execution is opt-in.
- `--executable` without `--evidence` is refused.
- Write-capable tasks stop for approval.
- Unknown or retired target lanes dead-letter instead of running.
- Agent-proposed messages are held pending promotion.

Judgment, enforced by whoever dispatches:

- Boundedness, verifiability, and the cost of being wrong.

The code can stop you from dispatching *carelessly*. It cannot stop you from
dispatching something that should have been a conversation.
