# MERGE-AUDIT-USERINFO — independent merge audit of `merge/userinfo` @ `238d6e2`

**Task ID:** MERGE-USERINFO (audit half)
**Auditor stance:** merge integrator re-deriving — every closure below was
re-executed at the merged tip, not quoted from commit messages.
**Base:** `main` @ `d10687499864db6fa85d282cbe19ebe4beb5eb37`
**Merged tip:** `238d6e2` (`merge/userinfo` = FF `d106874..238d6e2`, hashes preserved)
**Prior audit:** `AUDIT-USERINFO-REDTEAM.md` @ `cdffe25` — PASS, 0 MUST-FIX,
3 SHOULD-FIX (SF-1/2/3). This document re-proves each SHOULD-FIX is closed.
**Environment:** isolated worktree `D:\New folder\merge-userinfo-wt`,
project venv CPython 3.14.1, `PYTHONPATH=<worktree>/src`. All probes offline
(hermetic injected resolvers; no socket ever opened — resolution answers are
canned strings, never dialed). Localhost-probes-only constraint respected:
zero real egress from audit probes.

## A. SF-1 CLOSED — the pin covers the accepted `:443` spelling

**Pin:** `src/hermes/tools/providers/http.py:242` (`_pin_key`), fold rule
`:268-272` (`name:port` → `name` iff `int(port) == 443`); rationale block
`:257-266` (FIX-PIN-PORT). Rule-layer counterpart:
`src/hermes/security/egress.py:149-152` (`_canonical_origin` folds the https
default the same way), so gate and pin agree by construction.

**Re-proof (pasted, merged tip):**

```
_pin_key('api.openalex.org')       -> 'api.openalex.org'
_pin_key('api.openalex.org:443')   -> 'api.openalex.org'
_pin_key('api.openalex.org:0443')  -> 'api.openalex.org'
_pin_key('API.OPENALEX.ORG')       -> 'api.openalex.org'
_pin_key('api.openalex.org.')      -> 'api.openalex.org'
_pin_key('api.openalex.org:8443')  -> 'api.openalex.org:8443'   (non-default kept)
```

Wire probe through the real `EgressPolicy.vet` + real pin table + urllib's own
`Request.host` spelling (the exact lookup the dialer performs):

```
VET-OK https://api.openalex.org/works      -> pinned 93.184.216.34
  req.host='api.openalex.org'       lookup='93.184.216.34' HIT
VET-OK https://api.openalex.org:443/works  -> pinned 93.184.216.34
  req.host='api.openalex.org:443'   lookup='93.184.216.34' HIT
VET-OK https://api.openalex.org:0443/works -> pinned 93.184.216.34
  req.host='api.openalex.org:0443'  lookup='93.184.216.34' HIT
SF1-NEGATIVE: https://api.openalex.org:8443/works refused ORIGIN_NOT_ALLOWLISTED
```

The audit's failing row (`:443` dialed by NAME — second resolution) now dials
the vetted address. No accepted spelling is left unpinned; no spelling was made
unacceptable (`:443` remains a legitimate fetch). **SF-1 CLOSED.**

## B. SF-2 CLOSED — the full resolver exception family is typed

**Pin:** `src/hermes/security/egress.py:250-266` — `except Exception` around the
injected `resolve(host, port)` call, re-raised as `EgressRefused DNS_FAILURE`
with the class name kept in the detail (`resolution failed (<ClassName>)`).
Comment header names the finding (`AUDIT-USERINFO SF-2`) and enumerates the
family: OSError / socket.gaierror, ValueError, RuntimeError (+NotImplementedError),
KeyError, TypeError, resolver-defined classes.

**Re-proof (pasted, merged tip — one row per escaping class):**

```
OSError  : refused DNS_FAILURE | detail= resolution failed (OSError)
ValueError : refused DNS_FAILURE | detail= resolution failed (ValueError)
RuntimeError : refused DNS_FAILURE | detail= resolution failed (RuntimeError)
KeyError : refused DNS_FAILURE | detail= resolution failed (KeyError)
TypeError : refused DNS_FAILURE | detail= resolution failed (TypeError)
Custom (resolver-defined) : refused DNS_FAILURE | detail= resolution failed (CustomResolverError)
```

Zero bare escapes. Refusals are data with a code on every path, restoring the
base gate's contract the narrowing had broken. **SF-2 CLOSED.**

## C. SF-3 CLOSED — the userinfo narrative is corrected

**Pins:**
- `src/hermes/research/live_fetch.py:22-33` (module docstring) — states the
  audited userinfo URL "never reached a dial — the shipped transport's own
  parser refuses it pre-connect (`InvalidURL`); the LIVE row is the non-default
  port, where base dialed `api.openalex.org:8443`".
- `src/hermes/research/live_fetch.py:98-117` (gate docstring) — same measured
  correction inline at the FIX-USERINFO rule statement.
- `src/hermes/tools/providers/http.py:246-255` (`_pin_key` docstring) — same
  correction at the pin rationale.

**Re-proof (pasted):** string probes confirm `InvalidURL` + `LIVE row is the
non-default port` + `never reached a dial` present in `live_fetch.py`, and
`never reached a dial … refuses it pre-connect; the LIVE row was the
non-default port` + `FIX-PIN-PORT` present in `http.py`. The head paste:

```
FIX-USERINFO: hosts are read the way ``urlsplit`` reads them
(``parts.hostname``), never by slicing ``netloc`` — the audited bypass read
``api.openalex.org`` (the userinfo prefix) as the host of
``https://api.openalex.org:foo@evil.example/works``, whose actual host is
``evil.example``: the allowlist verdict and the FIX-D pin were keyed on a
name that is not the URL's host. Measured on the base gate, that URL never
reached a dial — the shipped transport's own parser refuses it pre-connect
(``InvalidURL``); the LIVE row is the non-default port, where base dialed
``api.openalex.org:8443`` — outside the vetted origin — with the pin keyed
on the bare host. ...
```

No sentence in tree still claims the userinfo URL dialed the attacker's host.
**SF-3 CLOSED.**

## D. Bypass baseline re-confirmed (no regression at merged tip)

```
BYPASS: refused 'https://api.openalex.org:foo@evil.example/works' CREDENTIALS_IN_URL
BYPASS: refused 'https://user:pass@api.openalex.org/works' CREDENTIALS_IN_URL
BYPASS: refused 'https://api.openalex.org@evil.example/works' CREDENTIALS_IN_URL
```

Refusal happens before any resolution (resolver untouched) — the FIX-USERINFO
gate holds under the two later commits.

## E. Gates (raw, pasted with counts — merged tip `238d6e2`)

```
$ python -m pytest tests -q            # project venv 3.14.1, PYTHONPATH=<worktree>/src
4365 passed, 0 failed, 0 errors, 0 skipped in 530.45s   (JUnit XML: tests=4365 failures=0 errors=0 skipped=0)
PYTEST_EXIT=0

$ python -m pytest tests/test_fix_userinfo.py tests/test_p_auto_3_live_fetch.py tests/test_p_auto_4_caps.py tests/test_p_auto_4_fix.py
113 passed in 9.06s

$ python -m ruff check src tests
All checks passed!
RUFF_EXIT=0

$ pyright --pythonpath <abs venv python> src
0 errors, 0 warnings, 0 informations
PYRIGHT_SRC_EXIT=0

$ pyright --pythonpath <abs venv python> --project pyrightconfig.tests.json
0 errors, 1 warning, 0 informations     # tests/test_research_program.py:144 reportSelfClsParameterName — pre-existing, off-stack
PYRIGHT_TESTS_EXIT=0
```

Count lineage: 4357 (5b7a4a5: 4341+16) → 4359 (eecf6c1: 4343+16, +2 port rows)
→ 4365 (238d6e2: 4349+16, battery 35→41) → merged tip 4365 passed / 0 skipped
(same total; the 16 conditional skips executed here because egress was
available — environmental, not a code delta).

## F. Scope discipline

- No `src/` changes on `merge/userinfo` beyond the FF'd stack: this audit's
  commits add `MERGE-LOG-USERINFO.md` and `MERGE-AUDIT-USERINFO.md` (docs only).
- No push performed or attempted (local-only). `main` untouched (still
  `d106874`; verified the merge branch only).
- No NOT-topics touched (no backtest_audit / SDA / TSE / Optimize-my-strategy).

## Verdict

**PASS** — all three SF closures re-derived at the merged tip (pastes in §A/B/C),
gates green with counts (§E), lineage clean fast-forward. `merge/userinfo` is
approved to hold at `238d6e2` + two docs commits, STOPPED BEFORE PUSH.
