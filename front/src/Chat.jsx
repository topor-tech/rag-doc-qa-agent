import { useEffect, useRef, useState } from 'react'

const KB_LINK = /\[([^\]]+)\]\((\/kb\/[^)\s]+)\)/g
const DOCUMENT_LINE = /^\[([^\]]+)\]\((\/kb\/[^)#\s]+)\)\s*$/

function openKb(event, href, onOpenPath) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return
  event.preventDefault()
  onOpenPath(href)
}

function lineNodes(content, onOpenPath) {
  const nodes = []
  let last = 0
  let key = 0
  for (const match of content.matchAll(KB_LINK)) {
    const start = match.index ?? 0
    if (start > last) nodes.push(content.slice(last, start))
    const href = match[2]
    const documentLink = !href.includes('#')
    nodes.push(
      <a
        key={key}
        href={href}
        className={documentLink ? 'doc-cite' : undefined}
        onClick={(event) => openKb(event, href, onOpenPath)}
      >
        {match[1]}
      </a>,
    )
    key += 1
    last = start + match[0].length
  }
  if (last < content.length) nodes.push(content.slice(last))
  return nodes
}

function MessageBody({ content, onOpenPath }) {
  const lines = content.split('\n')
  return (
    <div className="message-body">
      {lines.map((line, index) => {
        const document = line.trim().match(DOCUMENT_LINE)
        if (document) {
          const href = document[2]
          return (
            <p key={index}>
              <a className="doc-cite" href={href} onClick={(event) => openKb(event, href, onOpenPath)}>
                {document[1]}
              </a>
            </p>
          )
        }
        return <p key={index}>{lineNodes(line, onOpenPath)}</p>
      })}
    </div>
  )
}

function Chat({ onOpenPath, onNavigate, sessionId }) {
  const [sessions, setSessions] = useState([])
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [creating, setCreating] = useState(false)
  const [writable, setWritable] = useState(true)
  const [error, setError] = useState('')
  const turnRef = useRef(0)
  const bottomRef = useRef(null)
  const sessionIdRef = useRef(sessionId)

  useEffect(() => {
    sessionIdRef.current = sessionId
  }, [sessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, pending, error])

  useEffect(() => {
    let cancelled = false
    const requestedId = sessionId

    async function load() {
      setMessages([])
      setWritable(true)
      setError('')
      setDraft('')

      const listResponse = await fetch('/api/sessions')
      if (cancelled) return
      if (!listResponse.ok) {
        setError('Не удалось открыть список диалогов')
        return
      }
      const list = await listResponse.json()
      if (cancelled) return
      setSessions(Array.isArray(list.sessions) ? list.sessions : [])

      if (!requestedId) return

      const response = await fetch(`/api/sessions/${requestedId}`)
      if (cancelled) return
      if (response.status === 404) {
        onNavigate('/')
        return
      }
      if (!response.ok) {
        setError('Не удалось открыть диалог')
        return
      }
      const data = await response.json()
      if (cancelled) return
      setMessages(Array.isArray(data.messages) ? data.messages : [])
      setWritable(data.writable !== false)
    }

    load().catch(() => {
      if (!cancelled) setError('Не удалось открыть диалог')
    })
    return () => {
      cancelled = true
    }
  }, [sessionId, onNavigate])

  async function refreshSessions() {
    const response = await fetch('/api/sessions')
    if (!response.ok) return
    const list = await response.json()
    setSessions(Array.isArray(list.sessions) ? list.sessions : [])
  }

  async function startNewDialog() {
    if (creating || pending) return
    setCreating(true)
    setError('')
    try {
      const response = await fetch('/api/sessions', { method: 'POST' })
      if (!response.ok) throw new Error('Не удалось открыть сессию')
      const data = await response.json()
      await refreshSessions()
      onNavigate(`/c/${data.id}`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось открыть сессию')
    } finally {
      setCreating(false)
    }
  }

  async function sendMessage() {
    const text = draft.trim()
    if (!text || pending || !sessionId || !writable) return

    const turn = turnRef.current
    const requestedId = sessionId
    setDraft('')
    setError('')
    setPending(true)
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', content: text },
    ])

    try {
      const response = await fetch(`/api/sessions/${requestedId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      })
      if (sessionIdRef.current !== requestedId || turnRef.current !== turn) return
      if (!response.ok) {
        let detail = 'Не удалось получить ответ агента'
        try {
          const problem = await response.json()
          if (typeof problem.detail === 'string') detail = problem.detail
        } catch {
          // Keep the fallback message when the body is not JSON.
        }
        throw new Error(detail)
      }

      const data = await response.json()
      if (sessionIdRef.current !== requestedId || turnRef.current !== turn) return
      setMessages(Array.isArray(data.messages) ? data.messages : [])
      setWritable(data.writable !== false)
      await refreshSessions()
    } catch (cause) {
      if (sessionIdRef.current !== requestedId || turnRef.current !== turn) return
      setError(cause instanceof Error ? cause.message : 'Не удалось получить ответ агента')
      try {
        const again = await fetch(`/api/sessions/${requestedId}`)
        if (again.ok && sessionIdRef.current === requestedId) {
          const data = await again.json()
          setMessages(Array.isArray(data.messages) ? data.messages : [])
          setWritable(data.writable !== false)
        }
      } catch {
        // The banner already explains the failure.
      }
    } finally {
      if (turnRef.current === turn) setPending(false)
    }
  }

  function onSubmit(event) {
    event.preventDefault()
    sendMessage()
  }

  function onKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      sendMessage()
    }
  }

  const openTitle = sessions.find((item) => item.id === sessionId)?.title

  return (
    <div className="chat-screen">
      <aside className="session-list" aria-label="Ваши диалоги">
        <button
          type="button"
          className="ghost"
          onClick={startNewDialog}
          disabled={creating || pending}
        >
          Новый диалог
        </button>
        {sessions.length === 0 ? (
          <p className="session-empty">Пока нет диалогов.</p>
        ) : (
          <ul>
            {sessions.map((session) => (
              <li key={session.id}>
                <a
                  className={session.id === sessionId ? 'session-link active' : 'session-link'}
                  href={`/c/${session.id}`}
                  aria-current={session.id === sessionId ? 'page' : undefined}
                  onClick={(event) => {
                    if (
                      event.metaKey ||
                      event.ctrlKey ||
                      event.shiftKey ||
                      event.altKey ||
                      event.button !== 0
                    ) {
                      return
                    }
                    event.preventDefault()
                    onNavigate(`/c/${session.id}`)
                  }}
                >
                  {session.title || 'Новый диалог'}
                </a>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <div className="chat">
        <header className="chat-header">
          <div>
            <p className="eyebrow">Сессия</p>
            <h1>{sessionId ? openTitle || 'Новый диалог' : 'Чат с агентом'}</h1>
          </div>
          <button
            type="button"
            className="ghost"
            onClick={startNewDialog}
            disabled={creating || pending}
          >
            Новый диалог
          </button>
        </header>

        <main className="messages" aria-live="polite">
          {!sessionId ? (
            <p className="empty">Выберите диалог или начните новый.</p>
          ) : messages.length === 0 ? (
            <p className="empty">Задайте вопрос по регламенту.</p>
          ) : (
            messages.map((message) => (
              <article key={message.id} className={`bubble ${message.role}`}>
                <span className="role">{message.role === 'user' ? 'Вы' : 'Агент'}</span>
                {message.role === 'assistant' ? (
                  <MessageBody content={message.content} onOpenPath={onOpenPath} />
                ) : (
                  <p>{message.content}</p>
                )}
              </article>
            ))
          )}
          {pending && (
            <article className="bubble assistant">
              <span className="role">Агент</span>
              <p>Печатает…</p>
            </article>
          )}
          <div ref={bottomRef} />
        </main>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        {sessionId && !writable ? (
          <p className="notice">Этот диалог только для чтения.</p>
        ) : null}

        {sessionId && writable ? (
          <form className="composer" onSubmit={onSubmit}>
            <label className="sr-only" htmlFor="draft">
              Сообщение
            </label>
            <textarea
              id="draft"
              rows={2}
              value={draft}
              placeholder="Спросите про регламент"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              disabled={pending}
            />
            <button type="submit" disabled={!draft.trim() || pending}>
              Отправить
            </button>
          </form>
        ) : null}
      </div>
    </div>
  )
}

export default Chat
