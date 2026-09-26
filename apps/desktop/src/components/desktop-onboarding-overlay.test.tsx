import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const setEnvVar = vi.fn()
const startOAuthLogin = vi.fn()
const getGlobalModelOptions = vi.fn()

vi.mock('@/elidia', () => ({
  setEnvVar: (key: string, value: string) => setEnvVar(key, value),
  startOAuthLogin: (providerId: string) => startOAuthLogin(providerId),
  getGlobalModelOptions: () => getGlobalModelOptions(),
  listOAuthProviders: vi.fn(),
  submitOAuthCode: vi.fn(),
  pollOAuthSession: vi.fn(),
  cancelOAuthSession: vi.fn(),
  getRecommendedDefaultModel: vi.fn(),
  setModelAssignment: vi.fn()
}))

// Notifications hit nanostores/timers we don't care about here.
vi.mock('@/store/notifications', () => ({
  notify: vi.fn(),
  notifyError: vi.fn()
}))

import { $desktopOnboarding, type DesktopOnboardingState, type OnboardingContext } from '@/store/onboarding'
import type { OAuthProvider } from '@/types/elidia'

import { Picker } from './desktop-onboarding-overlay'

function provider(id: string, name = id): OAuthProvider {
  return {
    cli_command: `elidia login ${id}`,
    docs_url: `https://example.com/${id}`,
    flow: 'pkce',
    id,
    name,
    status: { logged_in: false }
  }
}

function setProviders(providers: OAuthProvider[], mode: DesktopOnboardingState['mode'] = 'oauth') {
  $desktopOnboarding.set({
    configured: false,
    flow: { status: 'idle' },
    mode,
    providers,
    reason: null,
    requested: false,
    manual: false
  } satisfies DesktopOnboardingState)
}

const ctx: OnboardingContext = { requestGateway: async () => undefined as never }

beforeEach(() => {
  // getGlobalModelOptions backs completeWithModelConfirm's default-model
  // lookup after a key/OAuth connect succeeds. An empty provider list makes
  // that lookup a no-op (no default to confirm), which is all these tests
  // need — they assert on the connect call itself, not the post-connect
  // model-confirmation step.
  getGlobalModelOptions.mockResolvedValue({ providers: [] })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  $desktopOnboarding.set({
    configured: null,
    flow: { status: 'idle' },
    mode: 'oauth',
    providers: null,
    reason: null,
    requested: false,
    manual: false
  })
})

describe('onboarding Picker', () => {
  it('features Elidia Portal as a recommended key-entry card, with other OAuth providers collapsed behind a disclosure', () => {
    setProviders([provider('anthropic', 'Anthropic Claude'), provider('openai-codex', 'OpenAI Codex / ChatGPT')])
    render(<Picker ctx={ctx} />)

    expect(screen.getByText('Elidia Portal')).toBeTruthy()
    expect(screen.getByText('Recommended')).toBeTruthy()
    expect(screen.queryByText('Anthropic Claude')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Other providers' }))

    expect(screen.getByText('Anthropic Claude')).toBeTruthy()
    expect(screen.getByText('OpenAI Codex / ChatGPT')).toBeTruthy()
    expect(screen.getByText("Another provider's API key")).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Collapse' })).toBeTruthy()
  })

  it('falls back straight to the API-key form, with AiUtils preselected, when no OAuth providers are offered', () => {
    setProviders([], 'apikey')
    render(<Picker ctx={ctx} />)

    // No OAuth providers to go back to.
    expect(screen.queryByText('Back to sign in')).toBeNull()
    // AiUtils is API_KEY_OPTIONS[0], so it's selected by default.
    expect(screen.getByText('Elidia Portal (AiUtils)')).toBeTruthy()
    expect(screen.getByText(/billed to your AiUtils credits/)).toBeTruthy()
    const docsLink = screen.getByRole('link', { name: /Get a key/ })
    expect(docsLink.getAttribute('href')).toBe('https://developer.aiutils.io/')
  })

  it('opens the AiUtils key form from the featured card, without starting OAuth', () => {
    setProviders([provider('anthropic', 'Anthropic Claude')])
    render(<Picker ctx={ctx} />)

    fireEvent.click(screen.getByRole('button', { name: /Elidia Portal/ }))

    expect(startOAuthLogin).not.toHaveBeenCalled()
    // Landed on the API-key form with AiUtils preselected.
    expect(screen.getByText('Elidia Portal (AiUtils)')).toBeTruthy()
    expect(screen.getByPlaceholderText('ak-dev-…')).toBeTruthy()
  })

  it('rejects an AiUtils key that does not start with ak-dev-', async () => {
    setProviders([], 'apikey')
    render(<Picker ctx={ctx} />)

    fireEvent.change(screen.getByPlaceholderText('ak-dev-…'), { target: { value: 'sk-not-a-dev-key' } })
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

    expect(await screen.findByText(/start with "ak-dev-"/)).toBeTruthy()
    expect(setEnvVar).not.toHaveBeenCalled()
  })

  it('saves a valid ak-dev- AiUtils key under AIUTILS_API_KEY', async () => {
    setProviders([], 'apikey')
    render(<Picker ctx={ctx} />)

    fireEvent.change(screen.getByPlaceholderText('ak-dev-…'), { target: { value: 'ak-dev-abc123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => expect(setEnvVar).toHaveBeenCalledWith('AIUTILS_API_KEY', 'ak-dev-abc123'))
  })
})
