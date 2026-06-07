# autoloop — self-driving goal loop for llmdocs

**Date:** 2026-06-08
**Status:** Design approved; ready for implementation plan.
**Scope:** One implementation plan (single package, ~6 source files + tests).

---

## 1. Problem & goal

llmdocs already has the pieces to do parallel, planned agent work — `fan-out-code`
(planner + parallel execution), `prompt-stamper` (prompt generation), and the
`agent-patterns` orchestration vocabulary. They are all **human-invoked**: a person types
`/fan-out-code <task>` and re-invokes each phase by hand. Nothing **closes the loop
unattended**.

**Goal:** a real Python binary, `autoloop`, that takes **one goal** and self-drives
`plan → fan-out → verify → re-plan` until the goal is met or a budget is hit — with no
re-invocation. It is the thin *evaluator-optimizer* shell around Claude's own
orchestration: Claude plans and executes each turn (delegating to subagents); the driver
evaluates the stop condition, enforces a token/cost budget, runs a safety guardrail, and
persists continuity for resume.

**Non-goals (YAGNI):**
- No scheduled/cron daemon mode (a later, separate spec — this is one-shot self-driving on a goal).
- No new planner or fan-out engine — reuse the existing patterns/prompts.
- No web UI, no multi-goal queue, no distributed execution.
- No billing/financial decisions off cost numbers (they are estimates — see §7).

**First real goal (acceptance demo):** `autoloop "close llmdocs issues #1-9" --budget 5.00`.

---

## 2. Grounding (local Claude Agent SDK docs)

Every primitive below was confirmed by grepping the local store
(`~/.llmdocs/docs/claude-agent-sdk/en/agent-sdk/`), not assumed:

| Need | API (verbatim from store) | Page |
|---|---|---|
| Loop body | `ClaudeSDKClient` async ctx mgr; `await client.query(p)` auto-continues the session; `async for m in client.receive_response()` | `sessions.md`, `python.md` |
| Plan / verdict | `output_format={"type":"json_schema","schema": Model.model_json_schema()}` → `ResultMessage.structured_output` | `structured-outputs.md` |
| Fan-out + results | `agents={name: AgentDefinition(description=, prompt=, tools=, model=)}`; parent receives the subagent's **final message verbatim** as the Agent tool result; `agentId:` trailer | `subagents.md` |
| Budget / stop | `ResultMessage.total_cost_usd` (client-side estimate) + `usage` dict; options `max_budget_usd`, `max_turns` | `cost-tracking.md`, `python.md` |
| Unattended safety | `permission_mode` ∈ {`default`,`acceptEdits`,`bypassPermissions`,`plan`}; `PreToolUse` `HookMatcher` → `{"permissionDecision":"deny","permissionDecisionReason":...}` | `permissions.md`, `hooks.md` |
| Restart continuity | `resume=session_id` / `fork_session=True` / `continue_conversation=True`; read `session_id` off the `ResultMessage` | `sessions.md` |

`ClaudeAgentOptions` fields used: `system_prompt`, `permission_mode`, `agents`, `hooks`,
`max_turns`, `max_budget_usd`, `output_format`, `setting_sources`, `allowed_tools`,
`disallowed_tools`, `resume`, `fork_session`, `cwd`, `model`.

---

## 3. Architecture & placement

A new **isolated package** `autoloop/` in the llmdocs repo that **does not import the
doc-pipeline code** (`crawler.py`, `scripts/`), keeping the stdlib-light core portable.
`claude-agent-sdk` (and `pydantic`) are an **optional extra**, declared in
`requirements-autoloop.txt` and a `pip install .[autoloop]` extra — the core tool stays
dependency-free and API-key-free.

```
goal ──► [ PLAN+EXECUTE turn ] ──► Verdict{done, reason, remaining[]}
            ▲ (Claude orchestrates;          │
            │  fans out to subagents)        │ driver evaluates
            └──────── remaining[] ◄──────────┘ stop condition
                                              │
                            done | budget | max_turns | error
                                              ▼
                                          RunResult
```

The driver owns only: the loop, the budget accounting, the guardrail, continuity, and the
run log. Claude owns the planning and the work.

---

## 4. Components (one job each, independently testable)

### `autoloop/schemas.py`
Pydantic models, used both as `output_format` schemas and as typed returns.
- `Task{ id: str, title: str, prompt: str, agent: str, status: Literal["pending","done","failed"] }`
- `Plan{ rationale: str, tasks: list[Task] }`
- `Verdict{ done: bool, reason: str, remaining: list[str] }` ← the per-turn structured output
- `RunResult{ status: Literal["done","budget","maxturns","error"], turns: int, cost_usd: float, session_id: str | None, reason: str, log_path: str }`

The loop reads **`Verdict`** each turn (it is what `output_format` requests). `Plan` is
available for a future explicit-fan-out mode but is not on the critical path in v1.

### `autoloop/agents.py`
The fan-out worker registry: `REGISTRY: dict[str, AgentDefinition]`.
- `fixer` — Read/Edit/Bash/Grep/Glob; "implement the assigned task, run the relevant test, report what changed and the test result."
- `verifier` — Read/Bash/Grep; "independently verify a claimed fix; run the test; report pass/fail with evidence." (Read-only-ish: no Edit.)
- `researcher` — Read/Grep/Glob/Bash(grep only); "answer a focused question from the repo and the llmdocs store; cite file:line."
- A `build_registry(overrides: dict | None)` factory so callers can add/replace agents.
Models default to the session model; `verifier` may pin a cheaper model. Field names follow
the SDK wire format (camelCase) per `subagents.md`.

### `autoloop/guardrail.py`
A `PreToolUse` hook enforcing an unattended **deny set** (returns
`permissionDecision: "deny"` with a reason):
- Bash command matches any of: `rm -rf`, `git push --force`/`-f`, `git reset --hard`,
  `ssh ` to a host, `scp `, `deploy`, `systemctl`, `sudo`, `curl`/`wget` piped to a shell.
- Write/Edit targeting `.env`, `*.pem`, `id_*`, `~/.ssh/`, anything outside `cwd`.
- A `make_guardrail(extra_deny: list[str] | None, cwd: Path)` factory returning the hook
  callback; the matched rule + reason go to the run log.
The deny set is the safety boundary that makes `permission_mode="acceptEdits"` acceptable.

### `autoloop/driver.py`
```python
async def run(goal: str, *, budget_usd: float, max_turns: int,
              model: str | None = None, resume: str | None = None,
              dry_run: bool = False, cwd: Path = Path.cwd(),
              registry: dict | None = None, log=...) -> RunResult
```
Builds `ClaudeAgentOptions` (see §5), opens `ClaudeSDKClient`, and runs the loop. Pure
async; all I/O (printing, logging) injected via a `log` callable so tests stay silent.
Accepts an injectable `client_factory` (defaults to the real `ClaudeSDKClient`) so the loop
is testable against a fake — **no real API calls in tests**.

### `autoloop/cli.py`
`argparse` entry point (`autoloop` console-script + `python -m autoloop`):
```
autoloop "<goal>" [--budget 5.00] [--max-turns 20] [--model claude-...]
                  [--resume SESSION_ID] [--dry-run] [--cwd PATH]
```
Validates `ANTHROPIC_API_KEY` is set (fail loud with a clear message), runs
`asyncio.run(driver.run(...))`, prints turn-by-turn progress, exits non-zero on
`status in {"error"}` (and prints the reason for `budget`/`maxturns`).

---

## 5. The loop (driver.py, precise)

```python
opts = ClaudeAgentOptions(
    system_prompt={"type": "preset", "preset": "claude_code", "append": OPERATING_RULES},
    permission_mode="plan" if dry_run else "acceptEdits",
    agents=registry or build_registry(None),
    hooks={"PreToolUse": [HookMatcher(matcher="Bash|Write|Edit", hooks=[guardrail])]},
    max_turns=max_turns,
    max_budget_usd=budget_usd,
    output_format={"type": "json_schema", "schema": Verdict.model_json_schema()},
    setting_sources=["project"],            # loads repo CLAUDE.md
    allowed_tools=["Agent", "Read", "Edit", "Bash", "Grep", "Glob"],
    model=model, resume=resume, cwd=str(cwd),
)
cost = 0.0; turns = 0; session_id = resume; last = None
async with client_factory(options=opts) as client:
    while True:
        await client.query(turn_prompt(goal, last))
        result = None
        async for m in client.receive_response():
            if isinstance(m, ResultMessage): result = m
        turns += 1
        cost += (result.total_cost_usd or 0.0)
        session_id = result.session_id or session_id
        verdict = Verdict.model_validate(result.structured_output or {})
        log(turns, verdict, cost)
        if verdict.done:                 return RunResult("done", turns, cost, session_id, verdict.reason, ...)
        if cost >= budget_usd:           return RunResult("budget", turns, cost, session_id, "budget exhausted", ...)
        if turns >= max_turns:           return RunResult("maxturns", turns, cost, session_id, "turn cap", ...)
        last = verdict                   # remaining[] feeds the next turn
```

`OPERATING_RULES` (the preset `append`) instructs Claude to: work the goal by delegating
independent units to the named subagents **in parallel via the `Agent` tool**; never run
deploy/destructive commands; after each round, emit the `Verdict` (`done` only when the
goal is fully met **and verified**, else list `remaining`). `turn_prompt` injects the goal
on turn 1 and `"Continue. Outstanding: <remaining>"` thereafter — session history (incl.
subagent final messages, returned verbatim) carries the rest.

---

## 6. Data flow

`goal` → turn 1 prompt → Claude plans + fans out to subagents → subagent final messages
return verbatim into session history → `ResultMessage.structured_output` = `Verdict` →
driver checks `done`/budget/turns → if not done, `remaining[]` → next turn prompt
(same session) → … → `RunResult`. The structured `Verdict` is the single spine; the JSONL
run log records every turn (verdict, cost, any guardrail denials) for audit and resume.

---

## 7. Error handling & edge cases

- **Terminal API error** (after SDK retries): caught in the loop, logged, returns
  `RunResult(status="error", reason=...)`. Never crashes mid-run.
- **Cost is an estimate.** `total_cost_usd` is a client-side estimate (docs caveat in
  `cost-tracking.md`) — treated as a *soft* ceiling; `max_turns` is the *hard* backstop, and
  `max_budget_usd` is also passed to the SDK as defense-in-depth. The CLI prints a "cost is
  an estimate, not a bill" note.
- **Guardrail denial:** logged with the matched rule + reason; Claude sees the denial and
  adapts within the same turn.
- **Non-convergence** (verdict never `done`): bounded by `max_turns`; `RunResult("maxturns")`.
- **`--dry-run`:** `permission_mode="plan"` — Claude produces the plan and Verdict with
  **zero writes**; used to preview what a goal would do.
- **Missing `ANTHROPIC_API_KEY`:** CLI fails loudly before any network call.
- **Resume:** `--resume <session_id>` continues a prior run's session; `session_id` is read
  off every `ResultMessage` and printed at the end of every run.

---

## 8. Testing (TDD; no real API in CI)

Unit (pure, fast):
- `schemas`: `Verdict`/`Plan`/`Task` validate; bad payloads raise.
- `guardrail`: each deny-set rule is denied (rm -rf, force-push, ssh, .env, out-of-cwd);
  safe commands (`pytest`, `grep`, `git status`, in-cwd Edit) are allowed.
- `cli`: arg parsing + the missing-API-key failure path.
- budget/turn accounting math.

Loop (against a **fake SDK client**): a stub `client_factory` yielding canned
`ResultMessage`s with crafted `structured_output`/`total_cost_usd`. Assert:
- stops with `status="done"` when a verdict sets `done=True`;
- stops with `status="budget"` when accumulated cost crosses `budget_usd`;
- stops with `status="maxturns"` at the cap;
- `remaining[]` from turn N appears in turn N+1's prompt;
- a terminal exception from the client → `status="error"`, loop exits cleanly.

Real-API end-to-end (the demo goal) is an **opt-in manual script**
(`scripts/autoloop_smoke.py`, gated on `ANTHROPIC_API_KEY`), never run in CI.

Target ≥ 90% coverage on `driver`/`guardrail`/`schemas`.

---

## 9. Packaging, security, docs

- **Optional extra:** `pip install .[autoloop]` (or `-r requirements-autoloop.txt`) pulls
  `claude-agent-sdk` + `pydantic`. Core llmdocs install is unchanged.
- **Console script:** `autoloop = autoloop.cli:main` (also `python -m autoloop`).
- **Secrets:** API key from env only; never logged. Run logs go to
  `~/.llmdocs/autoloop/<timestamp>-<slug>.jsonl` (outside the repo).
- **Docs:** a `docs/autoloop.md` page (what it is, the safety guardrail, the budget caveat,
  the resume flow) + a README mention under a new "Autonomous" section. Keeps Claude/Anthropic
  framing for discoverability.

---

## 10. Open questions

None blocking. Deferred to a future spec: scheduled/daemon mode; an explicit driver-side
fan-out mode that parses `Plan.tasks` and issues per-task subagent calls (v1 lets Claude
orchestrate the fan-out within the turn, which is simpler and matches the agent-patterns
orchestrator model).
