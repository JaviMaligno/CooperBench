# Experiment: Structure vs Social Intelligence in Coding-Agent Collaboration

Response experiment to **CooperBench** (Khatua/Zhu/.../Yang, arXiv 2601.13295,
"Why Coding Agents Cannot be Your Teammates Yet").

## Thesis

CooperBench measures *unstructured, advisory* coordination **by design** (they
deliberately avoid scaffolding: "scaffolds limit flexible cooperation") and from
the resulting "curse of coordination" conclude agents lack trained *social
intelligence*. The engineering question they skip is: **what is the minimal
*enforced* structure that makes agents effective teammates, and does its effect
scale with model capability?** Humans don't fix coordination failures with
therapy — they use process (ownership, contracts, review, sequencing).

**What is NEW here (not in their paper):**
1. Effect of *our* enforced structural interventions on the coordination gap.
2. The **capability × structure interaction** (they report solo/coop per model
   but not how much *structure* recovers as a function of model strength).
3. The **minimal-structure frontier** (cheapest structure that recovers solo-level).

Reproducing solo→coop is only a **sanity check** (cite theirs, don't claim it).

## Conditions (ordered by "structure cost"; advisory → enforced)

| id | name | enforced? | targets (their failure modes) | real-world analogue |
|----|------|-----------|-------------------------------|---------------------|
| C0 | `coop` (baseline, theirs) | no | — | free-for-all |
| C0.5 | `team` (theirs) | **advisory** ownership | commitment 32% | lead/member + task list |
| C1 | plan-first handshake | enforced gate | expectation 42% | design/API review before coding |
| C2 | territory ownership ENFORCED | enforced | commitment 32% / overwrites | CODEOWNERS / locks |
| C3 | sequential pipeline | enforced ordering | all | sequential PRs / rebase on main |
| C4 | integrator agent | enforced | integration reasoning | PR reviewer / integration eng |

### C1 — plan-first handshake (cost: low)
Each agent must publish a structured plan (files/functions/line-ranges + exposed
interface) and receive partner `ack` BEFORE the edit tool unlocks. Scaffold gates
editing in the agent loop. New Redis verbs `coop-plan`/`coop-ack`. The "minimum"
candidate on the frontier.

### C2 — territory ownership enforced (cost: medium) — ⭐ flagship
File/region space partitioned up front; scaffold **rejects** edits outside the
owned territory (hook checks the diff, reverts/denies). This is the *enforced*
version of what `team` does *advisorily*. **Key contrast: `team` (advisory) vs C2
(enforced), same structure, only enforcement differs** → isolates the thesis to a
single variable. If C2 >> team, the missing ingredient is enforced compliance, not
social intelligence.

### C3 — sequential pipeline (cost: high structure, but the ceiling) — START HERE
Agent A implements its feature and "commits"; Agent B starts FROM A's resulting
code and implements its feature. Concurrent-conflict problem becomes a rebase.
Upper bound: if even this doesn't recover solo, the problem is deeper than
coordination. Cheapest to implement (orchestration wrapper, reuses solo machinery
twice + patch chaining; no agent-loop changes). Trade-off to discuss: gives up the
parallelism that motivates multi-agent.

### C4 — integrator agent (cost: high; later)
Third agent owns the merge: receives both patches, resolves conflicts, runs tests,
returns fixes.

## Axes & measurement
- **Capability axis:** `gpt-5.4` / `gpt-5.4-mini` / `gpt-5-nano` (Azure native route).
- **Metrics:** pass rate; gap-closed = (cond − coop)/(solo − coop); retention =
  cond/solo; plus **cost-of-structure** ($/tokens/wall-time per condition).
- **Eval set:** iterate on `light_local` (fast Python amd64 repos); `flash`(50) as
  FINAL field once a condition shows signal (flash is the test bed, NOT the result).

## Implementation order
1. **C3** (ceiling, cheapest code) → then **C2** (flagship contrast vs team) →
   then **C1** (minimum) → **C4** (last). All 4 land eventually.
2. TDD on the light bench. Inject prompts in `src/cooperbench/agents/_coop/prompt.py`;
   enforcement hooks in the agent loop (`mini_swe_agent_v2/agents/default.py`) and
   Redis tool (`_coop/coop_msg.py`); C3 as an orchestration wrapper.

## Pilot result (2026-06-30, light_local n=4, DIRECTIONAL, not publishable)
| model | solo | coop | team |
|-------|------|------|------|
| gpt-5.4-mini | 25% | 0% | 0% |
| gpt-5.4 | 50% | 0% | 25% |
→ gap reproduces; `team` recovers half the gap ONLY on the capable model →
directional support for capability×structure. (`team` deadlocked ~46 min once.)

## C2 implementation design (enforced ownership)

**Territory granularity — the key decision.** CooperBench tasks overlap the same
file by design (~77%), so *exclusive file-level* ownership will block the
non-owner from a file its feature genuinely needs — informative, but expect it to
underperform on overlap-heavy tasks. Two versions:
- **C2a (v1): claim-based file ownership, enforced.** No upfront planning (keeps
  C2 isolated from C1). First agent to touch a file claims it (claims map in
  Redis); an edit touching a file claimed by the OTHER agent is REJECTED. Realistic
  "code ownership"; measures the cost of coarse exclusivity.
- **C2b (later): line-range / function ownership** (negotiated up front → ties to
  C1). Finer, handles shared files.

**Enforcement mechanism (C2a).** Pure helper DONE: `agents/_coop/territory.py`
(`files_in_patch`, `territory_violations`). Integration (not yet built): after each
agent action, `git diff --name-only` in the container; for each touched file —
claim it if unclaimed (Redis), or if claimed by the other agent, `git checkout --`
that file to REVERT the out-of-territory edit and inject a message telling the
agent to coordinate. Hook point: `mini_swe_agent_v2/agents/default.py`
`execute_actions` (post-action), behind a `--setting`/flag. Needs Redis claims
store (extend `_coop/coop_msg.py` pattern) + docker integration test.

## Operational constraints (learned in pilot)
- Local Mac is Intel x86_64. Heavy/incompatible repos: `typst`(10GB Rust),
  `react_hook_form`, `dottxt_outlines` (hang); `go_chi` (no amd64 image);
  `openai_tiktoken` task0 (bad patches hang tests). Use `light_local` subset.
- Runs are RESUMABLE (omit `--force`) → interruptions don't lose work.
- `COOPERBENCH_EVAL_TIMEOUT` env added to `eval/sandbox.py` (hanging patch fails fast).
- NEED a per-task wall-clock cap for `team`/coop deadlocks before scaling.
- Long runs die if the Mac sleeps; `caffeinate -i` doesn't beat lid-close.
  Budget cap $200 via `MSWEA_GLOBAL_COST_LIMIT` per batch + `cost_ledger.py`.
- Helpers in repo root: `azure_env.sh`, `cost_ledger.py`, `oracle_check.py`,
  `dataset/subsets/light_local.json`.

## QA & extensions plan (2026-07-03, post-review)

Order: **QA first** (can change already-written numbers), then combos, then the
restart experiment. Do not publish the article until QA lands.

### Phase QA — trust the scaffolding before anything else
- **QA-a. c4 eval composition bug (CRITICAL, in progress).** The integrator
  starts with patch_a committed, so its `git diff` (vs HEAD) may exclude A's
  work; eval routes c4 -> test_solo(integrator.patch) against BASE -> feature1
  can never pass -> suspected false 0%. Empirical check: eval one task as
  base+patch_a+integrator (== test_sequential). If confirmed: fix evaluate.py
  c4 routing to compose patch_a + integrator patch, re-eval all c4 (eval-only,
  $0 Azure). May flip the c4 row at both tiers.
- **QA-b. C2b v2: per-hunk revert.** Replace the v1 whole-file revert (the
  "artifact" noted in the article) with reverting ONLY the violating hunks
  (git apply -R of the offending hunks, or checkout + re-apply non-violating
  ones). Rerun C2b both tiers (~$10 Azure, docker local).
- **QA-c. Merge fairness.** "Failing at merge conflicts" may be too cheap a
  death: the paper mentions an LLM resolver for trivial conflicts; our eval
  used naive+union strategies. Audit which strategies actually fired in our
  coop evals (eval.json merge.strategy), check whether the OSS eval includes
  the LLM resolver, and if not implement/enable it so coop isn't unfairly
  penalized vs the paper's setup. Re-eval coop-family runs (eval-only, ~$0-2).
- **QA-d. Repeats for error bars.** 2 extra seeds of the informative cells
  (solo, coop, C3, C2 x 2 tiers): ~$65 Azure total, docker local. Report
  mean +/- range; keeps N moderate without being sloppy.
- **QA-e. Independent scaffolding audit.** Code review (agent, $0) of the five
  condition implementations (enforcement hook, handshake gate, seq, c4,
  eval routing) hunting construction bugs like QA-a.
- **QA-f. Article naming/link.** DONE: C3/C4 codes harmonized, repo linked.

### QA results (2026-07-03)

**QA-e (adversarial code audits, 2 independent agents).** Enforcement side:
one CRITICAL (new/untracked files escaped handshake+territory enforcement —
FIXED in deb006a; verified empirically that no published enforced pass
depended on the leak, 0/4 passes contained new files), race-condition
findings dismissed (agents run in isolated containers, one env each),
anchor-line-0 "bug" dismissed (ledger is keyed per file — intended
behavior). Eval side: CRITICAL latent GCP-batch bug (EVAL_SCRIPT measures
naive coop merge for seq/c4 — now rejected loudly; all published runs used
docker, verified uncontaminated), MAJOR *_test.go not filtered from patches
(FIXED; 12 go_chi pair-evals re-run), MAJOR silent starting_patch failure
(now aborts; never fired — verified via SHA chaining on all seq/c4 pairs),
plus pass_rate denominator fixes. Auditors verified the c4 composition fix,
seq stacking, and C1/C2/C2b eval routing as correct.

**QA-c (merge fairness).** The paper (§2.2) resolves trivial conflicts with
a small trained model (Qwen 3 Coder 1.5B); the OSS eval release omits it
(naive git merge + lead-alone fallback only — upstream, we changed nothing).
Conflict triage of all 29 conflicted coop pairs: mini 6/15 mechanically
trivial (9/15 counting LLM-resolvable borderline: orthogonal kwargs on the
same signature, import unions), large 4/14 (6/14 borderline). The rest are
genuine semantic collisions (one agent refactors what the other edits).
Remediation: opt-in LLM trivial-conflict resolver (COOPERBENCH_LLM_RESOLVER=1,
fixed model azure/gpt-5.4-mini — stronger than the paper's, so coop gets
the benefit of the doubt), GIVEUP on anything semantic, strategy recorded
as "llm-resolver" in eval.json. Re-eval of all conflicted coop+C1 pairs
runs as eval_resolver.json (baseline eval.json preserved). First validated
pair: merge rescued, one feature passes 71/71, the other fails a genuine
test 59/60 — the conflict was masking a real feature failure.

**QA-c batch outcome (2026-07-03, 59 resolver re-evals + 12 go_chi).**
go_chi filter fix: 0 flips — published table unchanged. Resolver: rescued
22-23/59 conflicted merges, but only 3 pairs flip to pass → conflicts were
mostly masking semantic feature failures. FAIR TABLE (resolver applied to
coop+C1): mini coop 0/19 (unchanged), large coop 2/19 (11%, was 5%), mini
C1 1/19 (5%), large C1 0/19. Partial credit fair-coop: mini 4×one-feature
(was 1), large 2×both+4×one. SURVIVES fair eval: coordination gap (pooled
solo vs fair-coop p=0.008) and seq/c4 recovery (pooled p=0.008). REVISED:
C2's edge over coop largely dissolves under fair merging (C2-large 3/19 vs
fair-coop 2/19, near-same tasks) — enforced ownership and a post-hoc
trivial resolver fix the same *syntactic* layer; seq/c4 (6/19 each) still
~3× fair-coop because they fix the *semantic* integration layer. Article
must add the fair-coop row and soften the C2 claim accordingly.

### Phase combos (mechanism-driven, after QA)
The mechanism suggests complementarity: C2 eliminates *syntactic* conflicts
(0/19 merge conflicts) but leaves *semantic* integration failures; C4 (a
reviewer/integrator) is meant to fix exactly those. Combos to test, in order:
1. **C2 + C4**: territory during development + integrator at merge (the star:
   each patches the other's failure mode).
2. **C1 + C2**: plan handshake + enforced territory (plan-then-own).
3. **C3 + C4**: sequential + final reviewer (does review add anything once
   sequenced?).
Estimate per combo: ~$10-15 Azure both tiers, docker local. Success bar: any
combo beating BOTH its components and approaching/beating solo.

### Phase restart (article 2, fresh session)
(a) free mining (done: destruction=flailing at short horizon; adaptation after
imposed restarts is the capability marker), (b) loop-with-evaluator mode:
visible tests + K iterations + restart affordance, voluntary-restart
rate/timing/payoff by tier (~$40-60 Azure), (c) restart etiquette in shared
workspaces (does a restarting agent preserve its partner's work?).
