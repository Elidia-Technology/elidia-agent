---
name: aiutils-audio-generation
description: "Generate speech, music and sound effects through the AiUtils Developer API."
version: 1.0.0
author: Elidia Agent
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  tools: [aiutils_model_for_task, aiutils_model_info, aiutils_estimate, aiutils_generate, aiutils_generation_get]
metadata:
  elidia:
    tags: [audio, speech, music, tts, generation, aiutils, dt]
    related_skills: [aiutils-image-generation, aiutils-video-generation]
---

# Audio generation (AiUtils)

Speech, music and sound effects as output, billed in DT.

## When to use this skill

"Read this aloud", "generate a voiceover", "compose a short track", "make a whoosh sound effect".

Audio *input* — transcription — is a different task. This skill covers audio as output only.

## How to work

1. `aiutils_model_for_task` with `task_kind: audio_generation`.
2. `aiutils_model_info` for the schema. The three sub-kinds diverge sharply:
   - **Speech/TTS** — voice id, language, speed, sometimes emotion
   - **Music** — genre, duration, instrumentation, sometimes a lyrics field
   - **Sound effects** — usually a short prompt and a duration
   Pick a model that matches the sub-kind; a music model asked to read a paragraph will not do it.
3. `aiutils_estimate`, state the cost, then `aiutils_generate` and poll.

## Getting good results

- **Voice selection is usually an enum.** Read the schema and offer the user real options rather than describing a voice in prose and hoping.
- **For TTS, send the text verbatim.** Do not paraphrase, re-punctuate or "improve" what the user wants spoken — punctuation drives pacing, and altering it changes the delivery.
- **Long text may exceed a per-request limit.** Split on sentence boundaries, never mid-sentence, and tell the user you did.

## Failure modes worth naming

- **Text too long** — split and say so.
- **Voice id not recognised** — the enum in `input_schema` is authoritative.
- **Insufficient DT** — report the estimate and balance; do not retry.
