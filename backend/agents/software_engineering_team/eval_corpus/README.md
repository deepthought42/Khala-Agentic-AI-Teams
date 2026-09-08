# SE Review Gate Evaluation Corpus

Labeled cases pairing a diff (or file set) with the findings the review gates
are expected to produce on it. This is the ground truth the golden-set
evaluation harness scores against.

Governing specifications, all under [`../docs/`](../docs/):

| Doc | What it fixes |
|---|---|
| [`CORPUS_CASE_FORMAT.md`](../docs/CORPUS_CASE_FORMAT.md) | The case and label schema, and the 31-value closed defect-class vocabulary |
| [`GATE_FINDING_MATCHING_RULE.md`](../docs/GATE_FINDING_MATCHING_RULE.md) | When a produced finding counts as matching a label |
| [`CORPUS_FALSE_POSITIVE_RESISTANCE.md`](../docs/CORPUS_FALSE_POSITIVE_RESISTANCE.md) | How a case declares that a gate must *not* report something |
| [`CORPUS_SELECTION_PLAN.md`](../docs/CORPUS_SELECTION_PLAN.md) | The designed distribution these cases fill |
| [`GATE_FINDING_INVENTORY.md`](../docs/GATE_FINDING_INVENTORY.md) | What the gates actually emit |

## What is here today

**40 case directories (`CASE-0005`–`CASE-0044`), carrying 45 `must_find`
labels.** This is the recall half of the corpus. The
false-positive-resistance half is authored separately and is not present yet,
so the corpus is not yet complete against the selection plan's 60-case target.

`CASE-0001`–`CASE-0004` are permanently reserved for the worked examples in
the format and false-positive-resistance specifications. They are deliberately
not materialized here: case identifiers are never reused or renumbered, so
reserving them is cleaner than renumbering these cases later.

### Layout

```
cases/CASE-NNNN/
  case.yaml      # identifier, title, language, stack, gates, mode, origin
  labels.yaml    # the expected_findings list
  diff.patch     # mode: diff
  files/         # mode: files
```

### The `origin` block

Each `case.yaml` carries an `origin` block recording provenance. The rules —
which fields are required when, what a real case's `diff.patch` is reduced to,
which commit it applies to, and why real cases stay pinned — are normative in
[`CORPUS_CASE_FORMAT.md`](../docs/CORPUS_CASE_FORMAT.md) §1 and are not
restated here.

```yaml
origin:
  sourcing: real        # real | invented
  commit: "0040820"     # short SHA of the fix commit, quoted; real sourcing only
  note: >               # invented: why no real example was available
    ...                 # real: may record a substitution or other nuance
```

What is specific to this corpus, rather than to the format:

- **Five cases depart from the source the selection plan named**, and each
  records why in its `note`. They split two ways. `CASE-0012` and `CASE-0029`
  are still real-sourced: only their origin commit changed, so the `note` sits
  on a `sourcing: real` case. `CASE-0015`, `CASE-0020` and `CASE-0032` could
  not be sourced from history at all — the planned commit does not invert to
  the defect, or the defect it shows is contestable — so each is `sourcing:
  invented` and its `note` records the commit it was modelled on. All five are
  listed under *Substitutions from the selection plan* below.
- **One case keeps the whole inverse** rather than a reduced subset, because
  its defect has no coherent one. `CASE-0033`'s label is file-wide — a
  component with twelve subscriptions and no teardown, which is one design
  defect repeated, so it keeps a single label; its precision contribution is
  not meaningful and should be read that way.
- **One case reduces to a single line** rather than a whole block. `CASE-0035`'s
  block reverts four sibling constructor arguments to the same unsafe pattern,
  and labelling all four would score a gate that reports the pattern once — the
  correct behaviour — at 25% recall for the case.

## Achieved distribution

| Measure | Value |
|---|---|
| Case directories | 40 |
| `must_find` labels | 45 |
| Cases from real history | 25 (63%) |
| Invented cases | 15 (38%) |
| Labels from real history | 30 of 45 (67%) |
| Backend-primary cases | 32 (80%) |
| Frontend-primary cases | 8 (20%) |

### Per-class must-find counts against the selection plan

Every class matches its target in `CORPUS_SELECTION_PLAN.md` §3 exactly except
`auth`, which carries 4 labels against a target of 2. `CASE-0023`'s diff opens
three Slack endpoints to unsigned requests, not one, so it carries a label per
site. Labelling only the first would have left a gate that correctly reports
either of the others producing unmatched findings — a precision penalty for
being right. The extra labels add no class variety; they exist so the fixture's
ground truth is complete.

| Class | Target | Actual | | Class | Target | Actual |
|---|---|---|---|---|---|---|
| `naming` | 1 | 1 | | `injection` | 1 | 1 |
| `structure` | 1 | 1 | | `xss` | 1 | 1 |
| `logic` | 3 | 3 | | `csrf` | 1 | 1 |
| `spec-compliance` | 1 | 1 | | `auth` | 2 | **4** |
| `standards` | 2 | 2 | | `crypto` | 1 | 1 |
| `integration` | 1 | 1 | | `insecure-deserialization` | 1 | 1 |
| `testing` | 1 | 1 | | `ssrf` | 1 | 1 |
| `architecture` | 1 | 1 | | `off-by-one` | 1 | 1 |
| `refactor` | 1 | 1 | | `race-condition` | 3 | 3 |
| `maintainability` | 1 | 1 | | `resource-leak` | 2 | 2 |
| `side-effects` | 1 | 1 | | `null-deref` | 3 | 3 |
| `documentation` | 1 | 1 | | `integer-overflow` | 1 | 1 |
| `missing-import` | 1 | 1 | | `unvalidated-input` | 3 | 3 |
| `wrong-path` | 1 | 1 | | `missing-error-handling` | 2 | 2 |
| `type-error` | 1 | 1 | | `inconsistent-state` | 1 | 1 |
| `syntax-error` | 1 | 1 | | | | |

### Frontend share: a hand-off for the other half

The corpus-wide target is 28% frontend. This half lands **8 of 40 (20%)**.

The hand-off is larger than a first pass suggests, because this half
over-delivered on directory count. The selection plan sized the corpus at 60 —
34 must-find-primary plus 26 false-positive-primary — and this half came out at
**40** directories rather than 34, so the finished corpus will be about **66**.
Frontend share is measured over that whole, and the extra six backend-leaning
directories dilute it:

| | |
|---|---|
| Frontend cases needed for 28% of 66 | 19 (18.48 rounded up) |
| Already delivered here | 8 |
| **Needed from the false-positive half** | **11 of its 26 (≈42%)** |

Delivering instead the plan's absolute 17 frontend cases — 9 more — lands the
corpus at 17/66, or **26%**. Either number is defensible; what is not
defensible is carrying forward a figure that reaches neither, which the
earlier "9 of ~24 (≈37%)" did.

That shortfall is real and is recorded rather than papered over. Frontend
supply in this repository's shipped-and-fixed history is genuinely thinner
than 28%, and the two cross-stack invented classes that could plausibly go
either way (`integer-overflow`, `type-error`) are already authored as
frontend. Inventing further frontend cases purely to move the ratio would
produce exactly the "whatever was easy to find" corpus the selection plan was
written to prevent.

### Substitutions from the selection plan

Five of the plan's cited commits did not survive contact with their actual
diffs. Every substitution is recorded here rather than forced.

- **`standards` (frontend), `CASE-0012`.** The plan cites `1308c1d` for a
  native `alert()` replaced by the application's snackbar convention. That
  commit's net squashed diff contains no `alert()` — the call had already been
  removed by `086a4894`, which is the commit that actually performs the
  substitution. `CASE-0012` is sourced from `086a4894`.
- **`injection`, `CASE-0020`.** The plan cites `27691e3` for an
  f-string-interpolated SQL table name. That commit hardened a fixed code
  literal that was never attacker-controlled — defence in depth, not a
  vulnerability the gates should have caught — so inverting it produces no
  exploitable defect.
  Every real SQL path in this codebase parameterizes its values, and no genuine
  injection fix exists in the history to source from, so `CASE-0020` is
  authored as an invented case with a request-reachable injection and marked
  `sourcing: invented`.
- **`resource-leak` (frontend), `CASE-0032`.** The plan cites `caed749` for
  flowchart click listeners that are never removed. Whether that is a leak is
  arguable: the listeners bind to nodes inside the component's own view, which
  the framework tears down with the component, so the node/closure cycle is
  collectable with or without `removeEventListener`. Ground truth cannot rest on
  a contested reading, so `CASE-0032` is authored as an invented case whose
  listener is held by `window` — an object that genuinely outlives every
  component — and marked `sourcing: invented`.
- **`architecture`, `CASE-0015`.** The plan cites `ae3ccf70` for a
  team-agnostic platform test importing a domain team package. That pull
  request introduced *and* fixed the violation within itself, so the violating
  state was squashed away and never reached `main`; the net diff is
  boundary-clean and does not invert to the defect. `CASE-0015` is authored as
  an invented case modelled on the boundary `ae3ccf70` documents, and is
  marked `sourcing: invented` with that reason.
- **`race-condition`, `CASE-0029`.** The plan cites `cb8aded` for a TOCTOU
  between a cancellation check and a terminal status write. That commit's fix
  replaces one atomic helper with a compare-and-set used at four call sites in
  a single function and deletes a status sentinel that unchanged callers
  elsewhere still import, so no subset of it reduces to one coherent defect and
  the whole inverse leaves the fixture unimportable. The plan's own backup
  commit `0523b9c` fixes the same race in the same function with a single
  guard, and `CASE-0029` is sourced from it; the case stays `sourcing: real`
  with the substitution recorded in its `note`.

No path was genericized for sensitivity: real-sourced cases use their true
repository-relative paths throughout, and no fixture embeds a credential,
token, key, or other private value. The one hard-coded key literal — the
fallback in `CASE-0025`, which is the defect that case labels — is a
self-describing placeholder decoding to `placeholder-not-a-real-key-32byt`,
not a secret.

## Case index

| Case | Title | Class(es) | Gate(s) | Sourcing | Origin | Stack |
|---|---|---|---|---|---|---|
| CASE-0005 | Predicate name is the inverse of what the function returns | `naming` | code_review | invented | — | backend |
| CASE-0006 | Response model defined inline in agent.py instead of models.py | `structure` | code_review | invented | — | backend |
| CASE-0007 | Null recommendation stringified to the literal "None" | `logic`, `null-deref` | code_review, qa | real | 0040820 | backend |
| CASE-0008 | Excluded-company match uses substring instead of word boundaries | `logic` | code_review | real | 766c6e5 | backend |
| CASE-0009 | aria-label bound as a host attribute on mat-checkbox | `logic` | code_review | real | 3fd49f5 | frontend |
| CASE-0010 | Missing report answered with 200 instead of the documented 404 | `spec-compliance` | code_review | invented | — | backend |
| CASE-0011 | Cache root read from an environment variable that is never set | `standards` | code_review | real | c6169cd | backend |
| CASE-0012 | Native blocking alert() used for an error toast | `standards` | code_review | real | 086a4894 | frontend |
| CASE-0013 | Factory overwrites its own injected llm_client | `integration` | code_review | real | e325ad8 | backend |
| CASE-0014 | Teardown success spec passes without exercising the subscribe path | `testing` | code_review | real | 0175839 | frontend |
| CASE-0015 | Team-agnostic platform test imports a domain team package | `architecture` | code_review | invented | — | backend |
| CASE-0016 | Inherited execution-phase helper reimplemented inline in the subclass | `refactor` | code_review | real | 51810fd5 | backend |
| CASE-0017 | Dead empty-string default under a correct `or` fallback | `maintainability` | code_review | real | 66bc52d5 | backend |
| CASE-0018 | Crash handler leaves the dedicated error field unset | `side-effects`, `inconsistent-state` | code_review, qa | real | c8cbbb7 | backend |
| CASE-0019 | Docstring documents a precondition the function never enforces | `documentation` | code_review | real | c0db42b | backend |
| CASE-0020 | Request query parameters interpolated into a raw SQL string | `injection` | security | invented | — | backend |
| CASE-0021 | Trigger description interpolated unescaped into trusted SVG | `xss` | security | real | 7e11ddc | frontend |
| CASE-0022 | State-changing endpoint accepts a cookie-authenticated cross-origin form post | `csrf` | security | invented | — | backend |
| CASE-0023 | Webhook signature verification skipped when the secret is unset | `auth` ×3 | security | real | f1f605b | backend |
| CASE-0024 | Repository-relative path joined without containment check | `auth`, `unvalidated-input` | qa, security | real | c5a9017 | backend |
| CASE-0025 | Encryption key falls back to a hard-coded literal | `crypto` | security | invented | — | backend |
| CASE-0026 | Cached payload deserialized with pickle | `insecure-deserialization` | security | invented | — | backend |
| CASE-0027 | User-configured URL fetched with no destination restriction | `ssrf` | security | invented | — | backend |
| CASE-0028 | Progress counter can grow past the next phase's fixed value | `off-by-one` | qa | real | 70f16f7 | backend |
| CASE-0029 | Cancellation re-check missing before the terminal status write | `race-condition` | qa | real | 0523b9c | backend |
| CASE-0030 | Lock released between session enumeration and write-back | `race-condition` | qa | real | f5eb3e9 | backend |
| CASE-0031 | Read-then-delete is not atomic, so pop can return stale data | `race-condition` | qa | real | 56c2fcd | backend |
| CASE-0032 | Window listener registered on init and never removed | `resource-leak` | qa | invented | — | frontend |
| CASE-0033 | Component subscribes throughout with no teardown on destroy | `resource-leak` | qa | real | 9ac88a3 | frontend |
| CASE-0034 | OHLC values coerced with float() without a null guard | `null-deref` | qa | real | c0e71da | backend |
| CASE-0035 | Explicit null field stringified into the literal "None" | `null-deref` | qa | real | fd3b9a0 | backend |
| CASE-0036 | Identifier from an external API truncated by JS number precision | `integer-overflow` | qa | invented | — | frontend |
| CASE-0037 | Credential store builds its file path from an unvalidated identifier | `unvalidated-input` | qa | real | 3a31cee | backend |
| CASE-0038 | One store method skips the path validation its siblings apply | `unvalidated-input` | qa | real | 0436308 | backend |
| CASE-0039 | Catch-all except returns None, erasing the difference from not-found | `missing-error-handling` | qa | real | 4f1b84e | backend |
| CASE-0040 | Catch-all reported as a specific, unrelated failure | `missing-error-handling` | qa | real | 87a02c2 | backend |
| CASE-0041 | Module uses a name it never imports | `missing-import` | qa | invented | — | backend |
| CASE-0042 | Template path points at a directory that does not exist | `wrong-path` | qa | invented | — | backend |
| CASE-0043 | Discriminated union member accessed on the wrong branch | `type-error` | qa | invented | — | frontend |
| CASE-0044 | Unclosed bracket in a dictionary literal | `syntax-error` | qa | invented | — | backend |

## Limits worth knowing before reading a metric derived from this

These are inherited from `CORPUS_SELECTION_PLAN.md` §7 and hold for the cases
here:

- Twenty-three of the 31 classes carry a single `must_find` label, so one miss swings that
  class's measured recall from 100% to 0%. The corpus confirms a gate catches
  *an* instance, not that it generalizes.
- The matching rule skips the defect-class check for `qa` labels entirely,
  because `BugReport` has no category field. The Group C and D class counts
  are a stratification tool for authoring variety, not a dimension the runner
  can score.
- `severity` is never compared by the matching rule, so nothing here measures
  whether a gate rates a correctly-found defect at the right severity.
- Free-text `qa` and `security` locations frequently resolve to a bare
  basename, which by the matching rule never matches a fuller relative path.
  These cases use true repository paths, so recall for those two gates will
  read pessimistically. That is a real property of the gates' output shape,
  not an artifact to be tuned away by shortening paths.
- **One fixture carries the whole inverse commit rather than a reduced subset,
  because its defect does not live in one block.** `CASE-0033`'s label is
  file-wide, since the defect *is* file-wide — a component that opens twelve
  subscriptions and implements no teardown. That is one design defect
  repeated, which a gate reports once, so it keeps a single label — but a gate
  that reports each subscription separately will produce findings the
  one-per-label rule leaves unmatched. Its precision contribution is not
  meaningful and should be read that way.
- Fifteen cases are invented rather than drawn from history — a structurally
  weaker grade of evidence. Each states in its `origin.note` why no real
  example was available.
