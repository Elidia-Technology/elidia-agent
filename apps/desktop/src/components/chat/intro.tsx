import { useState } from 'react'

import introCopyJsonl from './intro-copy.jsonl?raw'

type IntroCopy = {
  headline: string
  body: string
}

type IntroCopyRecord = IntroCopy & {
  personality: string
}

export type IntroProps = {
  personality?: string
  seed?: number
}

const NEUTRAL_PERSONALITIES = new Set(['', 'default', 'none', 'neutral'])

const FALLBACK_COPY: IntroCopy[] = [
  {
    headline: 'What are we moving today?',
    body: "Send a bug, branch, plan, or rough idea. I'll inspect the repo and turn it into the next concrete step."
  },
  {
    headline: "What's on your mind?",
    body: "Bring the code, question, or stuck part. I'll read the room before making changes."
  },
  {
    headline: 'What should Elidia look at?',
    body: "Send the task, failing path, or half-formed plan. I'll help turn it into action."
  },
  {
    headline: 'Where should we start?',
    body: "Bring the problem, goal, or file. I'll inspect first and keep the next step concrete."
  },
  {
    headline: 'What needs attention?',
    body: "Send the context you have. I'll help sort it into a plan or a fix."
  }
]

function normalizeKey(value?: string): string {
  return (value || '').trim().toLowerCase()
}

function titleize(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function isIntroCopyRecord(value: unknown): value is IntroCopyRecord {
  if (!value || typeof value !== 'object') {
    return false
  }

  const record = value as Record<string, unknown>

  return (
    typeof record.personality === 'string' &&
    typeof record.headline === 'string' &&
    typeof record.body === 'string' &&
    Boolean(record.personality.trim()) &&
    Boolean(record.headline.trim()) &&
    Boolean(record.body.trim())
  )
}

function parseIntroCopy(raw: string): Record<string, IntroCopy[]> {
  const byPersonality: Record<string, IntroCopy[]> = {}

  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim()

    if (!trimmed) {
      continue
    }

    try {
      const parsed: unknown = JSON.parse(trimmed)

      if (!isIntroCopyRecord(parsed)) {
        continue
      }

      const key = normalizeKey(parsed.personality)
      byPersonality[key] ??= []
      byPersonality[key].push({
        headline: parsed.headline.trim(),
        body: parsed.body.trim()
      })
    } catch {
      // Bad generated copy should not break the whole desktop app.
    }
  }

  return byPersonality
}

const INTRO_COPY_BY_PERSONALITY = parseIntroCopy(introCopyJsonl)

function neutralCopy(): IntroCopy[] {
  return INTRO_COPY_BY_PERSONALITY.none || INTRO_COPY_BY_PERSONALITY.default || FALLBACK_COPY
}

function fallbackCopyForPersonality(personalityKey: string): IntroCopy[] {
  if (NEUTRAL_PERSONALITIES.has(personalityKey)) {
    return neutralCopy()
  }

  const label = titleize(personalityKey)

  return [
    {
      headline: `${label} mode is on. What should we work on?`,
      body: "Send the task, file, or rough idea. I'll use your configured voice and keep the work grounded in this repo."
    },
    {
      headline: `What does ${label} Elidia need to see?`,
      body: "Bring the context or the stuck part. I'll adapt to your configured personality."
    },
    {
      headline: `${label} mode is ready.`,
      body: "Send the problem, file, or idea. I'll follow the personality you've configured."
    },
    {
      headline: `What should ${label} Elidia tackle?`,
      body: "Drop the task here. I'll keep the work grounded in the repo."
    },
    {
      headline: 'Where should we begin?',
      body: `Give me the context and I'll answer in ${label} mode.`
    }
  ]
}

function pickCopy(copies: IntroCopy[], seed = 0): IntroCopy {
  return copies[Math.abs(seed) % copies.length] || FALLBACK_COPY[0]
}

function resolveCopy(personality?: string, seed?: number): IntroCopy {
  const personalityKey = normalizeKey(personality)

  const copies = NEUTRAL_PERSONALITIES.has(personalityKey)
    ? INTRO_COPY_BY_PERSONALITY[personalityKey] || neutralCopy()
    : INTRO_COPY_BY_PERSONALITY[personalityKey] || fallbackCopyForPersonality(personalityKey)

  return pickCopy(copies, seed)
}

// Two variants, switched by CSS rather than by reading the theme in JS. The
// source banner's wordmark is near-black: right on the light skins, all but
// invisible on the dark ones. `applyTheme` sets the `.dark` class from the
// rendered background luminance — not from the requested mode, which can
// disagree — so a `dark:` variant tracks what the user actually sees.
//
// Both are in the bundle either way; at ~100KB each and served locally, that
// costs nothing next to a wordmark that disappears on half the themes.
const BANNER_LIGHT = 'banner.png'
const BANNER_DARK = 'banner-dark.png'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

export function Intro({ personality, seed }: IntroProps) {
  const [mountSeed] = useState(() => Math.floor(Math.random() * 100000))
  const copy = resolveCopy(personality, mountSeed + (seed ?? 0))

  return (
    <div
      className="pointer-events-none flex w-full min-w-0 flex-col items-center justify-center px-3 py-6 text-center text-muted-foreground sm:px-6 lg:px-8"
      data-slot="aui_intro"
    >
      <div className="w-full min-w-0">
        {/* One alt text on the visible pair, not two — a screen reader should
            hear the product name once, not once per theme variant. */}
        <img
          alt="Elidia Agent"
          className="mx-auto mb-4 block h-auto w-4/5 max-w-[26rem] select-none dark:hidden"
          data-slot="aui_intro-banner"
          draggable={false}
          src={assetPath(BANNER_LIGHT)}
        />
        <img
          alt=""
          aria-hidden="true"
          className="mx-auto mb-4 hidden h-auto w-4/5 max-w-[26rem] select-none dark:block"
          data-slot="aui_intro-banner-dark"
          draggable={false}
          src={assetPath(BANNER_DARK)}
        />

        <p className="m-0 text-center leading-normal tracking-tight">{copy.body}</p>
      </div>
    </div>
  )
}
