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

function Chat({ onOpenPath }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const sessionIdRef = useRef(null)
  const turnRef = useRef(0)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, pending, error])

  async function openSession() {
    if (sessionIdRef.current) return sessionIdRef.current

    const response = await fetch('/api/sessions', { method: 'POST' })
    if (!response.ok) throw new Error('Не удалось открыть сессию')

    const data = await response.json()
    sessionIdRef.current = data.id
    return data.id
  }

  async function sendMessage() {
    const text = draft.trim()
    if (!text || pending) return

    const turn = turnRef.current
    setDraft('')
    setError('')
    setPending(true)
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', content: text },
    ])

    try {
      const sessionId = await openSession()
      const response = await fetch(`/api/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      })
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
      const reply = data.messages.at(-1)
      if (!reply || reply.role !== 'assistant') {
        throw new Error('Не удалось получить ответ агента')
      }
      if (turnRef.current !== turn) return

      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'assistant', content: reply.content },
      ])
    } catch (cause) {
      if (turnRef.current !== turn) return
      setError(cause instanceof Error ? cause.message : 'Не удалось получить ответ агента')
    } finally {
      if (turnRef.current === turn) setPending(false)
    }
  }

  function startNewDialog() {
    turnRef.current += 1
    sessionIdRef.current = null
    setMessages([])
    setDraft('')
    setError('')
    setPending(false)
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

  return (
    <div className="chat">
      <header className="chat-header">
        <div>
          <p className="eyebrow">Сессия</p>
          <h1>Чат с агентом</h1>
        </div>
        <button
          type="button"
          className="ghost"
          onClick={startNewDialog}
          disabled={messages.length === 0 && !error}
        >
          Новый диалог
        </button>
      </header>

      <main className="messages" aria-live="polite">
        {messages.length === 0 ? (
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
    </div>
  )
}

export default Chat
