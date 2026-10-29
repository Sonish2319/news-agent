import { useState, useCallback } from 'react'
import './index.css'

const API_BASE = 'http://localhost:8000'

const COUNTRIES = [
  { value: 'Nepal', label: 'Nepal', flag: '🏔️', abbr: 'NPL', color: '#dc2626' },
  { value: 'India', label: 'India', flag: '☀️', abbr: 'IND', color: '#f97316' },
  { value: 'International', label: 'Global', flag: '🌐', abbr: 'INT', color: '#3b82f6' },
]

function App() {
  const [country, setCountry]       = useState('Nepal')
  const [email, setEmail]           = useState('')
  const [topStories, setTopStories] = useState(5)
  const [loading, setLoading]       = useState(false)
  const [status, setStatus]         = useState(null) // { type: 'success'|'error', message }

  const fillPct = ((topStories - 1) / 19) * 100

  const handleSubmit = useCallback(async (e) => {
    e.preventDefault()
    if (!email || !country) return

    setLoading(true)
    setStatus(null)

    try {
      const res = await fetch(`${API_BASE}/api/news`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          country,
          email,
          top_stories: topStories,
        }),
      })

      const data = await res.json()

      if (res.ok) {
        setStatus({ type: 'success', message: data.message })
        setEmail('')
      } else {
        const detail = data?.detail
        const msg =
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
            ? detail.map((d) => d.msg).join(', ')
            : 'Something went wrong. Please try again.'
        setStatus({ type: 'error', message: msg })
      }
    } catch {
      setStatus({
        type: 'error',
        message:
          'Could not reach the server. Make sure the API is running on port 8000.',
      })
    } finally {
      setLoading(false)
    }
  }, [country, email, topStories])

  return (
    <div className="app-wrapper">
      {/* Background orbs */}
      <div className="bg-orb bg-orb-1" />
      <div className="bg-orb bg-orb-2" />
      <div className="bg-orb bg-orb-3" />

      {/* Hero */}
      <header className="hero">
        <div className="hero-badge">
          <span className="dot" />
          AI-Powered News Agent
        </div>
        <h1>
          Your daily <span>news briefing</span>,
          <br />delivered to your inbox
        </h1>
        <p>
          Choose your country, enter your email, and our local AI agent will
          curate the top stories and send them directly to you — completely
          private, no tracking.
        </p>
      </header>

      {/* Form card */}
      <main>
        <form className="form-card" onSubmit={handleSubmit} noValidate>

          {/* ── Country ── */}
          <div className="field-group">
            <label className="field-label">
              <span className="label-icon">🗺️</span>
              Select Country
            </label>
            <div className="country-grid" role="radiogroup" aria-label="Country selection">
              {COUNTRIES.map(({ value, label, abbr, color }) => (
                <label
                  key={value}
                  className={`country-card${country === value ? ' selected' : ''}`}
                  htmlFor={`country-${value}`}
                >
                  <input
                    type="radio"
                    id={`country-${value}`}
                    name="country"
                    value={value}
                    checked={country === value}
                    onChange={() => setCountry(value)}
                  />
                  <span
                    className="country-flag"
                    style={{
                      background: color,
                      borderRadius: '8px',
                      padding: '4px 8px',
                      fontSize: '13px',
                      fontWeight: '800',
                      color: 'white',
                      letterSpacing: '0.05em',
                      display: 'inline-block',
                      marginBottom: '8px',
                    }}
                    aria-label={label}
                  >
                    {abbr}
                  </span>
                  <span className="country-name">{label}</span>
                  <span className="country-check" aria-hidden="true">✓</span>
                </label>
              ))}
            </div>
          </div>

          {/* ── Email ── */}
          <div className="field-group">
            <label className="field-label" htmlFor="email-input">
              <span className="label-icon">📧</span>
              Email Address
            </label>
            <input
              id="email-input"
              type="email"
              className="text-input"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>

          {/* ── Top Stories Slider ── */}
          <div className="field-group">
            <label className="field-label" htmlFor="stories-slider">
              <span className="label-icon">📰</span>
              Number of Top Stories
            </label>
            <div className="slider-container">
              <div className="slider-header">
                <span className="slider-label-text">Drag to choose</span>
                <span className="slider-value" aria-live="polite">{topStories}</span>
              </div>
              <input
                id="stories-slider"
                type="range"
                className="range-input"
                min={1}
                max={20}
                step={1}
                value={topStories}
                style={{ '--fill-pct': `${fillPct}%` }}
                onChange={(e) => setTopStories(Number(e.target.value))}
                aria-label={`Number of top stories: ${topStories}`}
              />
              <div className="slider-ticks" aria-hidden="true">
                <span className="slider-tick">1</span>
                <span className="slider-tick">5</span>
                <span className="slider-tick">10</span>
                <span className="slider-tick">15</span>
                <span className="slider-tick">20</span>
              </div>
            </div>
          </div>

          <hr className="divider" />

          {/* ── Submit ── */}
          <button
            type="submit"
            className="submit-btn"
            id="submit-news-request"
            disabled={loading || !email}
          >
            {loading ? (
              <>
                <span className="spinner" role="status" aria-label="Loading" />
                Submitting request…
              </>
            ) : (
              <>
                ✨ Get My News Briefing
              </>
            )}
          </button>

          {/* ── Status ── */}
          {status && (
            <div
              className={`status-box ${status.type}`}
              role="alert"
              aria-live="polite"
            >
              <span className="status-icon">
                {status.type === 'success' ? '✅' : '❌'}
              </span>
              <div>
                <div className="status-title">
                  {status.type === 'success' ? 'Request Received!' : 'Something went wrong'}
                </div>
                <p className="status-msg">{status.message}</p>
              </div>
            </div>
          )}
        </form>
      </main>

      {/* Feature pills */}
      <div className="features" aria-label="Key features">
        {[
          { icon: '🤖', text: 'Powered by local Ollama AI' },
          { icon: '🔒', text: 'Private & no tracking' },
          { icon: '📡', text: 'Live RSS feeds' },
          { icon: '⚡', text: 'Async delivery' },
          { icon: '🗞️', text: 'Smart story ranking' },
        ].map(({ icon, text }) => (
          <div key={text} className="feature-pill">
            <span className="pill-icon" aria-hidden="true">{icon}</span>
            {text}
          </div>
        ))}
      </div>
    </div>
  )
}

export default App
