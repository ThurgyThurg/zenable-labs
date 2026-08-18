# ACP workshop rig

Working reference implementation behind the **ACP: The Protocol Between Your
Editor and Your Agent** training unit on the [Zenable Learning
Hub](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=acp_readme).
Every command and every expected output in that lab was captured from a real
run; `evidence/` holds those captures.

The lab clones this tree and runs it, so these files are the ones a reader
executes. A fix here reaches them immediately; nothing is retyped from the
Learning Hub.

## Which ACP?

The one Zed published in August 2025: **Agent Client Protocol**, JSON-RPC over
stdio, connecting a code editor to a coding agent. The "LSP for agents."

Two other live protocols share the acronym and are unrelated to this lab:

- **Agent Communication Protocol** — IBM Research, powered BeeAI, donated to the
  Linux Foundation and [merged into
  A2A](https://lfaidata.foundation/communityblog/2025/08/29/acp-joins-forces-with-a2a-under-the-linux-foundations-lf-ai-data/)
  in August 2025. Agent-to-agent, REST. If you arrived from an A2A context, this
  is probably the one you meant.
- **Agentic Commerce Protocol** — OpenAI and Stripe, for buying things.

## The pieces

| File | What it is |
| --- | --- |
| `acp_handshake.py` | Speaks `initialize` to a real agent and reports the negotiated capabilities. No model required. |
| `acp_policy_proxy.py` | Sits between client and agent, audits every frame, and refuses configured agent→client calls. |
| `demanding_agent.py` | A stub agent that does nothing but ask to write a file and run a command. Removes the model from the experiment. |
| `permissive_client.py` | A client that grants every callback, so "allowed" is a real effect rather than a claim. |

Standard library only. Python 3.11+.

## The experiment

The point of the rig is that one action produces opposite outcomes depending on
what sits on the wire.

```bash
# No policy: the agent reaches the machine.
python3 permissive_client.py -- python3 demanding_agent.py

# Same agent, same client, policy in between: it does not.
python3 permissive_client.py -- \
  python3 acp_policy_proxy.py \
    --deny fs/write_text_file --deny terminal/create --audit audit.jsonl -- \
    python3 demanding_agent.py
```

`evidence/allowed.txt` and `evidence/denied.txt` are those two runs. The captures
were taken in a `python:3.12-slim` container, which is why `id` reports root —
run them on your own machine and you will see your own account, which is the
part worth noticing.

## Why a stub agent

A real agent reaches back into the client only when a model decides to, so the
interesting call happens or it doesn't depending on a sampled token. That is
untestable and it makes a bad demo. `demanding_agent.py` always makes both
calls, so whether they succeed is a property of the policy and nothing else.

Driving real `goose` is the last section of the lab, once the mechanism is
already clear.

## Where this rig stops

It teaches the protocol and the trust boundary. It is **not** a production
policy engine:

- The proxy matches on method name only. It never inspects a path, a command, or
  an argument, so `--deny fs/write_text_file` is all-or-nothing.
- There is no identity anywhere. Nothing here authenticates the agent, and the
  ACP `authMethods` negotiated during `initialize` are reported but never used.
- The audit log has no integrity protection. It is a file the audited party
  could edit.

Real deployments need per-path rules, an identity to attribute the request to,
and a log the agent cannot reach. Those are the layer above this one.
