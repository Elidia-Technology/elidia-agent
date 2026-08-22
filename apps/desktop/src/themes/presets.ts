/**
 * Built-in desktop themes. Names match the CLI skins / dashboard presets.
 * Add new themes here — no code changes needed elsewhere.
 */

import type { DesktopTheme, DesktopThemeTypography } from './types'

const SYSTEM_SANS =
  '"Segoe WPC", "Segoe UI", -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui, sans-serif'

const SYSTEM_MONO = '"Cascadia Code", "JetBrains Mono", "SF Mono", ui-monospace, Menlo, Monaco, Consolas, monospace'

export const DEFAULT_TYPOGRAPHY: DesktopThemeTypography = { fontSans: SYSTEM_SANS, fontMono: SYSTEM_MONO }

const ELIDIA_BLUE = '#0053FD'
const PSYCHE_BLUE = '#1540B1'
const PSYCHE_WARM = '#FFE6CB'

// Elidia brand gold, from the CLI `default` skin (skin_engine.py): gold title,
// amber accent, bronze border.
const ELIDIA_GOLD = '#FFD700'
const ELIDIA_AMBER = '#FFBF00'
const ELIDIA_BRONZE = '#CD7F32'

const elidiaTint = (pct: number) => `color-mix(in srgb, ${ELIDIA_BLUE} ${pct}%, #FFFFFF)`
const elidiaTintTransparent = (pct: number) => `color-mix(in srgb, ${ELIDIA_BLUE} ${pct}%, transparent)`

/**
 * Elidia — canonical Elidia desktop identity. Gold primary (#FFBF00 amber /
 * #CD7F32 bronze), with the recent Elidia blue retained as the secondary /
 * accent tier. Mirrors the CLI `default` skin ("gold and kawaii") on a warm
 * paper light ground, and keeps the deep-blue dark ground with gold accents.
 */
export const elidiaTheme: DesktopTheme = {
  name: 'elidia',
  label: 'Elidia',
  description: 'Gold primary, blue secondary — the canonical Elidia brand',
  colors: {
    background: '#FBF6EC',
    foreground: '#2B2620',
    card: '#FFFFFF',
    cardForeground: '#2B2620',
    muted: '#F2EAD8',
    mutedForeground: '#8A7B64',
    popover: '#FFFFFF',
    popoverForeground: '#2B2620',
    primary: ELIDIA_AMBER,
    primaryForeground: '#2B2620',
    secondary: elidiaTint(7),
    secondaryForeground: '#242432',
    accent: elidiaTint(10),
    accentForeground: '#202030',
    border: '#E4D9BE',
    input: '#E4D9BE',
    ring: ELIDIA_AMBER,
    midground: ELIDIA_BRONZE,
    composerRing: ELIDIA_BRONZE,
    destructive: '#C72E4D',
    destructiveForeground: '#FFFFFF',
    sidebarBackground: '#F3EEDF',
    sidebarBorder: '#E4D9BE',
    userBubble: '#F2EAD8',
    userBubbleBorder: '#E4D9BE'
  },
  darkColors: {
    background: '#0D2F86',
    foreground: '#FFF8DC',
    card: '#12378F',
    cardForeground: '#FFF8DC',
    muted: '#183F9A',
    mutedForeground: '#B5C7F3',
    popover: '#123A96',
    popoverForeground: '#FFF8DC',
    primary: ELIDIA_GOLD,
    primaryForeground: '#1A1A2E',
    secondary: '#1B45A4',
    secondaryForeground: '#E0E8FF',
    accent: PSYCHE_BLUE,
    accentForeground: '#F0F4FF',
    border: '#3158AD',
    input: '#0B2566',
    ring: ELIDIA_GOLD,
    midground: ELIDIA_AMBER,
    composerRing: ELIDIA_GOLD,
    destructive: '#C0473A',
    destructiveForeground: '#FEF2F2',
    sidebarBackground: '#09286F',
    sidebarBorder: '#234A9C',
    userBubble: '#143B91',
    userBubbleBorder: '#3A63BD'
  },
  typography: {
    fontSans: SYSTEM_SANS,
    fontMono: `"Courier Prime", ${SYSTEM_MONO}`,
    fontUrl: 'https://fonts.googleapis.com/css2?family=Courier+Prime:wght@400;700&display=swap'
  }
}

/** Deep blue-violet with cool accents. Matches the dashboard midnight theme. */
export const midnightTheme: DesktopTheme = {
  name: 'midnight',
  label: 'Midnight',
  description: 'Deep blue-violet with cool accents',
  colors: {
    background: '#08081c',
    foreground: '#ddd6ff',
    card: '#0d0d28',
    cardForeground: '#ddd6ff',
    muted: '#13133a',
    mutedForeground: '#7c7ab0',
    popover: '#0f0f2e',
    popoverForeground: '#ddd6ff',
    primary: '#ddd6ff',
    primaryForeground: '#08081c',
    secondary: '#1a1a4a',
    secondaryForeground: '#c4bff0',
    accent: '#1a1a44',
    accentForeground: '#d0c8ff',
    border: '#1e1e52',
    input: '#1e1e52',
    ring: '#8b80e8',
    midground: '#8b80e8',
    destructive: '#b03060',
    destructiveForeground: '#fef2f2',
    sidebarBackground: '#06061a',
    sidebarBorder: '#12123a',
    userBubble: '#14143a',
    userBubbleBorder: '#242466'
  },
  typography: {
    fontMono: `"JetBrains Mono", ${SYSTEM_MONO}`,
    fontUrl: 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap'
  }
}

/** Warm crimson and bronze — forge vibes. Matches the CLI ares skin. */
export const emberTheme: DesktopTheme = {
  name: 'ember',
  label: 'Ember',
  description: 'Warm crimson and bronze — forge vibes',
  colors: {
    background: '#160800',
    foreground: '#ffd8b0',
    card: '#1e0e04',
    cardForeground: '#ffd8b0',
    muted: '#2a1408',
    mutedForeground: '#aa7a56',
    popover: '#221008',
    popoverForeground: '#ffd8b0',
    primary: '#ffd8b0',
    primaryForeground: '#160800',
    secondary: '#341800',
    secondaryForeground: '#f0c090',
    accent: '#301600',
    accentForeground: '#e8c080',
    border: '#3a1c08',
    input: '#3a1c08',
    ring: '#d97316',
    midground: '#d97316',
    destructive: '#c43010',
    destructiveForeground: '#fef2f2',
    sidebarBackground: '#100600',
    sidebarBorder: '#2a1004',
    userBubble: '#2a1000',
    userBubbleBorder: '#4a2010'
  },
  typography: {
    fontMono: `"IBM Plex Mono", ${SYSTEM_MONO}`,
    fontUrl: 'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap'
  }
}

/** Clean grayscale. Matches the CLI mono skin and dashboard mono theme. */
export const monoTheme: DesktopTheme = {
  name: 'mono',
  label: 'Mono',
  description: 'Clean grayscale — minimal and focused',
  colors: {
    background: '#0e0e0e',
    foreground: '#eaeaea',
    card: '#141414',
    cardForeground: '#eaeaea',
    muted: '#1e1e1e',
    mutedForeground: '#808080',
    popover: '#181818',
    popoverForeground: '#eaeaea',
    primary: '#eaeaea',
    primaryForeground: '#0e0e0e',
    secondary: '#262626',
    secondaryForeground: '#c8c8c8',
    accent: '#222222',
    accentForeground: '#d8d8d8',
    border: '#2a2a2a',
    input: '#2a2a2a',
    ring: '#9a9a9a',
    midground: '#9a9a9a',
    destructive: '#a84040',
    destructiveForeground: '#fef2f2',
    sidebarBackground: '#0a0a0a',
    sidebarBorder: '#202020',
    userBubble: '#1a1a1a',
    userBubbleBorder: '#363636'
  }
}

/** Neon green on black. Matches the CLI cyberpunk skin and dashboard theme. */
export const cyberpunkTheme: DesktopTheme = {
  name: 'cyberpunk',
  label: 'Cyberpunk',
  description: 'Neon green on black — matrix terminal',
  colors: {
    background: '#000a00',
    foreground: '#00ff41',
    card: '#001200',
    cardForeground: '#00ff41',
    muted: '#001a00',
    mutedForeground: '#1a8a30',
    popover: '#001000',
    popoverForeground: '#00ff41',
    primary: '#00ff41',
    primaryForeground: '#000a00',
    secondary: '#002800',
    secondaryForeground: '#00cc34',
    accent: '#002000',
    accentForeground: '#00e038',
    border: '#003000',
    input: '#003000',
    ring: '#00ff41',
    midground: '#00ff41',
    destructive: '#ff003c',
    destructiveForeground: '#000a00',
    sidebarBackground: '#000600',
    sidebarBorder: '#001800',
    userBubble: '#001400',
    userBubbleBorder: '#004800'
  },
  typography: {
    fontMono: `"Courier New", Courier, monospace`,
    fontSans: `"Courier New", Courier, monospace`
  }
}

/** Cool slate blue for developers. Matches the CLI slate skin. */
export const slateTheme: DesktopTheme = {
  name: 'slate',
  label: 'Slate',
  description: 'Cool slate blue — focused developer theme',
  colors: {
    background: '#0d1117',
    foreground: '#c9d1d9',
    card: '#161b22',
    cardForeground: '#c9d1d9',
    muted: '#21262d',
    mutedForeground: '#8b949e',
    popover: '#1c2128',
    popoverForeground: '#c9d1d9',
    primary: '#c9d1d9',
    primaryForeground: '#0d1117',
    secondary: '#2a3038',
    secondaryForeground: '#adb5bf',
    accent: '#1e2530',
    accentForeground: '#c0c8d0',
    border: '#30363d',
    input: '#30363d',
    ring: '#58a6ff',
    midground: '#58a6ff',
    destructive: '#cf4848',
    destructiveForeground: '#fef2f2',
    sidebarBackground: '#090d13',
    sidebarBorder: '#1c2228',
    userBubble: '#1e2a38',
    userBubbleBorder: '#2e4060'
  },
  typography: {
    fontMono: `"JetBrains Mono", ${SYSTEM_MONO}`
  }
}

/** Bright light theme with cool blue accents. Matches the CLI daylight skin. */
export const daylightTheme: DesktopTheme = {
  name: 'daylight',
  label: 'Daylight',
  description: 'Bright light — cool blue accents',
  colors: {
    background: '#F8FAFC',
    foreground: '#111827',
    card: '#FFFFFF',
    cardForeground: '#111827',
    muted: '#E5EDF8',
    mutedForeground: '#475569',
    popover: '#FFFFFF',
    popoverForeground: '#111827',
    primary: '#2563EB',
    primaryForeground: '#FFFFFF',
    secondary: '#DBEAFE',
    secondaryForeground: '#0F172A',
    accent: '#1D4ED8',
    accentForeground: '#FFFFFF',
    border: '#93C5FD',
    input: '#93C5FD',
    ring: '#2563EB',
    midground: '#2563EB',
    composerRing: '#2563EB',
    destructive: '#B91C1C',
    destructiveForeground: '#FFFFFF',
    sidebarBackground: '#E5EDF8',
    sidebarBorder: '#BFDBFE',
    userBubble: '#EFF6FF',
    userBubbleBorder: '#BFDBFE'
  },
  darkColors: {
    background: '#0F172A',
    foreground: '#E2E8F0',
    card: '#1E293B',
    cardForeground: '#E2E8F0',
    muted: '#243449',
    mutedForeground: '#94A3B8',
    popover: '#1E293B',
    popoverForeground: '#E2E8F0',
    primary: '#3B82F6',
    primaryForeground: '#FFFFFF',
    secondary: '#334155',
    secondaryForeground: '#CBD5E1',
    accent: '#2563EB',
    accentForeground: '#EFF6FF',
    border: '#334155',
    input: '#334155',
    ring: '#3B82F6',
    midground: '#3B82F6',
    composerRing: '#3B82F6',
    destructive: '#EF4444',
    destructiveForeground: '#FFFFFF',
    sidebarBackground: '#0B1220',
    sidebarBorder: '#1E293B',
    userBubble: '#1E293B',
    userBubbleBorder: '#334155'
  }
}

/** Warm light theme — brown/gold text on a cream ground. Matches the CLI warm-lightmode skin. */
export const warmLightTheme: DesktopTheme = {
  name: 'warm-lightmode',
  label: 'Warm Light',
  description: 'Warm light — brown and gold on cream',
  colors: {
    background: '#F5F0E8',
    foreground: '#2C1810',
    card: '#F5EFE0',
    cardForeground: '#2C1810',
    muted: '#F0E8D8',
    mutedForeground: '#8B7355',
    popover: '#F5EFE0',
    popoverForeground: '#2C1810',
    primary: '#8B4513',
    primaryForeground: '#FFF8DC',
    secondary: '#E8DCC8',
    secondaryForeground: '#5C3D11',
    accent: '#8B6914',
    accentForeground: '#FFF8DC',
    border: '#A0845C',
    input: '#A0845C',
    ring: '#8B4513',
    midground: '#8B6914',
    composerRing: '#8B6914',
    destructive: '#C62828',
    destructiveForeground: '#FFFFFF',
    sidebarBackground: '#F0E8D8',
    sidebarBorder: '#DFCFB0',
    userBubble: '#E8DCC8',
    userBubbleBorder: '#DFCFB0'
  },
  darkColors: {
    background: '#2C1810',
    foreground: '#F5F0E8',
    card: '#3A2418',
    cardForeground: '#F5F0E8',
    muted: '#4A3222',
    mutedForeground: '#C9B49A',
    popover: '#3A2418',
    popoverForeground: '#F5F0E8',
    primary: '#DAA520',
    primaryForeground: '#2C1810',
    secondary: '#4A3222',
    secondaryForeground: '#E8DCC8',
    accent: '#8B6914',
    accentForeground: '#FFF8DC',
    border: '#5C3D11',
    input: '#5C3D11',
    ring: '#DAA520',
    midground: '#DAA520',
    composerRing: '#DAA520',
    destructive: '#EF5350',
    destructiveForeground: '#FFFFFF',
    sidebarBackground: '#241410',
    sidebarBorder: '#4A3222',
    userBubble: '#3A2418',
    userBubbleBorder: '#5C3D11'
  }
}

/** Deep ocean blue and seafoam. Matches the CLI poseidon skin. */
export const poseidonTheme: DesktopTheme = {
  name: 'poseidon',
  label: 'Poseidon',
  description: 'Deep ocean blue and seafoam',
  colors: {
    background: '#0F2440',
    foreground: '#EAF7FF',
    card: '#153C73',
    cardForeground: '#EAF7FF',
    muted: '#0B1F3A',
    mutedForeground: '#496884',
    popover: '#153C73',
    popoverForeground: '#EAF7FF',
    primary: '#5DB8F5',
    primaryForeground: '#0F2440',
    secondary: '#1B4A8A',
    secondaryForeground: '#A9DFFF',
    accent: '#2A6FB9',
    accentForeground: '#EAF7FF',
    border: '#2A6FB9',
    input: '#2A6FB9',
    ring: '#5DB8F5',
    midground: '#5DB8F5',
    composerRing: '#5DB8F5',
    destructive: '#D94F4F',
    destructiveForeground: '#FFFFFF',
    sidebarBackground: '#0B1F3A',
    sidebarBorder: '#153C73',
    userBubble: '#1B4A8A',
    userBubbleBorder: '#2A6FB9'
  }
}

/** Austere grayscale with persistence. Matches the CLI sisyphus skin. */
export const sisyphusTheme: DesktopTheme = {
  name: 'sisyphus',
  label: 'Sisyphus',
  description: 'Austere grayscale — persistence',
  colors: {
    background: '#202020',
    foreground: '#F5F5F5',
    card: '#2A2A2A',
    cardForeground: '#F5F5F5',
    muted: '#181818',
    mutedForeground: '#656565',
    popover: '#2A2A2A',
    popoverForeground: '#F5F5F5',
    primary: '#E7E7E7',
    primaryForeground: '#202020',
    secondary: '#303030',
    secondaryForeground: '#D3D3D3',
    accent: '#3A3A3A',
    accentForeground: '#F5F5F5',
    border: '#4A4A4A',
    input: '#4A4A4A',
    ring: '#B7B7B7',
    midground: '#B7B7B7',
    composerRing: '#B7B7B7',
    destructive: '#E7E7E7',
    destructiveForeground: '#202020',
    sidebarBackground: '#161616',
    sidebarBorder: '#2A2A2A',
    userBubble: '#2A2A2A',
    userBubbleBorder: '#4A4A4A'
  }
}

/** Burnt orange and ember. Matches the CLI charizard skin. */
export const charizardTheme: DesktopTheme = {
  name: 'charizard',
  label: 'Charizard',
  description: 'Burnt orange and ember — volcanic',
  colors: {
    background: '#2B160E',
    foreground: '#FFF0D4',
    card: '#3A1E10',
    cardForeground: '#FFF0D4',
    muted: '#1F0E08',
    mutedForeground: '#6C4724',
    popover: '#3A1E10',
    popoverForeground: '#FFF0D4',
    primary: '#F29C38',
    primaryForeground: '#2B160E',
    secondary: '#4A1B07',
    secondaryForeground: '#FFD39A',
    accent: '#C75B1D',
    accentForeground: '#FFF0D4',
    border: '#C75B1D',
    input: '#C75B1D',
    ring: '#F29C38',
    midground: '#F29C38',
    composerRing: '#F29C38',
    destructive: '#EF5350',
    destructiveForeground: '#FFFFFF',
    sidebarBackground: '#1F0E08',
    sidebarBorder: '#3A1E10',
    userBubble: '#4A1B07',
    userBubbleBorder: '#C75B1D'
  }
}

/** CLI skin name → desktop theme name, so `/skin <cli-name>` and backend sync resolve correctly. */
export const SKIN_ALIASES: Record<string, string> = {
  default: 'elidia',
  gold: 'elidia',
  'elidia-light': 'elidia',
  ares: 'ember'
}

export const BUILTIN_THEMES: Record<string, DesktopTheme> = {
  elidia: elidiaTheme,
  midnight: midnightTheme,
  ember: emberTheme,
  mono: monoTheme,
  cyberpunk: cyberpunkTheme,
  slate: slateTheme,
  daylight: daylightTheme,
  'warm-lightmode': warmLightTheme,
  poseidon: poseidonTheme,
  sisyphus: sisyphusTheme,
  charizard: charizardTheme
}

export const BUILTIN_THEME_LIST = Object.values(BUILTIN_THEMES)

/** Skin used when nothing is persisted or the persisted name is retired. */
export const DEFAULT_SKIN_NAME = 'elidia'
