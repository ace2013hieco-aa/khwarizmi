# OPS-5Z triage — what the three audits found, and what happens to each

Three adversarial audits ran on `b832ebd`. This is every finding, with a decision. The decisions are
**fixed**, **fix now**, **document**, or **defer**, and the difference between the last two is whether the
behaviour is wrong or merely costly.

The rule for **fix now**: a *false pass* — a wrong answer reported as correct. A false refusal is a cost, and a
cost can be documented; a false pass cannot be, because nothing downstream will notice it.

## Fixed before this slice

| finding | audit | commit |
|---|---|---|
| `contradiction_scan` silently dropped the 13th claim | N-A | `555dcd1` |
| A refused tool call bought a tick | O-1 | `555dcd1` |
| The date rule accepted *any* claim date — the incident reopened with a parenthetical | O-2 | `555dcd1` |
| §13 described a date rule that no longer existed | O-5 | `555dcd1` |
| Two text models at different seams | P | `810e829` |
| `check_claim` had no production caller | P | `810e829` |
| A date-first sentence bound the figure to *September* | N-C | `4a1f2c1` |
| A newline or pipe table bound a row's figure to the previous row | N-B | `4a1f2c1` |
| `"India's"` and `"India"` were different entities | N-E | `4a1f2c1` |
| A swap on one date produced no conflict (cascaded from the entity fix) | N-D | `4a1f2c1` |

The last four were one root cause: the entity was the *first* capitalised token of the phrase, months are
capitalised, a window ending at a clause break had an empty last part, and `|` did not end a clause.

## Fixed by this slice — seven of the eight false passes, and the eighth by Group E below

Seven rows were false passes: a wrong answer reported as correct. Each is closed by a falsifier; the new
rules add a positive case, a near miss they must not fire on, and a red proof that stubs the rule out.
The eighth, E1, is reclassified below: its semantics are decided, but its mechanism is a design gate.

| finding | audit | what the payload now does | proof |
|---|---|---|---|
| An ordering conflict with no per-entity figures — *"Brazil was ahead of India"* vs *"India led Brazil by 300,000"* | N-D | `ORDER` from two assertions on the same named pair and scope | `test_an_ordering_conflict_with_no_per_entity_figures_is_reported` |
| *"Brazil was ahead of India"* vs *"Brazil was not ahead of India"* | N-D | A claim and its negation are opposite state sets; `ORDER` | `test_a_claim_and_its_negation_is_reported` |
| The same figure on two entities with different formatting (*"5.275035 million"*) | N-D | `ATTRIBUTION` compares the canonical quantity, not the spelling | `test_a_decimal_magnitude_is_the_same_quantity_as_grouped_digits` |
| 17 mutually conflicting claims return 16 of 136 conflicts | N-H | 17 claims are refused by the input cap (already fixed); a 12-claim scan reports `conflicts_total` and `truncated`, and the note says "showing 16 of 66" | `test_the_conflict_cap_reports_the_total_it_did_not_return` |
| 70 figures return 64 with `truncated: false` | N-H | `truncated: true`, `figures_truncated: true`, `window_truncated: false`, note names the cap | `test_seventy_figures_set_the_truncation_flag` |
| Crossref `date-parts` / `is-referenced-by-count`, the OpenAlex search wrapper, and PubMed XML are mined as content | N-F | Crossref records, `results`/`items` wrappers and PubMed XML are read field-wise; unmodelled shapes are unreadable | `test_a_crossref_record_is_read_field_wise_not_mined`, `test_the_real_openalex_work_inside_a_search_wrapper_is_not_metadata`, `test_pubmed_xml_is_read_field_wise_not_tag_stripped` |
| The first C fix still left `semantic_text` a string and `raw.decode` as the fallback, so a caller could mine any unmodelled serialization; the format was still inferred from the bytes | N-F, second pass | typed states (`content`/`fallback`/`unreadable`), declared-format dispatch, format carried on the artifact; `facts_in` mines only `content` | `test_ops5z_group_c_content_states.py` (four shapes + control + red proofs; details in §C below) |
| A record carrying both `abstract` and `abstract_inverted_index` appends both | N-F | the plain abstract wins; the index is a reconstruction of the same field | `test_a_record_that_carries_both_abstracts_states_it_once` |

## Fixed by Group E — the eighth false pass

| finding | audit | what the payload now does | proof |
|---|---|---|---|
| A reported `CONFLICT` has no consequence: a critic that proposes nothing after one ends `SUCCEEDED` | P | A conflict can open one bounded verification round: the critic proposes `REQUEST_ADDITIONAL_EXPERIMENT`, the gateway records the conflict with the round, the spine fetches the primary and records RESOLVED / DISPUTED / REFUSED | `tests/test_ops5z_group_e_verification_round.py` |

The earlier decision — **record, never force** — stands: a conflict does not force a proposal, and the
critic is still the one that decides to ask. What changed is that the ask now has a mechanism. The design
gate's fear was a capability-plane shape change (`ToolResult`/`Observation` gaining `findings`); the repair
does not touch that surface. The finding travels in the *proposal* the model authors, which was always the
critic's channel, and the spine's response is a new intent + journal event, not a new capability field.

## How each decision was made

### A1/A2 — keep the bound, report the cut

Both caps stay at 16 and 64. Removing them would let a 12-claim scan produce
`O(claims² × figures²)` conflicts — hundreds of thousands — in one observation, and refusing a legitimate
multi-conflict scan would be a false refusal. The honest middle is the one the merge rule asks for: the
payload reports `conflicts_total`/`truncated` (conflicts) and `truncated`/`figures_truncated`/
`window_truncated` (figures), and the note names the cut. `MAX_SCAN_CLAIMS` already refuses 17 claims, so the
audit's 17-claim reproduction now stops at the input; the remaining truncation case (12 claims, 66 conflicts)
is reported rather than disguised.

### B1/B2 — an ordering rule that reads state sets, not verbs alone

`conflicts_between` now parses `X was ahead of Y`, `X led Y`, `Y trailed X`, `X was behind Y` (plus the
enumerated variants below), binds each assertion to a date scope, and compares the **sets of pair states**
each assertion permits: ahead / behind / equal. Two assertions on the same named pair and scope conflict
only when their sets are disjoint. That covers `ahead` vs `behind`, `ahead` vs `not ahead`, and `led` vs
`did not lead`, while `not ahead` vs `not behind` (both consistent with equality) is silent. Only
assertions from different claims are compared, so one sentence cannot contradict itself.

**Near misses pinned, not merely hoped for:** different months, different dates, a bare month against a
dated claim, the same ordering stated twice, both negated relations, and the audit's own sentence
*"Brazil was ahead of India in September but behind in October"* (verbatim) — all produce no conflict.
The real-sentence test uses a line-wrapped `India overtook\nBrazil on 7 September…` from
`docs/OPS-5Z-DESIGN.md`, a shape the rule was not designed around.

**Named limits:** contractions (`wasn't`), perfect constructions (`has not been`), passive and nominal
forms (`the lead of X over Y`, `X's lead`), pre-sentence negations other than `not the case that`, and
ordering by a dimension the sentence does not name (queue, development, alphabet) are not read; a sentence
that says "ahead of" about the queue and another about cases will conflict, and two undated claims about
different contexts (a model vs the data) are compared as one scope. These are misses/ambiguities, not
silent agreements.

### B3 — the normaliser was already canonical; the comparison was not

`5.275035 million` already canonicalises to `5275035.0`. The attribution rule compared `literal` strings, so
the two spellings never met. It now compares `canonical` with a dimension guard (`%` and `pp` are dimensions;
`million`/`billion` are scales already folded into the canonical value). The detail names the shared
quantity and both spellings, so a reader sees why.

### C1–C3 — model the shapes that are supported; do not strip what is not

`read_content` now models:

- **Crossref** — a `message` record (`title` may be a list, `abstract` may be JATS);
- **record wrappers** — `results` (OpenAlex and others) and `items` / `message.items` (Crossref), whose
  members are read with the same field selector;
- **PubMed XML** — `ArticleTitle` and `AbstractText` only; the PMID, journal and publication date are
  metadata, not prose.

Everything else that is JSON stays unreadable at that pass (the second pass
distinguishes a *declared* bad shape, unreadable, from an *undeclared* blob,
fallback), and an XML document that is not PubMed is unreadable rather than
tag-stripped. The wrapper and Crossref cases use `date-parts`,
`is-referenced-by-count` and `cited_by_count` as *metadata* in the tests, proving they do not become facts.
The real 33,727-byte OpenAlex record inside a wrapper yields zero figures and zero dates.

**Second pass (see §C below).** The first pass still inferred the shape from the bytes and still let any
caller mine a `raw.decode` fallback through `semantic_text`. The second pass replaces that with a typed
three-state read, adapter-declared formats carried on the artifact, and `facts_in` refusing everything but
`content`. The four shapes now have falsifiers with red proofs in
`tests/test_ops5z_group_c_content_states.py`.

### C, second pass — the shape is declared, and a read is a state

The first C pass closed the field selection but left two doors open, and the
prompt for this slice names both. `semantic_text` still returned a plain
`str`, so any caller could feed `raw.decode` output to `facts_in` as though it
were prose; and the reader still inferred the shape from the bytes
(`abstract_inverted_index`, a `message` key, a `results` list), which is
knowledge the fetch path already had and which fails for every shape nobody
thought to add.

**1. A typed result.** `semantic_text(raw, format=…)` now returns
`ContentRead`: `(text, state, format, fields, detail)`, with `state` one of
`content` / `fallback` / `unreadable`. The envelope's `read` field and the
`evidence_inspect` payload carry that vocabulary (`"read": "content"`), not a
boolean. `facts_in` accepts the typed read and extracts only from `content`;
`fallback` and `unreadable` return an empty `Inspection` whose `not_mined`
names the state and reason. An empty fact list can no longer mean "the source
states nothing" when the reader could not read it.

The three states are decided by what the carrier declared:

| carrier | bytes | state |
|---|---|---|
| declared format with an extractor | the shape it promises | `content` (even partially — a title without a reconstructable abstract is content + `detail`) |
| declared format with an extractor | not that shape / malformed | `unreadable` |
| declared format with **no** extractor | anything | `unreadable` (supported at fetch, unsupported at read) |
| no declared format | plain text | `content` |
| no declared format | JSON or markup | `fallback` (legible; never mined) |
| any | not UTF-8 | `unreadable` |

An undeclared serialization is a fallback rather than unreadable because the
carrier cannot name its shape; a *declared* format that fails is unreadable
because the provider promised a shape the reader models. That is why the
Crossref falsifier is "content or unreadable, never fallback": Crossref is a
declared format, and a bad one is an anomaly, not a blob.

**2. The format is declared by the adapter and carried on the artifact.**
`ProviderAdapter.fetch_content_format(media_type)` declares the shape from the
response's media type (a fact the transport carries), never from the body:
OpenAlex and Crossref declare their record formats for JSON, PubMed declares
XML, HTML and plain text are common formats, and a provider with no read
extractor declares nothing. `SourceArtifact.content_format` travels with the
bytes into both fetch writers (`source_fetch` metadata and the task-side
`_prepare_fetch` metadata, with the provider id beside it for attribution).
Every reader that mines or grounds — `evidence_inspect`,
`statistic_check`, the controller's quote/span seams, the methodology claim
gate, the evidence envelope — dispatches on the carried token. The provider id
is deliberately **not** used as a fallback format: a provider can serve more
than one shape, and a name is not a declaration.

**3. The extractors.** The field extraction remains one implementation in
`hermes.tools.capabilities.content` (see the Document table below for why it
is not physically in each adapter); the adapter owns the *declaration* and the
reader dispatches on it. OpenAlex
unwraps `results[0]`/`data[0]`/`items[0]` and reads title/display_name/abstract
(inverted index reconstructed); Crossref reads `message.title` and
`message.abstract`, or `message.items[0]`; PubMed reads `ArticleTitle` and
`AbstractText`.

**4. The falsifiers** (all in `tests/test_ops5z_group_c_content_states.py`;
each has a red proof that stubs the extractor to the old `raw.decode`):

| shape | before (raw fallback mined) | after |
|---|---|---|
| Crossref | `34` from `is-referenced-by-count` and `18` from `date-parts` are figures | `content`; only `1,200`, bound to `Hubei`; metadata absent from the text |
| OpenAlex wrapper (real 33,727-byte work inside) | wrapper `per_page: 25` and the work's `cited_by_count: 34` are figures; `publication_date` is a date | `content`; `results[0]` unwrapped; the prose figure binds to `Hubei`; no metadata facts |
| PubMed XML | PMID `32456789`, XML version `1.0` and journal day `23` are figures; `1,200` binds to a tag/title token | `content`; title and abstract only; `1,200` binds to `cases`; the PMID/journal date are absent |
| Unknown shape | `34` and `2020-09-27` mined | declared: `unreadable`; undeclared: `fallback`; both yield no facts and a `not_mined` reason |
| **Control**: the real work | — | `content`, 1,260 characters (see the note below), and the verbatim abstract sentence is `grounded` |

The control's reported length is **1,260**, not the 1,379 the prompt names:
1,379 counts the identical `title` and `display_name` twice. The D1 fix in
`c7ff016` states the repeated part once, so the same title + abstract is 1,260.
Regressing D1 to reach the older number would re-state the title twice; the
control instead pins the full content and the grounded quotation.

### D1 — one field, one statement

When `abstract` is present, `abstract_inverted_index` is the same field in another encoding and is not
appended. A repeated title/display-name part is also emitted once. The test asserts the abstract's `1,200`
and its date each appear once.

### E1 — wired: one bounded verification round

**Decision (unchanged): record, never force. Mechanism (this slice): the critic can open one round of
investigation; the spine decides and records its outcome.** A conflict is a report, not a verdict — the
scan does not rank the claims — so nothing here makes a conflict force a proposal. What it does is give the
critic a way to ask the question the incident's critic asked and the runtime refused `NOT_WIRED`: *fetch the
primary source for this disputed figure*.

**The intent.** `REQUEST_ADDITIONAL_EXPERIMENT` is now a wired LLM-proposable kind with a closed payload:
the two claims (ref, statement, source each rests on), the `contradiction_scan` conflict object (kind,
left, right, subject, date, detail), the mode, and the fetch target(s). The gateway parses the payload with
the same module the executor uses (`hermes.research.verification`), so the contract and the execution cannot
disagree.

**The mode is derived by the spine, not chosen by the critic.** Different sources (or one side naming none)
→ `verify-one`: one targeted fetch of the primary source, both sides checked against that artifact. The
same non-empty source on both sides and still disagreeing → `parallel-two`: two branches, one per side, each
with its own target; both branches are recorded. The critic declares the mode; the gateway recomputes it
from the claims' own `source_ref`s and refuses a declaration that contradicts them.

**The bound is one round per claim.** The round identity is content-derived from the claim refs and the
disputed question (kind/subject/date); a replay of the same round is `DUPLICATE`, and any request naming a
claim that already had a round is refused `BUDGET` — *one round, then escalate; a persistent conflict is
DISPUTED, never a second fetch*. The round's fetch is the capability plane's `source_fetch` under the
RESEARCHER grant: egress allowlist, provider consistency, and the content gate included. The critic never
gains the egress capability; the spine executes the round.

**The outcome is recorded, three ways.** `RESOLVED` (one side's figures are established by the fetched
artifact — the record names the winner and the artifact), `DISPUTED` (neither side is, or both are), or
`REFUSED` (the round could not run; the code names why — a challenge page, no grant, no source). The round's
OPENED event carries the conflict that caused it; the COMPLETED event carries the status, winner, evidence
and per-branch records. The methodology stage record carries a `VerificationRecord` on the stage that
proposed the round and on the CLAIM it examined, so a disputed claim is caveated where the claim is.

**The incident's mode, read from its claims.** The audit's p10 conflict (`AUDIT-INTEGRATION` §4.4) is
`ORDER`: claim[1] transcribes the fetched 18 September snapshot (India 5,275,035 / Brazil 4,467,433) and
claim[3] is the qualitative *"Brazil was ahead of India"*. They do **not** share a source — the figures come
from the fetched artifact, the ordering names none — so the incident is `verify-one`: one targeted fetch of
the primary (the 1 September source) is the cost its critic asked for. `parallel-two` is for two claims
that cite the same artifact and still disagree; the falsifier pins that branch with two claims that share
an `evidence:` ref.

**What the falsifiers show** (`tests/test_ops5z_group_e_verification_round.py`; the chain is the real
driver/runtime/gateway/capability supply/artifact store):

| # | falsifier | evidence |
|---|---|---|
| 1 | a conflict opens a round | the real `contradiction_scan` returns `1 conflict(s); ORDER`; the OPENED event names the conflict; the COMPLETED record says RESOLVED / claim[1]; the CLAIM stage carries it |
| 2 | no conflict, no round | agreeing statements; no round event; the stage ends as today without a `VerificationRecord` |
| 3 | the round is bounded | a primary that contradicts the claim → DISPUTED, the chain completes (not LOOP/TICK_LIMIT), the claim carries the caveat; a second request for either claim is `BUDGET` |
| 4 | verify-one fetches the primary through the gate | the real 5,590-byte cookie wall is refused `NON_CONTENT_PAYLOAD`; no citable artifact is written; the round records REFUSED |
| 5 | parallel-two | two targets, two branches, both recorded, one winner |
| 6 | the journal shows why | the OPENED payload's conflict is the scan's conflict (kind and detail) |
| red | today's behaviour | stubbing the applier to refuse `NOT_WIRED` opens nothing; the same falsifier assertion fails |

**What it does not do.** It does not implement `REQUEST_REPLICATION` or `PROPOSE_GATE_OVERRIDE` (the other
audit's subject). It does not let the critic decide which side is right: the adjudication is `check_claim`
over the fetched content and the statements, and a side with no checkable figure never "wins" — a
qualitative ordering is not established by a figure snapshot, so the round says DISPUTED rather than
inventing a verdict. It does not widen the egress allowlist; a WHO URL the allowlist does not carry is
REFUSED with the capability's own code, which is a cost the operator can see. And it does not re-run the
critic after the round: the round is the investigation; a later conflict for the same claim is the bound's
DISPUTED, not another model pass.

**One fence is recorded, not added.** The round's evidence is checked for the IDR-046 web-derived bar, but
not for N9 retraction: the retraction predicate's call-site census is frozen at exactly four (AGENTS.md; N9
cert `02cb976`), so a fifth call in this validator needs a design gate plus the N9 slice re-run. The new
resolve site is recorded as a **frozen gap** in `tests/test_n9_resolve_path_pin.py` with that reason. Until
the gate lands, a round could in principle cite a retracted fetched payload; that is a disclosed gap, not a
silent one.

## False-positive measurement — the ordering rule on real prose

Corpus: every first-party Markdown document in the repository (496 files: `docs/`, `reports/`,
`obsidian-vault/`, `audits/`, `references/`, root `*.md`), split into 7,239 paragraphs and 28,728
sentences, plus the real OpenAlex abstract (5 sentences). Excluded: vendored packages, worktrees, this
measurement's own scratch files, and this report itself (so the rule is not measured against its own
examples).

| quantity | count |
|---|---|
| sentences containing an ordering word | 259 |
| ordering assertions extracted (capitalised pair + enumerated relation) | 4 |
| assertion pairs with the same named pair | 3 |
| pairs with the same scope (the rule actually compared) | 3 |
| **legitimate pairs called a conflict** | **0** |

The four extracted assertions are three occurrences of "the CLIs behind the Tool Runtime" in design prose
(compatible with each other, and not entity orderings) and one real India/Brazil sentence. The three
same-pair comparisons were all compatible; no false conflict was produced. This measures precision only:
the corpus contains no actual ordering contradiction, so it says nothing about recall. The suite's
near-miss tests are the adversarial half (five compatible pairs plus the one-sentence self-check; 0
conflicts), and the B1/B2 cases are the positive half.

## Document — false refusals and costs

| finding | audit | note |
|---|---|---|
| Marker threshold: an 831-character article about CAPTCHAs is refused; a 1,417-character consent wall is admitted | O-3 | The threshold is the switch, by construction. The real wall is 136 readable characters |
| `"10% of 2 million is 200,000"` is INCONSISTENT; `bn`/`lakh`/`crore` are dropped | N-G | Unit conversion is declared but absent on the percent and change paths |
| `"2-type"` is refused where the source says `"two-type"` | agent | Number words are not parsed |
| Month-granularity dates: `2020-09` and `2020-09-18` compare equal | N-E | A month is not a day |
| A three-row table binds a row's last cell to the *next* row's date | O-2 | Character distance has no concept of a row |
| A header more than 400 characters above its row yields `DATE_MISMATCH … none` — should be `undated_source` | O-2 | A caveat, not a refusal |
| `"May 5"` in prose is read as 5 May | O-2 | Bare month-day parsing invents dates |
| An unreadable abstract is now marked (`read`), but the loss is still not a verdict | O-4 | `810e829` made it visible; the second C pass makes a partial read a `content` state plus `detail`, and the claim gate caveats it |
| Extraction code lives in `hermes.tools.capabilities.content`, not physically in each adapter | this slice | The runtime may import only capabilities; a capabilities→providers import would pull the provider plane into the agent runtime. The adapter owns the *declaration* (`fetch_content_format`); the one implementation is shared, so the model and the falsifier cannot disagree |
| An artifact whose carrier recorded no `content_format` reads as a `fallback` (JSON/markup) and is not mined | this slice | The honest cost of "carried, not inferred": a direct admission (a test fixture, a corpus row written by another producer) loses extraction until its producer declares the format. The blob is still shown (labelled), never mined |
| `semantic_text` returns a typed `ContentRead`, not a `str` | this slice | Every in-tree caller was updated; an out-of-tree caller expecting a string reads `.text`. The typed pair is what lets `facts_in` refuse a fallback instead of mining it |
| PubMed's shipped search URL serves HTML; the PubMed XML extractor sees XML only when the response *is* XML | this slice | The declaration follows the response's media type, so `eutils` XML is field-wise and the HTML page is HTML. Both are supported; neither is tag-stripped as a PubMed record |
| A provider id is not accepted as a format declaration | this slice | A provider can serve a record, a search envelope or an HTML page; treating its name as a format would be the same inference the slice removes. The reader uses `content_format` only |
| The verification round's evidence is not N9-retraction-fenced | this slice | The retraction predicate's call-site census is FROZEN at four (AGENTS.md; N9 cert `02cb976`); a fifth call needs the owning gate re-run. The new resolve site is recorded as a frozen gap in `tests/test_n9_resolve_path_pin.py`. The IDR-046 web-derived bar IS applied. A round could cite a retracted fetched payload until the gate lands |
| A WHO URL the egress allowlist does not carry is refused | this slice | The round fetches through `source_fetch`; the allowlist (OpenAlex/PubMed) is code-owned and widening it is a separate decision. The round records REFUSED with the capability's own code |
| A resumed CRITIQUE stage may re-fetch once | this slice | A duplicate round proposal still executes (the driver cannot read the journal); the gateway refuses a second round and a second terminal record, so it cannot loop. The extra fetch is the crash-retry cost |
| Ordering contractions / perfect tense / nominal forms (`wasn't ahead`, `has not been ahead`, `X's lead`) are not parsed | this slice | Misses, not false passes; named in §B1/B2 above |
| An ordering about a different dimension (queue, development) can conflict with one about cases | this slice | The rule has no metric model; the same-pair/scope key is the only guard |
| A PubMed XML document that uses an undefined named entity fails `ElementTree` parse and is reported unreadable | this slice | A caveat on a supported source, not metadata-as-content |

## Defer — structural, no behaviour change today

| finding | audit | why deferred |
|---|---|---|
| Grants are unioned per `agent_profile`; an egress-only profile sharing `ADVERSARY` widens the grant | N-I | Latent — masked by the runtime's `spec.tools` check. Needs a design decision, not a patch |
| The corpus writer is a second `source_payload` producer and never passes the content gate | P | Three live artifacts are already walls admitted before the gate existed |
| Cross-project hash dedup answers differently per door | P | Needs a scoping decision |
| `TOOL_OBSERVED` records a digest, not the invocation envelope | P | Auditability gap; the fix is a journal schema change |
| Standalone `workflows.run_methodology` remains ungated | agent | Only the live composition calls the gate |
| `subjects` is caller-declared, so a model-authored quantitative claim without operator subjects is refused | agent | Deriving them needs a model, which the gate forbids |
| Three tests are tautological under a generic stub | N-K | Test quality; the red proofs are genuine |

## What "settled" means for merging

The slice may merge when **every row in "fix now" is fixed or reclassified with a reason**. The "document" and
"defer" rows do not block: they are costs and structural gaps, and a repository that waits for those never
merges anything.

By that rule this slice is **mergeable**: seven of the eight false passes are closed by a rule with a red
proof, and the eighth (E1) is closed by Group E — a bounded verification round wired as an intent, with the
journal as its terminal record and a red proof that today's `NOT_WIRED` behaviour opens nothing. The two
decisions that were not patches (the caps and E1) are argued above rather than implemented by reflex.
