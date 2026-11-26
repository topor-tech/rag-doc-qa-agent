import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

async function problemMessage(response, fallback) {
  try {
    const problem = await response.json()
    if (typeof problem.detail === 'string') return problem.detail
  } catch {
    // The body is not JSON.
  }
  return fallback
}

function Documents({ documentId, anchor, onNavigate }) {
  const [catalog, setCatalog] = useState([])
  const [catalogError, setCatalogError] = useState('')
  const [loaded, setLoaded] = useState(null)
  const readerRef = useRef(null)
  const article = loaded?.id === documentId ? loaded.article : null
  const articleError = loaded?.id === documentId ? loaded.error : ''
  const loadingArticle = Boolean(documentId) && loaded?.id !== documentId

  useEffect(() => {
    let cancelled = false
    async function loadCatalog() {
      try {
        const [documentsResponse, glossaryResponse] = await Promise.all([
          fetch('/api/documents'),
          fetch('/api/glossary'),
        ])
        if (!documentsResponse.ok) {
          throw new Error(await problemMessage(documentsResponse, 'Не удалось загрузить документы'))
        }
        if (!glossaryResponse.ok) {
          throw new Error(await problemMessage(glossaryResponse, 'Не удалось загрузить глоссарий'))
        }
        const documents = await documentsResponse.json()
        const glossary = await glossaryResponse.json()
        if (cancelled) return
        setCatalog([
          ...documents.documents.map((item) => ({ id: item.id, title: item.title })),
          { id: glossary.id, title: glossary.title },
        ])
        setCatalogError('')
      } catch (cause) {
        if (cancelled) return
        setCatalogError(cause instanceof Error ? cause.message : 'Не удалось загрузить документы')
      }
    }
    loadCatalog()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!documentId) return undefined
    const controller = new AbortController()
    fetch(`/api/documents/${encodeURIComponent(documentId)}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await problemMessage(response, 'Не удалось открыть документ'))
        }
        return response.json()
      })
      .then((data) => {
        if (controller.signal.aborted) return
        setLoaded({ id: documentId, article: data, error: '' })
      })
      .catch((cause) => {
        if (controller.signal.aborted) return
        setLoaded({
          id: documentId,
          article: null,
          error: cause instanceof Error ? cause.message : 'Не удалось открыть документ',
        })
      })
    return () => controller.abort()
  }, [documentId])

  useEffect(() => {
    if (!article) return
    const node = anchor ? window.document.getElementById(anchor) : null
    if (!node) {
      readerRef.current?.scrollTo({ top: 0 })
      return
    }
    node.scrollIntoView({ block: 'start' })
  }, [article, anchor])

  function openDocument(event, id) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return
    event.preventDefault()
    onNavigate(`/kb/${encodeURIComponent(id)}`)
  }

  return (
    <div className="docs">
      <nav className="doc-column" aria-label="Документы">
        <p className="column-label">Каталог</p>
        {catalogError && (
          <p className="error" role="alert">
            {catalogError}
          </p>
        )}
        {catalog.map((item) => (
          <a
            key={item.id}
            href={`/kb/${encodeURIComponent(item.id)}`}
            className={item.id === documentId ? 'doc-link active' : 'doc-link'}
            aria-current={item.id === documentId ? 'page' : undefined}
            onClick={(event) => openDocument(event, item.id)}
          >
            {item.title}
          </a>
        ))}
      </nav>

      <nav className="section-column" aria-label="Разделы">
        <p className="column-label">Разделы</p>
        {article?.sections.map((section) => (
          <a
            key={section.id}
            href={`#${section.anchor}`}
            className={anchor === section.anchor ? 'section-link active' : 'section-link'}
            aria-current={anchor === section.anchor ? 'location' : undefined}
          >
            {section.heading}
          </a>
        ))}
      </nav>

      <article className="reader" ref={readerRef}>
        {!documentId && !articleError && <p className="empty">Выберите документ.</p>}
        {loadingArticle && <p className="empty">Загрузка…</p>}
        {articleError && (
          <p className="error" role="alert">
            {articleError}
          </p>
        )}
        {article && (
          <>
            <h1>{article.title}</h1>
            {article.sections.map((section) => (
              <section key={section.id} className="kb-block">
                <h2 id={section.anchor}>{section.heading}</h2>
                {section.body_markdown && (
                  <div className="markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.body_markdown}</ReactMarkdown>
                  </div>
                )}
              </section>
            ))}
          </>
        )}
      </article>
    </div>
  )
}

export default Documents
