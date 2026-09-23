---
name: aiutils-video-generation
description: "Generate video through the AiUtils Developer API — model selection, cost confirmation, and asynchronous collection."
version: 1.0.0
author: Elidia Agent
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  tools: [aiutils_model_for_task, aiutils_model_info, aiutils_estimate, aiutils_generate, aiutils_generation_get]
metadata:
  elidia:
    tags: [video, generation, media, aiutils, dt]
    related_skills: [aiutils-image-generation, aiutils-audio-generation]
---

# Video generation (AiUtils)

Produce video from a text prompt or a source image, billed in DT.

## When to use this skill

The user wants moving output: "make a video", "animate this image", "a 5-second clip of…".

## How to work

1. `aiutils_model_for_task` with `task_kind: video_generation` for ranked candidates.
2. `aiutils_model_info` for the chosen model's `input_schema`. Video models vary far more than image models — duration limits, frame rates, aspect ratios and whether an input image is accepted all differ. Read the schema; do not assume.
3. `aiutils_estimate`, then **state the cost**. Video is the most expensive category on the platform; a user surprised by the bill has been failed.
4. `aiutils_generate`, then poll `aiutils_generation_get`.

## Cost discipline

Video generation is materially more expensive than image, and cost usually scales with duration and resolution. Two habits follow:

- **Confirm before rendering long or high-resolution output.** Say the estimate and wait, rather than assuming a request for "a video" licenses the most expensive interpretation.
- **Suggest a short test render first** when the user is iterating on a prompt. One cheap pass to check the direction beats three expensive ones.

## Failure modes worth naming

- **Duration exceeds the model's limit** — the schema states the maximum; propose the nearest valid value rather than silently truncating.
- **Source image rejected** — image-to-video models often constrain dimensions or aspect ratio.
- **Long processing** — video takes minutes, not seconds. Keep polling; never launch a second generation, which bills twice.
