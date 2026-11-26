import { useEffect, useState } from 'react'
import Chat from './Chat.jsx'
import Documents from './Documents.jsx'
import './App.css'

function readLocation() {
  return {
    pathname: window.location.pathname,
    anchor: decodeHash(window.location.hash),
  }
}

function decodeHash(hash) {
  if (!hash || hash === '#') return ''
  try {
    return decodeURIComponent(hash.slice(1))
  } catch {
    return hash.slice(1)
  }
}

function parseRoute(pathname) {
  if (pathname === '/kb') return { name: 'documents', documentId: null }
  const match = pathname.match(/^\/kb\/([^/]+)\/?$/)
  if (match) return { name: 'documents', documentId: decodeURIComponent(match[1]) }
  return { name: 'chat', documentId: null }
}

function NavLink({ href, current, onNavigate, children }) {
  return (
    <a
      href={href}
      className={current ? 'nav-link active' : 'nav-link'}
      aria-current={current ? 'page' : undefined}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return
        event.preventDefault()
        onNavigate(href)
      }}
    >
      {children}
    </a>
  )
}

function App() {
  const [location, setLocation] = useState(readLocation)

  useEffect(() => {
    const sync = () => setLocation(readLocation())
    window.addEventListener('popstate', sync)
    window.addEventListener('hashchange', sync)
    return () => {
      window.removeEventListener('popstate', sync)
      window.removeEventListener('hashchange', sync)
    }
  }, [])

  function navigate(to) {
    const url = new URL(to, window.location.origin)
    const next = `${url.pathname}${url.search}${url.hash}`
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
    if (next !== current) window.history.pushState({}, '', next)
    setLocation(readLocation())
  }

  const route = parseRoute(location.pathname)

  return (
    <div className="shell">
      <nav className="navbar" aria-label="Разделы приложения">
        <NavLink href="/" current={route.name === 'chat'} onNavigate={navigate}>
          Чат
        </NavLink>
        <NavLink href="/kb" current={route.name === 'documents'} onNavigate={navigate}>
          Документы
        </NavLink>
      </nav>
      <div className={route.name === 'chat' ? 'view' : 'view hidden'}>
        <Chat onOpenPath={navigate} />
      </div>
      {route.name === 'documents' && (
        <Documents documentId={route.documentId} anchor={location.anchor} onNavigate={navigate} />
      )}
    </div>
  )
}

export default App
