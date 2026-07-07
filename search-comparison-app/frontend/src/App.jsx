import { useState } from 'react'

function App() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setError(null)
    setResults(null)

    try {
      const response = await fetch(`/api/compare?query=${encodeURIComponent(query)}`)
      if (!response.ok) {
        throw new Error(`API Error: ${response.statusText}`)
      }
      const data = await response.json()
      setResults(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const renderSkeleton = () => (
    <div className="loader-container">
      {[1, 2, 3].map(i => (
        <div key={i} className="skeleton-card">
          <div className="skeleton-title"></div>
          <div className="skeleton-url"></div>
          <div className="skeleton-text"></div>
          <div className="skeleton-text"></div>
          <div className="skeleton-text"></div>
        </div>
      ))}
    </div>
  )

  return (
    <>
      <header>
        <h1>Search Pipeline Comparison</h1>
        <form className="search-container" onSubmit={handleSearch}>
          <input
            type="text"
            className="search-input"
            placeholder="Enter a company or topic to investigate..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={loading}
          />
          <button type="submit" className="search-btn" disabled={loading || !query.trim()}>
            {loading ? 'Searching...' : 'Search'}
          </button>
        </form>
      </header>

      <main className="main-container">
        {!loading && !results && !error && (
          <div className="empty-state">
            Enter a query above to see side-by-side results from Exa API and the Custom Scraper.
          </div>
        )}

        {error && (
          <div className="empty-state" style={{ color: '#ef4444' }}>
            Failed to load results: {error}
          </div>
        )}

        {/* Exa Column */}
        {(loading || results) && (
          <div className="column exa">
            <h2 className="column-header exa">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
              Exa API Results
            </h2>
            {loading ? renderSkeleton() : (
              <div className="results-list">
                {results?.exa.map((res, i) => (
                  <div key={i} className="result-card">
                    <a href={res.url} target="_blank" rel="noreferrer" className="result-title">
                      {res.title}
                    </a>
                    <a href={res.url} target="_blank" rel="noreferrer" className="result-url">
                      {res.url}
                    </a>
                    <div className="result-snippet">{res.snippet}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Custom Column */}
        {(loading || results) && (
          <div className="column custom">
            <h2 className="column-header custom">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
              Custom Scraper Results
            </h2>
            {loading ? renderSkeleton() : (
              <div className="results-list">
                {results?.custom.map((res, i) => (
                  <div key={i} className="result-card">
                    <a href={res.url} target="_blank" rel="noreferrer" className="result-title">
                      {res.title}
                    </a>
                    <a href={res.url} target="_blank" rel="noreferrer" className="result-url">
                      {res.url}
                    </a>
                    <div className="result-snippet">{res.snippet}</div>
                    
                    {res.summary && !res.summary.startsWith("[Summarization Failed") && (
                      <div className="summary-box">
                        <span className="summary-label">LLM Summary:</span>
                        {res.summary}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </>
  )
}

export default App
