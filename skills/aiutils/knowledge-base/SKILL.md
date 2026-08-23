---
name: aiutils-knowledge-base
description: "Store and retrieve the user's own documents in the AiUtils RAG knowledge base. Free — retrieval runs on local models."
version: 1.0.0
author: Elidia Agent
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  tools: [aiutils_rag_ingest, aiutils_rag_search, aiutils_rag_collections, aiutils_rag_documents]
metadata:
  elidia:
    tags: [rag, knowledge, memory, search, documents, aiutils]
    related_skills: [aiutils-medical-research, aiutils-legal-analysis]
---

# Knowledge base (AiUtils RAG)

Give the agent durable memory of the user's own material. Anything ingested stays searchable across sessions — the difference between being re-told context every time and being able to look it up.

**Free.** Embeddings run on AiUtils' own hardware, so ingest and search cost nothing. Only the model call you make *with* the retrieved passages is billed.

## When to use this skill

- The user shares reference material worth keeping: documentation, notes, transcripts, specs, meeting minutes.
- A question likely depends on their own documents rather than general knowledge — **search before answering**, do not guess.
- The user asks what has been stored.

## How to work

**Storing.** `aiutils_rag_ingest` with a `collection`, the `content`, and a `title`. Choose a collection name that groups sensibly — `project-docs`, `meeting-notes`, `handbook`. Re-ingesting identical content is a no-op and reports `skipped: true`, so re-running a sync is safe.

**Retrieving.** `aiutils_rag_search` returns **passages, not an answer** — you write the answer from them. Set `rerank: true` when precision matters more than a moment of latency; it is also free.

**Orienting.** `aiutils_rag_collections` shows what exists with sizes; `aiutils_rag_documents` lists what has been ingested.

## Answering from retrieved passages

- **Cite what you used.** Name the document or collection a claim came from, so the user can check it.
- **Empty results mean one of two things.** Either nothing matched, or nothing was ever ingested. `aiutils_rag_collections` distinguishes them — never conclude "you have no document about X" from an empty search alone.
- **Do not pad with general knowledge unmarked.** If the passages do not answer the question, say so, then answer separately from your own knowledge and label it as such. Blending the two is how a confident wrong answer gets attributed to the user's own documents.
- **Passages may be truncated.** Long chunks come back shortened with `truncated: true`; if the cut-off matters, search again more narrowly.

## Choosing collections

One collection per coherent body of material. Searching without a `collection` covers everything the user owns, which is right for open questions and wrong when two projects use the same vocabulary — scope it then.
