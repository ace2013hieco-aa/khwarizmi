# Adversarial Audit — Hazard Evaluator, Second Gate (post-HZ remediation)

**Scope:** second-gate protest-stage attack on the **remediated** `src/hermes/tools/providers/hazards.py` + the four `hazard_specs/*.json` (HZ-01…HZ-12 folded in). Method: attack only the surfaces the remediation *introduced or rewrote* — throttle fields-scoping (HZ-01), retraction value semantics (HZ-02), the generalized `no_full_text_status` deferral (HZ-03), and the new registration rules (HZ-06/09/10/12) — for the same bypass/silent-failure classes. The first gate's findings were treated as closed only where the remediation actually closes them; every HZ2 finding below is a hole in the *remediated* mechanism, reproduced against the running code.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| HZ2-01 | **P1** | throttle fields-scoping | **The fields-scoped throttle is bypassed by BYTES payloads** — the plain-text branch searches the entire decoded body whenever the payload is not a `dict`, so the shipped `europepmc`/`pmc` throttle `fields` are dead for the realistic raw-bytes form, and a legitimate result mentioning "too many requests" is silently `THROTTLED` (probe B) |
| HZ2-02 | **P2** | throttle fields-scoping | A `fields` entry pointing at a **container** (list/dict of records) matches `str(container)` — every nested field included — so a broad spec path reopens the HZ-01 false-positive class (probe A) |
| HZ2-03 | **P2** | retraction value semantics | A `retraction_marker` pointing at a **container** matches `str(article)` — body text included — so a normal paper whose text mentions "retracted" is mislabeled `REMOVED_OR_RETRACTED` (probe C); same leaf-discipline gap applies to the presence-based `no_full_text_marker` |
| HZ2-04 | **P2** | registration | `valid_negative_statuses` admits **auth-failure statuses** (401/403) — an access-denied response is reported as "identifier resolved to a real no", the silent-failure class inverted (probe D) |
| HZ2-05 | **P3** | registration | A `"*"`-rooted path registers as **always-dead content** — `field_path: "*"` resolves nothing (the payload root is always a dict), so a typo'd spec ships a never-firing marker silently (probe E) |

## Detail

**HZ2-01 — Bytes payloads silently bypass the fields-scoped throttle. (P1)**

The HZ-01 remediation's guarantee — "a body pattern never searches dict result content; it matches only the declared error fields" — is implemented as `if isinstance(payload, dict): … else: re.search(body_pattern, text)`. The `else` branch (plain-text whole-body matching) applies to **every non-dict payload, including bytes that are JSON**. The design's own flow evaluates hazards on the **raw payload** before `parse_page` (blueprint §5.2: "transport.request → hazard evaluate on the raw payload → parse_page"), and the transport delivers bytes — so a bytes-encoded response is the realistic input form, and the shipped specs' `fields` are dead for it. Probe B, with the **shipped** `europepmc.json` (`fields: ["errMsg"]`):

```
payload = b'{"hitCount":1,"resultList":{"result":[{"title":"A study",
           "abstractText":"we discuss too many requests in APIs"}]}}'
→ THROTTLED
```

A legitimate search result mentioning "too many requests" silently throttles the whole response — the exact HZ-01 silent-loss class, reopened on the same surface the fix claimed to close, with **no spec-author error needed**. `pmc.json` (`fields: ["error"]`) and the CORE 403 case carry the same hole. **Fix: the fields-scoped rule must hold for bytes too** — decode and `json.loads` a bytes payload before field resolution (or fail closed with no match when the bytes do not parse), and a body pattern with declared `fields` must **never** fall to the whole-body branch; equivalently, state the adapter parse contract (decode to str/dict before evaluation) and make the evaluator's whole-body branch reachable only for `str` payloads.

**HZ2-02 — A container `fields` path reopens the false-throttle class. (P2)**

With a dict payload (the form the HZ-01 fixtures assume), `_throttle_matches` matches `str(value)` for every resolved field value. If a spec declares a **container** field (`fields: ["resultList.result"]` — a list of record dicts), `str()` of the container includes every nested field — titles, abstracts, everything. Probe A:

```
fields: ["resultList.result"], pattern "too many requests"
payload: {"resultList": {"result": [{"title": "A study",
         "abstractText": "we discuss too many requests in APIs"}]}}
→ THROTTLED
```

The mechanism still permits the false positive the HZ-01 fix removed, as long as the spec path is broad. The shipped specs use leaf fields (`errMsg`/`error`) so nothing ships wrong today, but the "never result content" guarantee is a leaf-value discipline, not a mechanism. **Fix: match only `str`/`bytes` leaf values — skip `dict`/`list` values entirely (their repr is never a meaningful error-message match).**

**HZ2-03 — A container `retraction_marker` mislabels a normal paper. (P2)**

`_retraction_marker_hit` matches `str(value)` for every resolved value. A `retraction_marker` pointing at a container (`retraction_marker: "article"`) matches the article dict's repr — body text included. Probe C:

```
retraction_marker: "article", retraction_pattern: "retract"
payload: {"article": {"front": …, "body": {"sec": "this paper was retracted last year"}}}
→ NO_FULL_TEXT(REMOVED_OR_RETRACTED)
```

A normal paper whose text mentions "retracted" is silently reported retracted — the HZ-02 mislabel class, reopened via a broad marker path (the shipped `pmc.json` path is precise, so nothing ships wrong today). The presence-based `no_full_text_marker` has the same leaf-discipline exposure: a broad path treats any non-empty container as marker evidence. **Fix: leaf-value-only matching in `_retraction_marker_hit`, and state the leaf-path requirement for `no_full_text_marker` presence semantics.**

**HZ2-04 — Auth-failure statuses can be declared valid negatives. (P2)**

The generalized consult (`status in spec.valid_negative_statuses`) honors any 4xx-except-429 the spec declares — including 401/403. An access-denied response is then reported as "identifier resolved to a real no", the silent-failure class inverted: a task could conclude "no literature" from "we were forbidden". Probe D: `valid_negative_statuses: [403]` + search 403 → `VALID_NEGATIVE`. Registration was meant to reject incoherent declarations; auth-failure statuses are incoherent as "not found" answers. **Fix: restrict `valid_negative_statuses` registration to the not-found family (404/410/451 — not found, gone, legally unavailable) and reject 401/403/400/405/422.**

**HZ2-05 — `"*"`-rooted paths are dead content, silently accepted. (P3)**

`_validate_path` rejects whitespace and empty segments but accepts `"*"` — and a path whose first segment is `*` resolves nothing (the payload root is always a dict; the wildcard only expands list elements). Probe E: `field_path: "*"` registers and `resolve_field_path({…}, "*") == ()` forever. A typo'd spec ships a never-firing marker/field with no error. **Fix: reject paths whose first segment is `*`.**

## What survives

The HZ-01/HZ-02/HZ-03 P1 fixes hold **for the forms their fixtures exercise**: dict payloads with leaf `fields` (no false throttle), precise-path retraction with value semantics (no normal-article mislabel), and the generalized `no_full_text_status` deferral (a declared 410 → `NO_FULL_TEXT`, verified in probe F and the regression suite). The registration matrix closures (schema version, `loop_guard` cap, status ranges, path structure, marker classes, retraction-pair coherence) all hold. The reopened surfaces are **value-type discipline** (str()-matching on containers and on bytes) and two registration allowances — not structural collapse.

## Overall verdict: **MERGE WITH REMEDIATION (second round).**

**HZ2-01** is gate-blocking for the HZ-01 fix's own guarantee: the fields-scoped throttle does not survive the realistic bytes input form, so the shipped `europepmc`/`pmc` specs can still silently throttle legitimate results. **HZ2-02/03** are the same two P1 classes (false throttle, false retraction) reachable through broad spec paths — leaf-value matching closes both at the mechanism. **HZ2-04/05** are registration allowances that admit incoherent or dead content. All five fixes land in `hazards.py`'s matching helpers and registration — no redesign, no new components — and the fold-in (with regression fixtures for all five probes) is the standing condition before step 3 proceeds.

---

## Remediation disposition — **FOLDED IN (2026-08-14)**

| ID | Fix | Where it lands |
|---|---|---|
| HZ2-01 | Fields-scoped throttle matching holds for bytes: decode + parse a bytes payload to dict before field resolution (no match on unparseable bytes), and the whole-body branch is reachable only for `str` payloads (or the adapter parse contract stated + enforced) | `hazards.py` `_throttle_matches` + module docstring; fixture |
| HZ2-02 | Leaf-value-only matching in `_throttle_matches` — `dict`/`list` values are skipped, never `str()`-matched | `hazards.py` `_throttle_matches`; fixture |
| HZ2-03 | Leaf-value-only matching in `_retraction_marker_hit`; `no_full_text_marker` presence semantics require leaf paths | `hazards.py` `_retraction_marker_hit` (+ docstring); fixture |
| HZ2-04 | `valid_negative_statuses` restricted to the not-found family (404/410/451); 401/403/400/405/422 rejected | `hazards.py` registration; fixture |
| HZ2-05 | Reject `"*"`-rooted paths at registration | `hazards.py` `_validate_path`; fixture |

**Status: FOLDED IN — all five dispositions implemented in `hazards.py` with regression fixtures in `tests/test_provider_hazards.py` (76 fixtures in the file, 684 passed suite-wide, pyright 0 errors), and re-checked against the running code:**

| HZ2 | Fold-in landing | Re-check |
|---|---|---|
| HZ2-01 | **Two-part fix**: bytes are decoded + parsed ONCE at `evaluate_hazards` entry (`_payload_as_dict(payload) or payload.decode(utf-8, errors="replace")`) so every step — throttle fields, markers, required-fields drift, fetch composites — sees the JSON dict or plain text, never a bytes blob; `_throttle_matches` searches dict content only via declared `fields`, and a fields-scoped signature never falls to the whole-body branch | Legit bytes JSON with an abstract mentioning "too many requests" → `NONE`; real `errMsg` bytes → `THROTTLED`; plain-text arXiv bytes `Rate exceeded.` → `THROTTLED` (probe A re-run: all three flipped to the correct verdict) |
| HZ2-02 | Leaf-value discipline moved into `resolve_field_path`: a dict-key segment over a list now yields the key's VALUES (not the element dicts), so a trailing key segment resolves the leaf values directly and a container path never resolves to its own repr; `_throttle_matches` matches only `isinstance(value, str)` leaves | Container path `resultList.result` + abstract mentioning "rate limit" → `NONE`; leaf path `resultList.result.abstractText` → `THROTTLED` (probe B re-run) |
| HZ2-03 | `_retraction_marker_hit` matches only str leaves (unchanged) — now correct because the resolver yields the actual event-type VALUES, so a normal paper whose body mentions "retracted" → `NONE` while a real `event-type: retraction` → `NO_FULL_TEXT(REMOVED_OR_RETRACTED)` | Container marker `article` + body text "this paper was retracted" → `NONE`; `pmc.json` real retraction + withdrawal still fire (probe C re-run) |
| HZ2-04 | `_VALID_NEGATIVE_STATUSES` not-found family `{404, 410, 451}`; registration rejects 401/403/400/405/422 | `valid_negative_statuses: [403]` and `[401, 404]` → `SpecValidationError`; `[451]` registers and a 451 → `VALID_NEGATIVE` (probe D re-run) |
| HZ2-05 | `_validate_path` rejects a `"*"`-rooted first segment (the payload root is a dict); mid-path wildcards remain legal | `field_path: "*"` → `SpecValidationError`; `result.*.title` still resolves (probe E re-run) |

The fold-in also surfaced and fixed a resolver defect the leaf filter exposed (see HZ2-02): `resolve_field_path`'s list-descent previously yielded element dicts, so `pub-history.event.event-type` resolved to dict reprs — the HZ2-01 entry normalization additionally closed the bytes→required-field-drift misfire. Both are covered by the regression fixtures above. The step-2 gate is now clear for step 3.
