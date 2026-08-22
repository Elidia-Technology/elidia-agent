import { JsonRpcGatewayClient } from '@elidia/shared'

import type {
  ActionResponse,
  ActionStatusResponse,
  AnalyticsResponse,
  AudioSpeakResponse,
  AudioTranscriptionResponse,
  AuxiliaryModelsResponse,
  ConfigSchemaResponse,
  CronJob,
  CronJobCreatePayload,
  CronJobUpdates,
  ElevenLabsVoicesResponse,
  EnvVarInfo,
  ElidiaConfig,
  ElidiaConfigRecord,
  LogsResponse,
  MessagingPlatformsResponse,
  MessagingPlatformTestResponse,
  MessagingPlatformUpdate,
  ModelAssignmentRequest,
  ModelAssignmentResponse,
  ModelInfoResponse,
  ModelOptionsResponse,
  OAuthPollResponse,
  OAuthProvidersResponse,
  OAuthStartResponse,
  OAuthSubmitResponse,
  PaginatedSessions,
  ProfileCreatePayload,
  ProfileSetupCommand,
  ProfileSoul,
  ProfilesResponse,
  SessionMessagesResponse,
  SessionSearchResponse,
  SkillInfo,
  StatusResponse,
  ToolsetConfig,
  ToolsetInfo
} from '@/types/elidia'

const DEFAULT_GATEWAY_REQUEST_TIMEOUT_MS = 30_000

export type {
  ActionResponse,
  ActionStatusResponse,
  AnalyticsDailyEntry,
  AnalyticsModelEntry,
  AnalyticsResponse,
  AnalyticsSkillEntry,
  AnalyticsSkillsSummary,
  AnalyticsTotals,
  AudioSpeakResponse,
  AudioTranscriptionResponse,
  AuxiliaryModelsResponse,
  ConfigFieldSchema,
  ConfigSchemaResponse,
  CronJob,
  CronJobCreatePayload,
  CronJobSchedule,
  CronJobUpdates,
  ElevenLabsVoice,
  ElevenLabsVoicesResponse,
  EnvVarInfo,
  GatewayReadyPayload,
  ElidiaConfig,
  ElidiaConfigRecord,
  LogsResponse,
  MessagingEnvVarInfo,
  MessagingHomeChannel,
  MessagingPlatformInfo,
  MessagingPlatformsResponse,
  MessagingPlatformTestResponse,
  MessagingPlatformUpdate,
  ModelAssignmentRequest,
  ModelAssignmentResponse,
  ModelInfoResponse,
  ModelOptionProvider,
  ModelOptionsResponse,
  PaginatedSessions,
  ProfileCreatePayload,
  ProfileInfo,
  ProfileSetupCommand,
  ProfileSoul,
  ProfilesResponse,
  RpcEvent,
  SessionCreateResponse,
  SessionInfo,
  SessionMessage,
  SessionMessagesResponse,
  SessionResumeResponse,
  SessionRuntimeInfo,
  SessionSearchResponse,
  SessionSearchResult,
  SkillInfo,
  StatusResponse,
  ToolsetConfig,
  ToolsetInfo
} from '@/types/elidia'

export class ElidiaGateway extends JsonRpcGatewayClient {
  constructor() {
    super({
      closedErrorMessage: 'Elidia gateway connection closed',
      connectErrorMessage: 'Could not connect to Elidia gateway',
      createRequestId: nextId => nextId,
      notConnectedErrorMessage: 'Elidia gateway is not connected',
      requestTimeoutMs: DEFAULT_GATEWAY_REQUEST_TIMEOUT_MS
    })
  }
}

export async function listSessions(
  limit = 40,
  minMessages = 0,
  archived: 'exclude' | 'include' | 'only' = 'exclude',
  order: 'created' | 'recent' = 'recent'
): Promise<PaginatedSessions> {
  const result = await window.elidiaDesktop.api<PaginatedSessions>({
    path: `/api/sessions?limit=${limit}&offset=0&min_messages=${Math.max(0, minMessages)}&archived=${archived}&order=${order}`
  })

  return {
    ...result,
    sessions: result.sessions.slice(0, limit),
    offset: 0
  }
}

export function setSessionArchived(id: string, archived: boolean): Promise<{ ok: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean }>({
    path: `/api/sessions/${encodeURIComponent(id)}`,
    method: 'PATCH',
    body: { archived }
  })
}

export function searchSessions(query: string): Promise<SessionSearchResponse> {
  return window.elidiaDesktop.api<SessionSearchResponse>({
    path: `/api/sessions/search?q=${encodeURIComponent(query)}`
  })
}

export function getSessionMessages(id: string): Promise<SessionMessagesResponse> {
  return window.elidiaDesktop.api<SessionMessagesResponse>({
    path: `/api/sessions/${encodeURIComponent(id)}/messages`
  })
}

export function deleteSession(id: string): Promise<{ ok: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean }>({
    path: `/api/sessions/${encodeURIComponent(id)}`,
    method: 'DELETE'
  })
}

export function renameSession(id: string, title: string): Promise<{ ok: boolean; title: string }> {
  return window.elidiaDesktop.api<{ ok: boolean; title: string }>({
    path: `/api/sessions/${encodeURIComponent(id)}`,
    method: 'PATCH',
    body: { title }
  })
}

export function getGlobalModelInfo(): Promise<ModelInfoResponse> {
  return window.elidiaDesktop.api<ModelInfoResponse>({
    path: '/api/model/info'
  })
}

export function getStatus(): Promise<StatusResponse> {
  return window.elidiaDesktop.api<StatusResponse>({
    path: '/api/status'
  })
}

export function getLogs(params: {
  component?: string
  file?: string
  level?: string
  lines?: number
}): Promise<LogsResponse> {
  const query = new URLSearchParams()

  if (params.file) {
    query.set('file', params.file)
  }

  if (typeof params.lines === 'number') {
    query.set('lines', String(params.lines))
  }

  if (params.level && params.level !== 'ALL') {
    query.set('level', params.level)
  }

  if (params.component && params.component !== 'all') {
    query.set('component', params.component)
  }

  const suffix = query.toString()

  return window.elidiaDesktop.api<LogsResponse>({
    path: suffix ? `/api/logs?${suffix}` : '/api/logs'
  })
}

export function getElidiaConfig(): Promise<ElidiaConfig> {
  return window.elidiaDesktop.api<ElidiaConfig>({
    path: '/api/config'
  })
}

export function getElidiaConfigRecord(): Promise<ElidiaConfigRecord> {
  return window.elidiaDesktop.api<ElidiaConfigRecord>({
    path: '/api/config'
  })
}

export function getElidiaConfigDefaults(): Promise<ElidiaConfigRecord> {
  return window.elidiaDesktop.api<ElidiaConfigRecord>({
    path: '/api/config/defaults'
  })
}

export function getElidiaConfigSchema(): Promise<ConfigSchemaResponse> {
  return window.elidiaDesktop.api<ConfigSchemaResponse>({
    path: '/api/config/schema'
  })
}

export function saveElidiaConfig(config: ElidiaConfigRecord): Promise<{ ok: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean }>({
    path: '/api/config',
    method: 'PUT',
    body: { config }
  })
}

export function getEnvVars(): Promise<Record<string, EnvVarInfo>> {
  return window.elidiaDesktop.api<Record<string, EnvVarInfo>>({
    path: '/api/env'
  })
}

export function setEnvVar(key: string, value: string): Promise<{ ok: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean }>({
    path: '/api/env',
    method: 'PUT',
    body: { key, value }
  })
}

export function validateProviderCredential(
  key: string,
  value: string
): Promise<{ ok: boolean; reachable: boolean; message: string }> {
  return window.elidiaDesktop.api<{ ok: boolean; reachable: boolean; message: string }>({
    path: '/api/providers/validate',
    method: 'POST',
    body: { key, value }
  })
}

export function deleteEnvVar(key: string): Promise<{ ok: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean }>({
    path: '/api/env',
    method: 'DELETE',
    body: { key }
  })
}

export function revealEnvVar(key: string): Promise<{ key: string; value: string }> {
  return window.elidiaDesktop.api<{ key: string; value: string }>({
    path: '/api/env/reveal',
    method: 'POST',
    body: { key }
  })
}

export function listOAuthProviders(): Promise<OAuthProvidersResponse> {
  return window.elidiaDesktop.api<OAuthProvidersResponse>({
    path: '/api/providers/oauth'
  })
}

export function startOAuthLogin(providerId: string): Promise<OAuthStartResponse> {
  return window.elidiaDesktop.api<OAuthStartResponse>({
    path: `/api/providers/oauth/${encodeURIComponent(providerId)}/start`,
    method: 'POST',
    body: {}
  })
}

export function submitOAuthCode(providerId: string, sessionId: string, code: string): Promise<OAuthSubmitResponse> {
  return window.elidiaDesktop.api<OAuthSubmitResponse>({
    path: `/api/providers/oauth/${encodeURIComponent(providerId)}/submit`,
    method: 'POST',
    body: { session_id: sessionId, code }
  })
}

export function pollOAuthSession(providerId: string, sessionId: string): Promise<OAuthPollResponse> {
  return window.elidiaDesktop.api<OAuthPollResponse>({
    path: `/api/providers/oauth/${encodeURIComponent(providerId)}/poll/${encodeURIComponent(sessionId)}`
  })
}

export function cancelOAuthSession(sessionId: string): Promise<{ ok: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean }>({
    path: `/api/providers/oauth/sessions/${encodeURIComponent(sessionId)}`,
    method: 'DELETE'
  })
}

export function getSkills(): Promise<SkillInfo[]> {
  return window.elidiaDesktop.api<SkillInfo[]>({
    path: '/api/skills'
  })
}

export function toggleSkill(name: string, enabled: boolean): Promise<{ ok: boolean; name: string; enabled: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean; name: string; enabled: boolean }>({
    path: '/api/skills/toggle',
    method: 'PUT',
    body: { name, enabled }
  })
}

export function getToolsets(): Promise<ToolsetInfo[]> {
  return window.elidiaDesktop.api<ToolsetInfo[]>({
    path: '/api/tools/toolsets'
  })
}

export function toggleToolset(
  name: string,
  enabled: boolean
): Promise<{ ok: boolean; name: string; enabled: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean; name: string; enabled: boolean }>({
    path: `/api/tools/toolsets/${encodeURIComponent(name)}`,
    method: 'PUT',
    body: { enabled }
  })
}

export function getToolsetConfig(name: string): Promise<ToolsetConfig> {
  return window.elidiaDesktop.api<ToolsetConfig>({
    path: `/api/tools/toolsets/${encodeURIComponent(name)}/config`
  })
}

export function selectToolsetProvider(
  name: string,
  provider: string
): Promise<{ ok: boolean; name: string; provider: string }> {
  return window.elidiaDesktop.api<{ ok: boolean; name: string; provider: string }>({
    path: `/api/tools/toolsets/${encodeURIComponent(name)}/provider`,
    method: 'PUT',
    body: { provider }
  })
}

export function getMessagingPlatforms(): Promise<MessagingPlatformsResponse> {
  return window.elidiaDesktop.api<MessagingPlatformsResponse>({
    path: '/api/messaging/platforms'
  })
}

export function updateMessagingPlatform(
  platformId: string,
  body: MessagingPlatformUpdate
): Promise<{ ok: boolean; platform: string }> {
  return window.elidiaDesktop.api<{ ok: boolean; platform: string }>({
    path: `/api/messaging/platforms/${encodeURIComponent(platformId)}`,
    method: 'PUT',
    body
  })
}

export function testMessagingPlatform(platformId: string): Promise<MessagingPlatformTestResponse> {
  return window.elidiaDesktop.api<MessagingPlatformTestResponse>({
    path: `/api/messaging/platforms/${encodeURIComponent(platformId)}/test`,
    method: 'POST'
  })
}

export function getCronJobs(): Promise<CronJob[]> {
  return window.elidiaDesktop.api<CronJob[]>({
    path: '/api/cron/jobs'
  })
}

export function getCronJob(jobId: string): Promise<CronJob> {
  return window.elidiaDesktop.api<CronJob>({
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}`
  })
}

export function createCronJob(body: CronJobCreatePayload): Promise<CronJob> {
  return window.elidiaDesktop.api<CronJob>({
    path: '/api/cron/jobs',
    method: 'POST',
    body
  })
}

export function updateCronJob(jobId: string, updates: CronJobUpdates): Promise<CronJob> {
  return window.elidiaDesktop.api<CronJob>({
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}`,
    method: 'PUT',
    body: { updates }
  })
}

export function pauseCronJob(jobId: string): Promise<CronJob> {
  return window.elidiaDesktop.api<CronJob>({
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}/pause`,
    method: 'POST'
  })
}

export function resumeCronJob(jobId: string): Promise<CronJob> {
  return window.elidiaDesktop.api<CronJob>({
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}/resume`,
    method: 'POST'
  })
}

export function triggerCronJob(jobId: string): Promise<CronJob> {
  return window.elidiaDesktop.api<CronJob>({
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}/trigger`,
    method: 'POST'
  })
}

export function deleteCronJob(jobId: string): Promise<{ ok: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean }>({
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}`,
    method: 'DELETE'
  })
}

export function getProfiles(): Promise<ProfilesResponse> {
  return window.elidiaDesktop.api<ProfilesResponse>({
    path: '/api/profiles'
  })
}

export function createProfile(body: ProfileCreatePayload): Promise<{ name: string; ok: boolean; path: string }> {
  return window.elidiaDesktop.api<{ name: string; ok: boolean; path: string }>({
    path: '/api/profiles',
    method: 'POST',
    body
  })
}

export function renameProfile(name: string, newName: string): Promise<{ name: string; ok: boolean; path: string }> {
  return window.elidiaDesktop.api<{ name: string; ok: boolean; path: string }>({
    path: `/api/profiles/${encodeURIComponent(name)}`,
    method: 'PATCH',
    body: { new_name: newName }
  })
}

export function deleteProfile(name: string): Promise<{ ok: boolean; path: string }> {
  return window.elidiaDesktop.api<{ ok: boolean; path: string }>({
    path: `/api/profiles/${encodeURIComponent(name)}`,
    method: 'DELETE'
  })
}

export function getProfileSoul(name: string): Promise<ProfileSoul> {
  return window.elidiaDesktop.api<ProfileSoul>({
    path: `/api/profiles/${encodeURIComponent(name)}/soul`
  })
}

export function updateProfileSoul(name: string, content: string): Promise<{ ok: boolean }> {
  return window.elidiaDesktop.api<{ ok: boolean }>({
    path: `/api/profiles/${encodeURIComponent(name)}/soul`,
    method: 'PUT',
    body: { content }
  })
}

export function getProfileSetupCommand(name: string): Promise<ProfileSetupCommand> {
  return window.elidiaDesktop.api<ProfileSetupCommand>({
    path: `/api/profiles/${encodeURIComponent(name)}/setup-command`
  })
}

export function getUsageAnalytics(days = 30): Promise<AnalyticsResponse> {
  return window.elidiaDesktop.api<AnalyticsResponse>({
    path: `/api/analytics/usage?days=${Math.max(1, Math.floor(days))}`
  })
}

export function getGlobalModelOptions(): Promise<ModelOptionsResponse> {
  return window.elidiaDesktop.api<ModelOptionsResponse>({
    path: '/api/model/options'
  })
}

export interface RecommendedDefaultModel {
  provider: string
  model: string
  /** True/false for Elidia (free vs paid tier); null for other providers. */
  free_tier: boolean | null
}

// Recommended default model for a freshly-authenticated provider. Mirrors the
// curation `elidia model` does — for Elidia it honors the free/paid tier so a
// free user gets a free model instead of a paid default.
export function getRecommendedDefaultModel(provider: string): Promise<RecommendedDefaultModel> {
  return window.elidiaDesktop.api<RecommendedDefaultModel>({
    path: `/api/model/recommended-default?provider=${encodeURIComponent(provider)}`
  })
}

export function setGlobalModel(
  provider: string,
  model: string
): Promise<{ ok: boolean; provider: string; model: string }> {
  return window.elidiaDesktop.api<{ ok: boolean; provider: string; model: string }>({
    path: '/api/model/set',
    method: 'POST',
    body: {
      scope: 'main',
      provider,
      model
    }
  })
}

export function getAuxiliaryModels(): Promise<AuxiliaryModelsResponse> {
  return window.elidiaDesktop.api<AuxiliaryModelsResponse>({
    path: '/api/model/auxiliary'
  })
}

export function setModelAssignment(body: ModelAssignmentRequest): Promise<ModelAssignmentResponse> {
  return window.elidiaDesktop.api<ModelAssignmentResponse>({
    path: '/api/model/set',
    method: 'POST',
    body
  })
}

export function restartGateway(): Promise<ActionResponse> {
  return window.elidiaDesktop.api<ActionResponse>({
    path: '/api/gateway/restart',
    method: 'POST'
  })
}

export function updateElidia(): Promise<ActionResponse> {
  return window.elidiaDesktop.api<ActionResponse>({
    path: '/api/elidia/update',
    method: 'POST'
  })
}

export function getActionStatus(name: string, lines = 200): Promise<ActionStatusResponse> {
  return window.elidiaDesktop.api<ActionStatusResponse>({
    path: `/api/actions/${encodeURIComponent(name)}/status?lines=${Math.max(1, lines)}`
  })
}

export function transcribeAudio(dataUrl: string, mimeType?: string): Promise<AudioTranscriptionResponse> {
  return window.elidiaDesktop.api<AudioTranscriptionResponse>({
    path: '/api/audio/transcribe',
    method: 'POST',
    body: {
      data_url: dataUrl,
      mime_type: mimeType
    }
  })
}

export function speakText(text: string): Promise<AudioSpeakResponse> {
  return window.elidiaDesktop.api<AudioSpeakResponse>({
    path: '/api/audio/speak',
    method: 'POST',
    body: { text }
  })
}

export function getElevenLabsVoices(): Promise<ElevenLabsVoicesResponse> {
  return window.elidiaDesktop.api<ElevenLabsVoicesResponse>({
    path: '/api/audio/elevenlabs/voices'
  })
}
