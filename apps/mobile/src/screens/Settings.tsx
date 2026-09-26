import { useState } from 'react'

import {
  DEFAULT_APPEARANCE,
  FAMILY_PRESETS,
  SIZE_PRESETS,
  applyAppearance,
  loadAppearance,
  saveAppearance,
  type Appearance,
} from '../lib/appearance'

/**
 * Reading appearance: font family and text size.
 *
 * Every choice applies immediately, to the whole app via `applyAppearance`,
 * and is persisted before the click handler returns, so leaving this screen
 * never loses a change and every other screen reflects it right away.
 */
export function Settings({ onBack }: { onBack: () => void }) {
  const [appearance, setAppearance] = useState<Appearance>(() => loadAppearance())

  function apply(next: Appearance) {
    setAppearance(next)
    saveAppearance(next)
    applyAppearance(next)
  }

  return (
    <div className="settings">
      <header>
        <button className="back" onClick={onBack} aria-label="Back to sessions">‹</button>
        <span className="title">Settings</span>
      </header>

      <section className="settings-section">
        <h2>Appearance</h2>

        <h3 className="settings-subtitle">Font</h3>
        {/* Each option is set inline, in its own font, because the whole
            point is to preview it before choosing it — the family a button
            shows is data (from lib/appearance.ts), not page styling. */}
        <div className="settings-options" role="group" aria-label="Font family">
          {FAMILY_PRESETS.map(preset => {
            const selected = appearance.familyId === preset.id
            return (
              <button
                key={preset.id}
                type="button"
                className={`settings-option${selected ? ' selected' : ''}`}
                aria-pressed={selected}
                style={{ fontFamily: preset.stack }}
                onClick={() => apply({ ...appearance, familyId: preset.id })}
              >
                <span>{preset.label}</span>
                <span aria-hidden="true" className="check">✓</span>
              </button>
            )
          })}
        </div>

        <h3 className="settings-subtitle">Text size</h3>
        <div className="settings-options" role="group" aria-label="Text size">
          {SIZE_PRESETS.map(preset => {
            const selected = appearance.sizeId === preset.id
            return (
              <button
                key={preset.id}
                type="button"
                className={`settings-option${selected ? ' selected' : ''}`}
                aria-pressed={selected}
                style={{ fontSize: `calc(1em * ${preset.scale})` }}
                onClick={() => apply({ ...appearance, sizeId: preset.id })}
              >
                <span>{preset.label}</span>
                <span aria-hidden="true" className="check">✓</span>
              </button>
            )
          })}
        </div>

        <button type="button" className="link settings-reset" onClick={() => apply(DEFAULT_APPEARANCE)}>
          Reset to defaults
        </button>
      </section>
    </div>
  )
}
