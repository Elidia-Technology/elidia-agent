---
name: aiutils-legal-analysis
description: "Structured legal analysis of contracts, compliance and regulation. Analysis, not legal advice."
version: 1.0.0
author: Elidia Agent
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  tools: [aiutils_tool_genres, aiutils_tool_execute, aiutils_rag_search, aiutils_rag_ingest, aiutils_model_for_task]
metadata:
  elidia:
    tags: [legal, contracts, compliance, regulation, aiutils]
    related_skills: [aiutils-knowledge-base, aiutils-medical-research]
---

# Legal analysis (AiUtils)

Structured analysis of contracts, policies, compliance obligations and regulation.

## The boundary, first

**This is analysis, not legal advice, and it does not create a solicitor–client relationship.**

Say so when a user asks what they *should* do, or is about to rely on an answer for a decision with real consequence — signing, filing, terminating, disputing. Then give the analysis. The disclaimer earns its place by being specific about *when* a qualified lawyer is needed, not by being appended to everything.

## When to use this skill

"Review this contract", "what does this clause mean", "are we compliant with X", "what are the obligations under Y".

## How to work

1. **Ingest the document** — `aiutils_rag_ingest` for anything long, then `aiutils_rag_search` to pull the relevant clauses. Reasoning over retrieved clauses beats holding a 60-page agreement in context.
2. **Check available tools** — `aiutils_tool_genres` for contract-intelligence or compliance tooling; run via `aiutils_tool_execute`.
3. **Use a strong model** — `aiutils_model_for_task` with `task_kind: text_reasoning`.

## Structure the analysis

Unless the user asks otherwise:

**Facts** — what the document actually says, quoted where wording matters
**Framework** — the governing law, regulation or standard, and which jurisdiction
**Analysis** — how the framework applies to these facts
**Recommendations** — what follows, and what needs a qualified lawyer

## Rigour

- **Never fabricate case law, statutes, section numbers or citations.** If you cannot name the authority, say the principle is your understanding and name nothing.
- **Jurisdiction changes the answer.** Ask which applies when it is not stated; do not silently assume one.
- **Quote the operative wording** for anything consequential. A paraphrase of an indemnity clause is not an indemnity clause.
- **Name what is absent.** A missing limitation-of-liability or termination clause is often more significant than the clauses present.
- **Separate what the text says from what is customary.** Both are useful; conflating them is not.
