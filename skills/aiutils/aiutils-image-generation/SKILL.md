---
name: aiutils-image-generation
description: "Generate images through the AiUtils Developer API: pick a suitable model, confirm the DT cost, then render."
version: 1.0.0
author: Elidia Agent
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  tools: [aiutils_model_for_task, aiutils_model_info, aiutils_estimate, aiutils_generate, aiutils_generation_get]
metadata:
  elidia:
    tags: [image, generation, media, aiutils, dt]
    related_skills: [aiutils-video-generation, aiutils-audio-generation]
---

# Image generation (AiUtils)

Render images from a prompt using the AiUtils catalog — 1000+ models across vendors, billed in DT.

## When to use this skill

The user wants an image *produced*: "generate", "draw", "make me a picture of", "create a logo/illustration/mockup".

Not this skill when an image is an **input** — reading a screenshot or describing a photo is a vision task, so pick a vision-capable chat model instead (`aiutils_model_for_task` with `task_kind: vision`).

## How to work

1. **Choose a model.** Call `aiutils_model_for_task` with `task_kind: image_generation`. It returns ranked candidates with DT costs. Do not guess model ids — they change.
2. **Check the parameters.** `aiutils_model_info` returns the model's `input_schema` plus ready-made `required_prompts`. Ask the user for anything required that they have not supplied rather than inventing values — an invented aspect ratio or style is a silent wrong answer.
3. **Show the cost before spending.** `aiutils_estimate` returns the DT cost and the wallet balance. State it plainly for anything beyond a trivial render. Generation is billed; the user should not discover the price afterwards.
4. **Generate.** `aiutils_generate` returns immediately with a generation id — image work is asynchronous.
5. **Collect the result.** Poll `aiutils_generation_get` with that id until it reports completion, then give the user the download URL.

## Choosing well

- Cheapest is not always right. A throwaway thumbnail and a hero image warrant different models; say which you picked and why in one line.
- If the user names a style ("watercolour", "isometric", "film still"), put it in the prompt rather than hunting for a model that specialises in it.
- The credit guard refuses when the balance cannot cover the estimate. That is a real refusal, not a transient error — tell the user the shortfall rather than retrying.

## Failure modes worth naming

- **Insufficient DT** — report the estimate and the balance; do not retry.
- **Model rejects a parameter** — re-read `input_schema`; a value was likely out of its allowed enum.
- **Still processing** — keep polling; large renders take time. Do not start a second generation, which bills twice.
