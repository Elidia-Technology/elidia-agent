---
name: aiutils-medical-research
description: "Summarise medical and clinical literature with evidence discipline. Summarises research; does not diagnose."
version: 1.0.0
author: Elidia Agent
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  tools: [aiutils_tool_genres, aiutils_tool_execute, aiutils_rag_search, aiutils_model_for_task]
metadata:
  elidia:
    tags: [medical, clinical, research, evidence, pubmed, aiutils]
    related_skills: [aiutils-knowledge-base, aiutils-legal-analysis]
---

# Medical research (AiUtils)

Evidence-led summarisation of clinical and biomedical literature.

## The boundary, first

**This skill summarises research. It does not diagnose, and it does not advise on treatment.**

When a user describes symptoms and asks what they have, say plainly that you cannot diagnose and that this needs a clinician — then, if useful, summarise what the literature says about the condition they named. Redirecting is not unhelpful; a confident non-diagnosis dressed as one is the harm.

Urgent presentations — chest pain, stroke signs, anaphylaxis, self-harm — get one response: seek immediate medical care. Do not lead with literature.

## When to use this skill

"What does the research say about X", "summarise trials for Y", "recent findings on Z", "what's the evidence for this treatment".

## How to work

1. **Check the user's own material first** — `aiutils_rag_search` if they have ingested papers or notes. Their documents beat generic recall.
2. **Find a research tool** — `aiutils_tool_genres` lists what the portal offers; `aiutils_tool_execute` runs one. Use the tools rather than recalling literature from memory, which is where fabricated citations come from.
3. **Pick a capable model** — `aiutils_model_for_task` with `task_kind: text_reasoning`. Clinical summarisation is not a place to economise.

## Evidence discipline

- **Cite identifiers, never invent them.** A PubMed ID or DOI you are not certain of is worse than none — say "I don't have the identifier" instead.
- **Distinguish evidence strength.** A systematic review, an RCT, a cohort study and a case report are not interchangeable. Name which you are quoting.
- **Flag preliminary and contested findings** rather than presenting them as settled. Say when results conflict.
- **Note sample size and population** when they limit generalisability — a result in 40 adults is not a result in children.
- **Say when you do not know.** Absence of evidence is a finding; padding around it is not.
