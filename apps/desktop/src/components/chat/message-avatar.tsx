import { IconUser } from '@tabler/icons-react'
import { type FC, useState } from 'react'

import { type Account, initialsFor } from '@/app/hooks/use-account'
import { cn } from '@/lib/utils'

/**
 * Who is speaking, at a glance.
 *
 * The assistant gets the Elidia mark — the colourful shield, not the wordmark.
 * It is line art on transparency and reads on every skin the app ships, from
 * the warm paper light ground to the near-black dark ones, so it needs no
 * per-theme variant the way the banner does.
 *
 * Line art specifically, not the illustrated logo. Rendered at 28px the
 * illustrated version collapses into a muddy blob and elidia.png is
 * unrecognisable; the line art keeps a readable silhouette at that size, which
 * is the only size this is ever drawn at.
 *
 * The user gets whatever is actually known about them, in that order: their
 * portal avatar if they have set one, else initials from their name or email,
 * else a glyph. Each step down is a real reduction in what we know, and the
 * last one is honest rather than a placeholder — an avatar showing "A" for an
 * account with no name would be a fabrication.
 *
 * Running Elidia with no AiUtils account is supported, so the glyph is a
 * normal outcome and not a failure state.
 */

const MARK = 'elidia-mark.png'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

const FRAME_CLASS =
  'grid size-7 shrink-0 place-items-center overflow-hidden rounded-full border border-(--ui-border-subtle) bg-(--ui-control-background) select-none'

export const AssistantAvatar: FC<{ className?: string }> = ({ className }) => (
  <span
    aria-hidden="true"
    className={cn(FRAME_CLASS, className)}
    data-slot="aui_assistant-avatar"
    title="Elidia Agent"
  >
    <img alt="" className="size-full object-contain p-0.5" draggable={false} src={assetPath(MARK)} />
  </span>
)

export const UserAvatar: FC<{ account?: Account | null; className?: string }> = ({
  account = null,
  className
}) => {
  // A remote avatar that 404s must fall back rather than leaving a broken
  // image in the conversation, and it can only be known to be broken at
  // runtime.
  const [imageFailed, setImageFailed] = useState(false)
  const avatarUrl = account?.avatar_url
  const initials = initialsFor(account)
  const label = account?.full_name || account?.email || 'You'

  if (avatarUrl && !imageFailed) {
    return (
      <span className={cn(FRAME_CLASS, className)} data-slot="aui_user-avatar" title={label}>
        <img
          alt=""
          className="size-full object-cover"
          draggable={false}
          onError={() => setImageFailed(true)}
          src={avatarUrl}
        />
      </span>
    )
  }

  if (initials) {
    return (
      <span
        className={cn(FRAME_CLASS, 'text-[0.625rem] font-semibold text-(--ui-text-secondary)', className)}
        data-slot="aui_user-avatar"
        title={label}
      >
        {initials}
      </span>
    )
  }

  return (
    <span
      aria-hidden="true"
      className={cn(FRAME_CLASS, 'text-(--ui-text-secondary)', className)}
      data-slot="aui_user-avatar"
      title={label}
    >
      <IconUser className="size-4" stroke={1.75} />
    </span>
  )
}
