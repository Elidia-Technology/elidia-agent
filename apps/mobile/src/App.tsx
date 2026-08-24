import { useEffect, useState } from 'react'

import { Gateway } from './lib/gateway'
import { clearPairing, loadPairing } from './lib/credentials'
import { Chat } from './screens/Chat'
import { Pair } from './screens/Pair'
import { Sessions } from './screens/Sessions'

type View = { name: 'loading' } | { name: 'pair' } | { name: 'sessions' } | { name: 'chat'; sessionId: string }

export default function App() {
  const [gateway, setGateway] = useState<Gateway | null>(null)
  const [view, setView] = useState<View>({ name: 'loading' })

  // Restore a previous pairing so the app opens straight into the user's
  // conversations rather than asking for an address every launch.
  useEffect(() => {
    loadPairing().then(pairing => {
      if (pairing) {
        setGateway(new Gateway(pairing))
        setView({ name: 'sessions' })
      } else {
        setView({ name: 'pair' })
      }
    })
  }, [])

  async function unpair() {
    await clearPairing()
    setGateway(null)
    setView({ name: 'pair' })
  }

  if (view.name === 'loading') {
    return <div className="boot muted center">Elidia</div>
  }

  if (view.name === 'pair' || !gateway) {
    return (
      <Pair
        onPaired={g => {
          setGateway(g)
          setView({ name: 'sessions' })
        }}
      />
    )
  }

  if (view.name === 'chat') {
    return (
      <Chat
        gateway={gateway}
        sessionId={view.sessionId}
        onBack={() => setView({ name: 'sessions' })}
      />
    )
  }

  return (
    <Sessions
      gateway={gateway}
      onOpen={id => setView({ name: 'chat', sessionId: id })}
      onUnpair={unpair}
    />
  )
}
