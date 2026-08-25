---
name: deep-research
description: "Run a multi-round autonomous investigation: decompose a question, gather evidence, notice gaps, iterate, and produce a cited report. Use when one search will not answer it."
version: 1.0.0
author: Elidia Agent
license: MIT
prerequisites:
  tools: [research_state, research_gate, research_personas, research_deck]
platforms: [linux, macos, windows]
metadata:
  elidia:
    tags: [Research, Investigation, Evidence, Citations, Multi-Round, Analysis]
    related_skills: [arxiv, osint-investigation, research-paper-writing]
---

# Deep Research

A single search answers a question you already know how to ask. Real research does not
work that way: you decompose the question, gather, read, notice what is missing, and go
again. This skill is that loop.

```
PLAN → [ GATHER → READ → REFLECT ] × N → CROSS-CHECK → SYNTHESIZE
```

**You run the loop yourself.** Every tool stays available at every step — read code, run
an experiment, drive a browser, call a domain skill. That is the point of doing it this
way rather than handing off to a single tool that can only search and write.

## When to use this

Use it when the question needs evidence from several sources, when positions conflict and
someone has to weigh them, or when the answer must be defensible with citations.

**Do not use it for a single lookup.** `web_search` costs one call; this costs many. A
question with one factual answer does not need an investigation.

## Two tools hold the parts you cannot hold yourself

`research_state` remembers the run — sub-questions, retrieved sources, sourced claims,
open gaps, rounds. Checkpointed after every change, so an interrupted run resumes.

`research_gate` decides whether the evidence is enough. It is arithmetic over what you
recorded, not an opinion.

**Why they exist:** over a long loop your own judgement of "have I done enough?" drifts.
After one round with three weak claims it is genuinely tempting to conclude. The gate is
the check you cannot talk your way past — and that is a feature, not an obstacle.

---

## Choose the lens first

Before planning, see what expert lenses exist and what each is grounded in:

```
research_personas(action="list")
```

Pick the persona whose **way of reading evidence** fits the question — a research lawyer
reasons from binding authority and jurisdiction; a clinical researcher weighs evidence by
study design. Pick the mode whose termination contract matches the job.

The tool reports what exists. It does not classify the question for you, and you should
not pattern-match the user's wording either — choose on the substance of what is being
asked.

```
research_personas(action="resolve", persona="...", mode="...")
```

That returns the persona's system prompt, its resource pack, and an announcement line.

**Tell the user which lens you are using before you begin, and honour an override.** The
choice must never be silent. If the resource pack comes back with anything under
`resource_pack_unavailable`, say so — a legal investigation without public-records access
is a thinner piece of work than one with it, and the user should know which they are
getting.

Note that a persona applies to *this run only*. It does not reframe the session.

---

## PLAN

Decompose the question into sub-questions that are independently answerable. Prefer few
and sharp over many and overlapping.

```
research_state(action="start",
    question="<the question as the user asked it>",
    mode="investigation|discovery|simulation|planning|market",
    persona="<expert lens>",
    sub_questions=["...", "..."])
```

Returns a `run_id`. Carry it through every subsequent call.

Pick `mode` for the shape of the job — it sets what "done" means:

| Mode | For | Done when |
|---|---|---|
| `investigation` | legal exposure, due diligence, OSINT | evidence chain complete, contradictions resolved |
| `discovery` | bio, drug, materials | candidates generated, ranked, top ones evaluated |
| `simulation` | case simulation, red-team | both sides argued to exhaustion |
| `planning` | launch, GTM, strategy | options costed, risks named |
| `market` | trading, competitive | positions supported by dated data |

**The question is fixed once set.** Nothing rewrites it. If the user's objective genuinely
changes, that is a new run — not a redefinition of this one.

---

## GATHER

Collect candidate sources for each open gap. Use everything the domain warrants:

- `web_search` / `web_extract` — always available
- `research_sources` — **authoritative domain sources**: PubMed and Europe PMC
  (biomedical literature), ClinicalTrials.gov (registered studies, with status and phase),
  UniProt (protein function), RCSB PDB (3D structures), Crossref and OpenAlex (citations).
  Free, no key. For any clinical, molecular, pharmacological or scholarly question these
  return the evidence, where a web search returns what someone wrote about it.
  Call `action="packs"` first to see what each covers.
- `aiutils_corpus` — the platform's 68 curated corpora, ~4.4M passages (Indian law and
  case law, IPC sections, contract clauses, medical Q&A, arXiv abstracts, company
  profiles, CVE records). Call `action="list"` with `samples=true` **first** and choose
  from what actually exists.
- Domain skills — `osint-investigation` for public records and court filings, `arxiv` for
  papers, `huggingface-hub` for datasets
- Any configured MCP server — `mcp_tool` speaks stdio, StreamableHTTP and SSE with OAuth
- `session_search` — you may have researched this before. Prior runs are a real source.

Choosing among these is your judgement. There is no mapping from question words to
sources anywhere in the system, deliberately: "what did the trial show about the drug's
effect on p53" wants clinical, molecular *and* literature sources at once, and no rule
reads that from the sentence.

**Record every retrieval as you make it:**

```
research_state(action="record_retrieval", run_id=...,
               origin="pubmed",              # what you queried
               query="<what you actually asked>",
               sources=["<id>", "<id>"])     # what it produced — empty if nothing
```

This is not bookkeeping, and it does two jobs. Identifiers recorded here become
citable, so a claim can only cite something genuinely fetched (see READ). And the
record of *where* each source came from is what lets a later round tell a productive
origin from a noisy one.

Record misses the same way, with `sources=[]`. If an origin could not be reached at all,
add `failed=true` — that is a different fact from finding nothing, and only one of them
tells you anything about whether the evidence exists.

### Progressive retrieval

Round 1 asks in the user's words. That is rarely the corpus's vocabulary. From round 2:

- Rebuild queries using **the terms the retrieved evidence actually used**. A
  pharmacologist's name for a mechanism is seldom the phrase in the question.
- Drop origins that are not earning their budget. Spend it where claims are landing.
- Record misses as well as hits — knowing where an answer is *not* narrows the next round.

Before each new round, ask what the record already shows:

```
research_state(action="retrieval_report", run_id=...)
```

It ranks every origin by **accepted claims**, not by passages returned — an origin can
return fifty passages that support nothing while another returns two that carry the
answer. It also lists `queries_tried` per origin, so a round does not repeat itself, and
`no_claims_yet` for origins that have produced nothing so far.

`no_claims_yet` is a list of candidates, not a verdict. An origin often appears there
because the query used the question's wording rather than the corpus's. Try re-asking it
in the vocabulary of the passages you *did* accept before discarding it — that reword is
usually what turns a silent corpus into the one that answers.

---

## READ

Extract claims from what you gathered. One pass over all sub-questions together, not one
call each — it is cheaper and lets you see connections across them.

```
research_state(action="add_claims", run_id=..., claims=[
  {"claim": "...", "source": "<exact recorded source>",
   "confidence": "high|medium|low", "sub_question": "...", "contested": false}])
```

Rules that matter:

- **`source` must match a source you recorded.** A claim citing anything else is rejected
  and returned to you. This makes a fabricated citation impossible to store rather than
  merely discouraged. If you find yourself reaching for a plausible-looking URL, that is
  the moment to go and fetch it instead.
- **`high` means a source states it directly and unambiguously.** Not "seems right", not
  "everyone knows". Inflating confidence corrupts the gate and produces a report that
  looks stronger than the evidence.
- **Extract fewer claims when sources are thin.** Manufacturing coverage is the worst
  outcome available to you.
- **Mark `contested` when sources disagree.** Disagreement is a finding.

---

## REFLECT

Read what you have against what was asked. Be honest about the gaps — concluding
prematurely produces a confidently wrong answer, which is worse than an incomplete one.

```
research_state(action="set_gaps", run_id=..., gaps=["<still unanswered>", ...])
research_state(action="next_round", run_id=...)
```

You may **close** a gap, or restate one still open. You may **not** invent a new topic.
An interesting tangent can become a claim bound to no sub-question, and it will be visible
as exactly that — but the objective does not grow to accommodate it.

---

## The gate

```
research_gate(run_id=...)
```

Three outcomes:

| Verdict | Do |
|---|---|
| **sufficient** | proceed to CROSS-CHECK |
| **insufficient, budget remains** | loop again — close the gaps it names |
| **insufficient, budget spent** | stop, synthesize what you have, **state the unmet criteria as limitations** |

The floor: ≥5 claims, ≥3 unique sources, ≥30% high-confidence, no open gaps.

**If you believe the evidence is adequate and the gate disagrees, the gate is right.**
Judging your own coverage from inside the loop is the failure mode it exists to catch.

The third outcome is not a failure. A run that hit its budget and says so, with limits
named, is honest work. A run that pretends is not.

---

## Mode-specific work

Two modes require more than the shared floor before they can stop. `research_gate`
enforces this — you cannot finish a discovery run with no ranked candidates.

### Investigation — adjudicate every contradiction

"Sources disagree" is where the work starts, not a finding. Every claim you recorded with
`contested: true` needs an adjudication:

```
research_state(action="resolve_contested", run_id=..., resolutions=[
  {"claim": "<exact text of the contested claim>",
   "assessment": "what they disagree about and which position the evidence better supports",
   "resolved": true}])
```

`claim` must match a claim actually marked contested — an adjudication of something never
in dispute would clear the gate without touching the real conflict, so it is rejected.

Set `resolved: false` when the conflict genuinely cannot be settled on the available
evidence. **That still counts.** Saying "this cannot be resolved, and here is why" is an
answer; quietly picking a side is not.

### Discovery — generate, rank, then actually evaluate

```
research_state(action="add_candidates", run_id=..., candidates=[
  {"name": "...", "score": 0.9, "rationale": "why this, why this score",
   "evaluated": true, "evaluation": "what testing it found"}])
```

Generation and ranking are usually separate passes — call again with the same `name` to
score or evaluate a candidate you already generated, and it updates in place.

The gate requires at least 3 candidates, **every** one scored, and at least one genuinely
evaluated. **Ranking is not evaluating.** A list of plausible molecules in score order,
none of them tested, is a hypothesis list — useful, but it is not what discovery mode
promises.

Where a candidate can be evaluated by real computation — molecular energy, combinatorial
optimization — do that rather than estimating.

---

### Simulation — argue each side at its strongest, then break it

The mode exists to argue against itself. Record every side, and for each one both the
best case that can be made for it and what is wrong with it:

```
research_state(action="add_positions", run_id=...,
               positions=[{"name": "Plaintiff", "argument": "<the strongest form>",
                           "weaknesses": ["<what undermines it>"]}])
```

The gate will not let the run stop while any position lacks an argument or a named
weakness, and it requires at least two. That is deliberate: a simulation that stops
early produces a summary splitting the difference, which is the one output this mode
must never give. Put the case you find least persuasive at its strongest anyway — if you
cannot, you do not yet understand it well enough to conclude against it.

### Planning — cost every option, name what would sink it

```
research_state(action="add_options", run_id=...,
               options=[{"name": "Build in-house", "cost": "<time, money, people>",
                         "risk": "<what would sink this>", "trade_offs": "..."}])
```

Two options minimum — one option is not a choice. The gate requires a cost and a risk on
each: an option with no cost is a wish, and one with no named risk has not been
stress-tested. "TBD" is not a cost; if you genuinely cannot cost it, say so as a
limitation rather than filling the field.

### Market — date everything, and say what would prove you wrong

Every claim needs `as_of` (when the figure was true) and `basis` (`measured` or
`projected`):

```
research_state(action="add_claims", run_id=..., claims=[{
    "claim": "Revenue grew 12% year on year",
    "source": "<retrieved source>", "confidence": "high",
    "as_of": "2026-Q2", "basis": "measured"}])
```

And before the run can conclude:

```
research_state(action="set_falsifier", run_id=...,
               falsifier="<what observation would prove this thesis wrong>")
```

A figure without a date is unreadable a month later. A projection presented as a
measurement is the failure mode of this entire genre, so the gate checks both. A thesis
nothing could falsify is not a finding.

**This is research synthesis, not investment advice**, and the report must say so. You
are assembling dated evidence and stating what would overturn it — not recommending that
anyone buy or sell anything.

---

## CROSS-CHECK

Only for claims marked `contested`. For each disagreement, say what the sources actually
disagree about and which position the evidence better supports — or that it is unresolved.
Do not manufacture a resolution the evidence does not carry.

Skip this step entirely when nothing is contested.

---

## SYNTHESIZE

Write the report from recorded claims only.

- Cite the source inline for every substantive statement
- Give remaining uncertainty **its own section** — a report that hides its gaps is worse
  than a shorter one that names them
- Introduce no facts that are not in the claims
- Match the output contract to the mode — `research_gate` returns it under
  `output_contract`, and every mode requires a limitations section

Then close the run:

```
research_state(action="finish", run_id=...)
```

### The deck

For anything the user will keep, share or print, produce a **single-page self-contained
HTML report**.

Get the numbers first:

```
research_deck(run_id=...)
```

That returns analytics computed from what you actually recorded — confidence mix, source
distribution grouped by origin, coverage per sub-question, contested points and their
resolutions, ranked candidates, claims per round — plus the mode's output contract, an
assembled limitations list, and the constraints the file must satisfy.

Use those numbers. Do not describe your own confidence in prose: *"4 of 11 claims are high
confidence, from 3 sources, and sub-question 2 has none"* is checkable; "the evidence is
reasonably strong" is not.

**Compose the deck for this run.** There is no template, no fixed section order, and you
should not invent one — a regulatory-exposure investigation and a molecular-discovery run
warrant different sections and different charts. A single mould forced over both is what
makes reports look generated.

The constraints come back from the tool. The short version: one self-contained file that
renders with **no network**, every claim showing its source and confidence, charts that
answer *"how solid is this?"*, **limitations as a section** rather than a footnote, and
print CSS that survives a PDF export.

### Saving it

Write the file with `write_file` and tell the user the path. **Local storage is the
default** — permanent, theirs, works offline, needs no account. Always do this.

To make it outlive the session — reopenable from another machine, or shareable — publish
it as well:

```
research_deck(action="publish", run_id=..., path="<the file you just wrote>")
```

| Tier | Retention |
|---|---|
| Local filesystem | permanent, always — the default |
| Published copy, no vault | **deleted 10 days after upload** |
| Published copy, account has a vault | permanent, and encrypted under the user's own key |

Which of the two applies is the account's, not something to predict: the response tells
you, in its `retention` field. **Repeat that sentence to the user at the moment you
publish.** A copy that silently disappears after ten days is worse than one that was
never offered.

The local file is unaffected either way, including when publishing fails.

`research_deck(action="list")` finds decks published earlier — including from other
sessions, which is the point of publishing at all.

---

## Worked shape

```
research_personas(action="list")                    # what lenses exist
research_personas(action="resolve", persona="legal", mode="investigation")
  → announce to the user, honour an override

research_state(action="start", question="...", mode="investigation",
               persona="legal", sub_questions=["A", "B", "C"])
  → run_id

# round 1
web_search / aiutils_rag_search / osint-investigation
research_state(action="record_sources", sources=[...])
research_state(action="add_claims", claims=[...])
research_state(action="set_gaps", gaps=["B unanswered"])
research_state(action="next_round")
research_gate() → insufficient: need 3 unique sources, have 2; 1 open gap

# round 2 — queries rebuilt from round-1 vocabulary, aimed at B
...
research_gate() → sufficient

# contested claims only
CROSS-CHECK → SYNTHESIZE
research_deck(run_id=...)          # analytics for the report
write_file(...)                    # the composed single-page HTML
research_state(action="finish")
```

## Resuming

A run survives interruption. `research_state(action="list")` shows recent runs; any
`run_id` picks up where it stopped, with its claims, sources and gaps intact. Resume
rather than restart.
