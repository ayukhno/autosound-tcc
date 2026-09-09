# Spike: the SDK sandbox for Bash in a tuning session (HUB-034)

**Verdict: worth enabling on macOS, and ONLY with two settings changed from their defaults.**
With the defaults it silently disables TCC's own permission gate — including everything HUB-028
added on the same day. This spike changes no product code; it answers five questions with
commands and their output.

Run 2026-09-09, macOS 15 (Apple M1 Pro), `claude-agent-sdk` 0.2.145, REW 5.40 Beta 132 answering
on `localhost:4735`. Probe scripts were throwaway; every command below is quoted from a real run.

## 1. `autoAllowBashIfSandboxed` defaults to True, and that BYPASSES `can_use_tool`

The finding that decides the whole ticket. Same options as a real `TuningSession`
(`allowed_tools=["mcp__tcc", "TodoWrite"]`, a `can_use_tool` that denies everything), one command,
sandbox on:

| sandbox | `autoAllowBashIfSandboxed` | `can_use_tool` called | what happened to `rm -rf /tmp/…` |
|---|---|---|---|
| on | default (**True**) | **0 times** | **it ran**, exit 0 |
| on | `False` | 1 time | denied, never reached the shell |

So turning the sandbox on with defaults would trade a gate that reads the command for one that
does not, and nothing would say so. **`autoAllowBashIfSandboxed: False` is not optional here.**

## 2. The gate is alive today, and it is a SECOND layer, not the first

Worth writing down because it looked broken for ten minutes. With no sandbox and TCC's own
options:

```
`echo hello`              -> can_use_tool called 0 times   (the CLI approved it itself)
`printf x > probe.txt`    -> can_use_tool called 1 time    (denied)
`rm -rf /tmp/…`           -> can_use_tool called 1 time    (denied)
```

The CLI auto-approves what it considers harmless before our callback is consulted. That is fine —
but it means `bash_is_dangerous` never sees every command, and no claim of the form "TCC examines
every command the agent runs" is true. It examines every command the CLI did not already wave
through.

Separately: an `allowed_tools` entry that names a whole tool auto-approves it *before* the
callback, and the SDK warns about it (`CanUseToolShadowedWarning`). TCC is safe here — `Bash` is
not in `ALLOWED_TOOLS` — and it must stay that way.

## 3. What the sandbox stops by itself

```
`sudo -n true`   ->  exit 127, "(eval):1: operation not permitted: sudo"
```

The OS refuses it; the model sees a shell error, not a permission dialog, and reported it plainly.
This is real protection and it is independent of the gate.

## 4. What it does NOT stop: reading outside the project

```
`ls ~/.claude | head -3`  ->  CLAUDE.md  backups  bridge-spawn
```

The sandbox's default is not a read jail. Denying `~/.ssh`, `~/.claude`, `~/.config` needs
explicit deny rules from the SDK options — **not** from the project's `.claude/settings.json`,
which TCC no longer reads at all (HUB-050). Not built here: this spike's job was to find out, and
what it found is that the file rules are a separate piece of work.

## 5. REW on loopback needs `allowLocalBinding`

```
sandbox on, no network config      ->  `curl -s -m 3 http://localhost:4735/version` fails
sandbox on, allowLocalBinding=True ->  {"message": "5.40 Beta 132 API 0.9.6"}
```

Same port, same minute, REW up throughout. The model's own guess on the first run was "probably
nothing is listening" — it was the sandbox, and that matters for how a failure will look to a
tuner: **a blocked loopback reads as "REW is not running"**, which is the single most misleading
thing this could do in a car.

## Recommendation

Enable on macOS as a layer over the command allowlist (HUB-027) and the gate (HUB-028), with:

```python
sandbox={
    "enabled": True,
    "autoAllowBashIfSandboxed": False,        # §1 — without this the gate is gone
    "network": {"allowLocalBinding": True},   # §5 — REW and TCC's own MCP are on loopback
}
```

It replaces nothing. It stops a class the parser cannot see (`xargs`, `bash -c`, `awk`), and the
gate stops a class the OS has no opinion about (`rm -rf ~/Music`, which is the tuner's own data
and entirely permitted).

**Windows: there is no sandbox.** The allowlist and the gate are the whole of it there, and any
wording that says "commands are sandboxed" has to say "on macOS and Linux".

## What this spike did NOT establish

Named rather than glossed, because a spike that reports only what it managed is worth less than
one that says where it stopped:

* **TCC's own MCP over loopback inside the sandbox.** REW answers on 4735 with
  `allowLocalBinding`, and TCC's server is the same shape on 127.0.0.1 — but "the same shape" is
  an argument, not a measurement. Untested.
* **Startup cost.** Not measured. The probes ran in seconds and nothing looked slow, which is not
  a number.
* **Linux.** Everything here is macOS. `enableWeakerNestedSandbox` exists for unprivileged Docker
  and was not touched.
* **The ten dangerous commands from HUB-027 inside the sandbox with the allowlist off.** Only
  `sudo` was tried. The rest would each need a target that is harmless if the sandbox lets it
  through, and building ten of those safely is its own afternoon.
