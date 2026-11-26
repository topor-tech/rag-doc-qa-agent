import { useEffect, useRef, useState } from 'react'
import './App.css'

function App() {
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
              <span className="role">
                {message.role === 'user' ? 'Вы' : 'Агент'}
              </span>
              <p>{message.content}</p>
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

export default App
