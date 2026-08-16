# MCP Enterprise-Managed Authorization (EMA / ID-JAG) — working end-to-end demo

Fully local. No vendor accounts, no signups, no cloud. One command:

```bash
./run.sh          # bring up + happy path + deny paths + security negatives
./run.sh down     # tear down
```

Requires Docker, `uv`, `jq`, `curl`.

## What it demonstrates

A real MCP client obtains a real access token for a real MCP server **without a browser
redirect or a consent screen**, because the enterprise IdP asserted both the user's identity
and the administrator's approval in a single signed grant.

```
  alice ──SSO──> enterprise IdP ──(1) RFC 8693 token exchange──> ID-JAG
                 (realm: enterprise)         requested_token_type=...id-jag
                        │                    audience = vendor AS
                        │                    resource = the MCP server
                        │  ADMIN POLICY EVALUATED HERE
                        ▼
  MCP client ──(2) RFC 7523 jwt-bearer, assertion=ID-JAG──> vendor AS
                                                            (realm: vendor)
                                                                 │
                                                                 ▼
                                                          access token
                                                          aud = the MCP server
                                                                 │
  MCP client ──(3) Authorization: Bearer ...──────────> MCP server :9100
```

The two Keycloak realms are **separate trust domains** on purpose. `vendor` trusts
`enterprise` only through an explicitly configured `jwt-authorization-grant` identity
provider pinned to its issuer and JWKS — exactly the out-of-band onboarding step a real SaaS
vendor performs per customer.

## Components

| File | Role |
|---|---|
| `setup-realms.sh` | Builds both realms: enterprise IdP (issuer) + vendor Resource AS (consumer) |
| `mcp_server.py` | MCP server as OAuth 2.1 protected resource. MCP SDK 2.0 emits the PRM + 401 challenge; the `TokenVerifier` enforces signature, audience, and scope |
| `ema_client.py` | MCP client. Discovers everything from the MCP URL alone, runs both legs, opens an MCP session, calls tools |
| `negative-tests.sh` | The security properties EMA is supposed to provide |
| `run.sh` | Orchestrates all of it |

## Paths exercised

```bash
uv run python ema_client.py                                      # allowed, read-only
uv run python ema_client.py --scope "findings.read findings.write"  # allowed, read+write
uv run python ema_client.py --scope findings.admin               # DENIED at the IdP
uv run python ema_client.py --audience https://unapproved.example # DENIED at the IdP
```

Both denials happen at the enterprise IdP. The vendor is never contacted — that is the whole
point of EMA: the customer's admin, not the SaaS vendor, is the policy decision point.

Scope enforcement is visible at the resource too: with `findings.read` only,
`suppress_finding()` fails with `insufficient_scope` while `list_findings()` succeeds.

### Security negatives (all must fail — `negative-tests.sh`)

1. No token → 401 carrying `resource_metadata`
2. The ID-JAG used as a bearer token at the MCP server → rejected (it is a grant, not a token)
3. The raw enterprise ID token used at the MCP server → rejected
4. The same ID-JAG redeemed twice → `Token reuse detected`
5. A token from the same AS but audience-bound to a different resource → rejected (confused deputy)
6. An unapproved client/AS pair → no assertion is ever minted

## Where admin policy actually lives

Two client attributes in the `enterprise` realm carry the policy. Their enforcement points
differ, and the difference matters if you are going to present this:

```
idjag.permitted.scopes.at.<vendor-stub>  -> scope ceiling, enforced at LEG 1 (the IdP)
idjag.clientid.at.<vendor-stub>          -> client↔AS pairing, enforced at LEG 2 (the vendor)
```

**Scope ceiling** — measured behaviour with the ceiling set to `findings.read` only:

| requested | result |
|---|---|
| `findings.read` | granted `findings.read` |
| `findings.write` | **denied** `invalid_scope` |
| `findings.read findings.write` | granted `findings.read` — silently narrowed |

Note the third row: a mixed request is trimmed to the permitted subset rather than refused.
Clients must read the returned `scope`, not assume they got what they asked for.

**Pairing** — clearing `idjag.clientid.at.*` does **not** stop the IdP from minting. The
assertion is still issued, but with no `client_id` claim, and the vendor rejects it at leg 2:

```
invalid_grant: client id in assertion : null and client id in request header/body : mcp-client
```

So revocation works, but it is caught at the vendor rather than refused at the IdP. Only the
unapproved-audience case (`--audience https://unapproved.example`) is refused at leg 1 with
the vendor never contacted. Do not overclaim "the vendor is never contacted" as a blanket
property — it holds for an unknown AS, not for a de-authorized client.

## Honest gaps — know these before you present

**1. Keycloak cannot issue ID-JAG in any released version.** Upstream implements only the
receiving side. Verified directly against `quay.io/keycloak/keycloak:nightly`:

```
requested_token_type=urn:ietf:params:oauth:token-type:id-jag
-> {"error":"invalid_request","error_description":"requested_token_type unsupported"}
```

This demo therefore runs `ceposta/keycloak:id-jag`. Its provenance is not a mystery — the
image labels state it exactly:

```
org.opencontainers.image.description = Keycloak main + PR #49998 with the identity-assertion-jwt feature
org.opencontainers.image.source      = https://github.com/keycloak/keycloak/pull/49998
org.opencontainers.image.revision    = 0ae96b6e89e065fa361df46662738a1efb9ac822
```

So this is **real upstream Keycloak code under active review**, not a mock or a fork:
keycloak/keycloak#49998, "Customize token exchange endpoint to issue ID-JAG", by bucchi
(Hitachi), adding an `IDJWTTokenExchangeProvider` and a `TokenCategory.IDJAG`. Open against
`main`, reviewed by several Keycloak maintainers, still iterating as of August 2026.

Related tracking: #43971 (umbrella, milestone 26.8.0), #48818 (issuer side, no milestone),
#49003 (promotion to preview, 3/63 subtasks).

Pin the digest so a demo can't shift under you:

```bash
KC_IMAGE=ceposta/keycloak@sha256:5d945dc3e04fa616eae7ad883f158f32951503f465dfedd0ab866e0a38bb8934 ./run.sh
```

It is still a third-party image — fine for a demo, not for anything else. To build it
yourself, compile Keycloak with PR #49998 applied and use `docker/` in the agentgateway
example. Swap in an official image via `KC_IMAGE=...` once upstream ships issuance.

**Apple Silicon note:** the image is `linux/amd64` only, so it runs under emulation on an M-series
Mac. Keycloak startup goes from ~12s native to ~50s. `run.sh` waits for readiness, but budget
for it on demo day, or pre-warm the stack with `./run.sh up` before you present.

**2. The AS does not advertise EMA.** Keycloak's metadata omits
`authorization_grant_profiles_supported: ["urn:ietf:params:oauth:grant-profile:id-jag"]`.
The client prints a warning and proceeds on out-of-band knowledge. A spec-strict client would
fall back to the browser flow here, so this is the single field most worth watching upstream.

**3. Users must be pre-provisioned at the vendor.** Keycloak resolves the ID-JAG `sub`
through a federated identity link, so every user needs a local account **before** EMA works
for them. `setup-realms.sh` does this for alice and bob. Real zero-touch rollout needs
JIT provisioning, which Keycloak-as-Resource-AS does not do here.

**4. Login is a password grant, not a browser SSO.** A stand-in for the OIDC
`authorization_code` leg so the demo runs unattended. The EMA-specific mechanics — both legs,
every claim, every check — are real.

**5. The ID-JAG carries no `resource` claim.** The client sends `resource`, but this Keycloak
build resolves the target from `audience` alone. The spec makes `resource` conditional, and
audience-restriction is instead enforced by an explicit audience mapper on the vendor client.

## Rebuilding just the realms

```bash
./setup-realms.sh    # idempotent; deletes and recreates both realms
```

Keycloak admin console: http://localhost:8480 (admin/admin).
