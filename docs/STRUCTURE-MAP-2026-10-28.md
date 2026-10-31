# Structure map — 2026-10-28

Two things were asked for: a full test of Ix against this project, and a map of the project. The first is
blocked by the sandbox; the second is below, built from the tree.

## 1. Ix could not be run here — and why

`ix` 0.9.3 and Docker 29.8 are both installed, but Ix's backend needs Docker Desktop, and Docker Desktop
needs `wsl.exe`:

```text
PROGRAM BLOCKED BY SECURITY POLICY — wsl.exe (C:\Windows\system32\wsl.exe)
This block cannot be approved or bypassed from the current command.
```

That is a hard sandbox block, not a missing install. I did not retry it or route around it. **Ix is
untested against this repo**, and nothing below is Ix output.

When Docker Desktop is running, these are the commands, in order:

```bash
ix docker start
ix status
ix map .                    # build the graph (large repo: minutes)
ix overview                 # subsystem summary
ix subsystems               # the layer picture Ix infers
ix smells                   # its own defect heuristics
ix impact hermes.methodology.substrate.write_node
ix callers hermes.research.gateway.apply_intent
ix inventory
```

The two worth comparing against the table in §2 are `ix subsystems` and `ix smells` — if Ix's inferred
subsystems disagree with the hand-built layer matrix, that disagreement is itself informative.

## 2. The map, built from the tree

`scripts/structure_map.py` (import-level, AST, read-only, deterministic).

**135 modules, 439 import edges.** Layer matrix, rows depend on columns:

```text
              agents resear method  tools persis  vault   eval securi   core
agents             .      .      .      3      .      .      .      4     13
research           7      .      5     32     22      .      .      4     18
methodology        2      .      .      .      .      .      .      .      .
tools              .      2      .      .      .      .      .      7      .
persistence        .     11      .      2      .      .      .      .     20
eval              15      1      1      7      .      .      .      2      1
```

### The finding that matters

**`persistence` and `research` are mutually dependent — a six-module cycle:**

```text
hermes.persistence.failure_classifications
hermes.persistence.repositories
hermes.persistence.source_outcomes
hermes.research.completion
hermes.research.contradiction_candidates
hermes.research.extraction
```

This is **deliberate**, and the code says so: `failure_classifications.py` documents that "the write path
re-runs the substrate with REAL resolvers", which is why persistence imports `research.failure_classification`
and `research.regimes`. It is not a slip.

But it has a consequence that explains this entire week. **A contract disagreement between persistence and
research has no layer boundary to catch it**, because there is no boundary — the two are the same
strongly-connected component. Every defect we chased was "two layers disagreeing about a value", and in the
region where the largest modules live (repositories 150 KB, gateway 247 KB, controller 293 KB) the layers
are not separated at all. The compatibility question the Director asked is, structurally, this cycle.

Second cycle: `journal_chain` ↔ `migrations` — a two-module bootstrap knot.

### The one clean seam

`methodology → persistence` is **0 edges**, and the rule that says so is written down
(`docs/OPS-5Y-DESIGN.md` §9.1: the driver imports persistence, not the plane). It is the only seam in the
matrix with a citation *and* a zero. It is also where the contract matrix can do its work — a pure seam can
be checked statically, an entangled one cannot.

### Where the contracts concentrate

- **`tools` fan-in 144** — the widest contract surface in the tree. Every field the model contract declares
  flows through `tools.models.router` and `tools.models.cloud`, which is exactly where the OPS-5Z defect
  lived.
- Largest modules track the audit's findings: `controller` 293 KB (5,684 lines), `gateway` 247 KB (5,207),
  `repositories` 150 KB, `router` 118 KB, `runtime.run` 117 KB. The red-team's most productive files are
  the five biggest ones — concentration predicts defect density.

## 3. What this map cannot see

It is **import-level**. It cannot see:

- a call from one function to another **inside the same module** — which is where the audit's `_apply`
  fail-open and the completion gate live (`run.py` calling its own `_admission_tally`);
- symbol-level impact ("what breaks if I change `write_node`");
- data flow — that a value written by one layer is read with a different meaning by another, which is the
  actual shape of every bug this week.

That is precisely the gap Ix closes: `CALLS` edges at symbol granularity. It is why running Ix when Docker
is available is worth doing rather than a nice-to-have — my map can show that two *files* are entangled, Ix
can show that `write_node` is called from eleven places and what each of them assumes.

## 4. One correction this exercise produced

The first draft of `structure_map.py` shipped a rule I invented — "persistence must not import the research
plane" — and reported 11 violations against it. Reading `failure_classifications.py` showed the edge is a
documented design decision. The script now carries **only rules with a citation**, and reports zero broken.

That is the same lesson as the invariant suite: a check that encodes the author's assumption produces
confident false positives, and the fix is to make every rule cite its source.

---

# 5. Ix, now that Docker is up

Run on the same tree (`diag/contract-matrix` @ `03aedad`). `ix` 0.9.3, backend revision 140, full ingest.

## Scale

```text
nodes 32,956    edges 100,182
  module 9,659   function 9,504   class 1,388   file 862
  CALLS 54,247   CONTAINS 17,406  DEFINES 17,401  IMPORTS 9,659  REFERENCES 1,211
```

My import map saw 439 edges. Ix sees **54,247 calls** — the three orders of magnitude that matter, because
a contract disagreement travels along a call, not an import.

## The contract surface is the gateway, not the substrate

| symbol | direct callers | direct callees |
|---|---|---|
| `apply_intent` | **387** | 29 |
| `write_node` | 42 | 11 |

OPS-5Y changed `write_node`'s contract and had to rewrite ten fixture files — that was 42 callers. The
spine's single mutation path has **387**. Any change to `apply_intent`'s payload contract ripples across 387
sites, which is a structural reason the gateway has stayed stable and why changes there are expensive.

## Ix's own smell ranking agrees with the audit

Top `God Module` rows by fan-in / fan-out:

```text
repositories.py   fan_in=130  fan_out=71
gateway.py        fan_in=88   fan_out=129
controller.py     fan_in=62   fan_out=157
router.py         fan_in=52   fan_out=35
run.py            fan_in=36   fan_out=87
composition.py    fan_in=18   fan_out=98
```

Those are the files the red-team audit found most findings in, and the two largest in my map. Coupling
predicted defect density; Ix measures the coupling independently.

Caveat: 735 smell candidates, of which **494 are "Orphan File"** — every `.md` in a documentation-heavy repo.
The category is noise here; the God Module head is the signal.

## Where Ix disagrees with the package layout — and I would not trust it

Ix infers its own subsystems by call affinity, and its grouping does not match the directories:

```text
Hermes / Vault   ->  Persistence (101), Providers (33), Adapters (15), Research (11), Vault (8)
Hermes / Eval    ->  Models (26), Runtime (24), Capabilities (22), Methodology (22), Eval (8)
```

Methodology under "Eval", Persistence under "Vault", at 53–55% confidence ("moderate"). That is Ix telling
you it is unsure. Treat `ix subsystems` as a hypothesis about coupling, not as an architecture — the layer
matrix in §2, built from the package boundaries the code actually declares, is the better account of
*intended* structure. The two disagreeing is itself informative: the call graph does not respect the layers,
which is the same conclusion the six-module cycle reached from the other direction.

## Two corrections made while running this

1. **I nearly shipped a false finding.** `ix callers apply_intent --pick 1` resolved to a *module* (an
   import site) and reported "No graph-backed CALLS/REFERENCES edges found". I read that as "the spine's
   single mutation path is invisible to static analysis" — an appealing story, and wrong. `--kind function`
   resolves the real definition and finds 387 callers. The tool was fine; my invocation was not.
2. Earlier, `structure_map.py`'s first draft invented a layering rule and reported 11 violations against a
   documented design decision. It now carries only cited rules.

Both are the same failure mode this whole exercise is meant to catch: a confident claim whose evidence was
never checked. The instruments are not exempt from the rule they enforce.

## What Ix still cannot tell you

It sees that `apply_intent` has 387 callers. It cannot see that one of them passes a `statement` the
validator will accept while another passes one it will refuse — the disagreement this project actually
suffers from is about **meaning**, and no call graph carries meaning. That is why the contract matrix exists
alongside it: Ix maps the wires, the matrix checks what travels on them.

---

# 6. The map becomes a gate

The map was a report. Three changes make it enforce, and they answer the question that started this:
*does fixing one thing disturb the whole?*

## 6.1 The structural ratchet

```bash
python scripts/structure_map.py --root src/hermes --ratchet docs/STRUCTURE-RATCHET.json
```

Pins the layer matrix and the cycle set. Fails on:

- **a new layer→layer edge** — not a count increase on an existing edge (more `research → tools` imports is
  normal), but a *kind of dependency that did not exist yesterday*. That is a boundary, and a contract
  disagreement needs one to travel along.
- **a new strongly-connected component** — always. (Not any new cycle: a sub-cycle inside an existing
  SCC does not change the SCC set, so it is not reported. The code was right; this line said "a new cycle".)

`--allow "<reason>"` moves the ratchet and records the reason in its history; `--update` re-records. Verified
all three paths: holds (0), new edge (1), allowed (0 + history entry).

Pinned today: 6 layer edges, 2 cycles — `persistence ↔ research` (deliberate: the write path re-runs the
substrate with real resolvers) and `journal_chain ↔ migrations` (a bootstrap knot).

## 6.2 The invariant, from pytest too

`test_no_new_layer_edge_or_cycle_since_the_ratchet` runs the same comparison inside the suite, so a change
that quietly couples two layers fails `pytest` and not only a script someone must remember to run. Verified
by dropping an edge from the ratchet: it fails with `new layer edge(s) since the ratchet: ['agents->tools']`.

That is the one thing no other test in this tree does — nothing else looks at imports at all.

## 6.3 Blast-radius weighting in the matrix

`contract_matrix.py` now sorts its mismatches by the import fan-in of the modules that own the seam
(`run.py`, `substrate.py`) and prints a `blast` column. Today all three 5Z mismatches score 6.

**Honest limit:** import fan-in is a coarse proxy. Ix reports `run.py` at **36 call callers**, six times
higher, because calls cross modules that imports don't. The proxy is what makes the gate runnable without
Docker; when Ix is available its number is the better one, and the doc says so rather than implying the
proxy is the truth.

## 6.4 What did not change

The depth ratchet is untouched — structure says nothing about how far a chain reaches, and inventing a
connection would have been the same mistake as the layering rule I had to retract. Two of three gates
evolved; one correctly did not.

---

# 7. The audit's F6 — the ratchet was narrower than it claimed

Six repairs, each reproduced before and after.

| hole | before | after |
|---|---|---|
| a new module on an already-pinned pair | invisible (pins only layer *pairs*) | **`NEW MODULE EDGE hermes.research.audit_probe->persistence`**, exit 1 |
| `if TYPE_CHECKING:` imports | counted as runtime coupling (false positive) | excluded — a type-only import is not an edge |
| `from hermes.research import x` | recorded as the *package*, so sibling cycles were invisible | resolved to `hermes.research.x` when that is a module |
| a missing ratchet | `no ratchet recorded yet`, **exit 0** | **exit 2** — a missing ratchet is not a pass |
| the one documented rule | computed, printed, **never enforced** | `RULE BROKEN`, exit 1; `--update` **refuses to pin** it |
| an unparseable file | skipped silently | reported as a finding |
| `--allow` on several edges | one reason covered all of them, history named none | `--allow-edge <name>` for one; `--allow` records the names |

Also: `modules` now counts every `.py` file, including the 36 with no edge in either direction. The old
number (135) excluded them and the doc called it "modules" without saying so.

The ratchet now pins **module→layer** edges as well as layer pairs, which is what makes the first row work.
Count increases on an existing pair stay invisible by design — more imports of a dependency the project
already has is normal; a *new module* reaching across is the event.

## What is still true

- A `from hermes.<pkg> import <name>` that names a **symbol** rather than a submodule is still recorded as
  an edge to the package. The parser cannot tell them apart; resolving it needs the symbol table, which this
  tool does not build.
- Dynamic imports (`importlib`) remain invisible. The tree has one (`eval/import_gate.py`).
- A new *sub*-cycle inside an existing strongly-connected component is still not a new SCC, so it is not
  reported. The doc says "a new cycle"; the code says "a new SCC". The code is right and the doc is now
  corrected below.

---

# 8. The second audit — N1, N2, N3, N11

Four findings, all reproduced before and after. The first is the worst single defect found in either audit.

## N1 — the map never read one file of the real tree

`hermes/tools/models.py` and `hermes/tools/models/__init__.py` both resolve to `hermes.tools.models`. The
dict kept whichever came last, which was the **95-byte placeholder**, so the real package `__init__.py` was
never parsed. Its imports were invisible to edges, module edges, the layer matrix and the count — and
**Python loads the package**, so the map was wrong about the file that actually runs.

```text
inject "import hermes.persistence.repositories" into tools/models/__init__.py
  before: exit 0, no findings
  after:  NEW LAYER EDGE tools->persistence, exit 1
```

Fixed by resolving a name collision the way Python does (package wins) and reporting the loser:

```text
modules: 170 | shadowed: ['hermes.tools.models (shadowed: tools\models.py)']
```

The shadowed set is **pinned** in the ratchet, so the existing duplicate is a recorded fact and a *new*
duplicate is loud. A hard failure would have made the gate permanently red for a tree condition.

This also corrects §7's "modules now counts every `.py` file": 171 files, 170 modules, one shadowed.

## N2 — `--allow-edge` accepted any string

A name matching nothing moved the ratchet and allowed everything; the *correct* name laundered every other
simultaneous finding. Now a name not in the new set is a misconfiguration (**exit 2**), and the allow branch
no longer ignores other findings.

## N3 — a non-dict ratchet exited 0

`[]` or `"garbage"` read as "no ratchet recorded yet" and disabled the gate. Now **exit 2**.

## N11 — relative imports in a package `__init__` fabricated a phantom layer

For `__init__.py`, `package` was computed one level too high, so `from .a import A` resolved to `hermes.a`
instead of `hermes.persistence.a`. Latent (zero in the tree today), now fixed.

## Also

A crash now exits **2**, not 1 — `exit 1` means "a finding" and a traceback must not impersonate one. Stdout
is pinned to UTF-8. Both were found by walking into them while making these changes.
