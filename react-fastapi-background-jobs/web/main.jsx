import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useJob } from './useJob'
import './style.css'

function JobProgress({ jobId }) {
  const { job, connection, message } = useJob(jobId)
  const active = job && ['queued', 'running'].includes(job.status)
  return (
    <section aria-label="Current report">
      <p className="eyebrow">Current job</p>
      <p className="identifier">{jobId}</p>
      {message && <p role="alert" className="notice">{message}</p>}
      {!job && connection === 'checking' && <p role="status">Checking job status…</p>}
      {job && <>
        <h2>{job.status === 'completed' ? 'Report complete' : job.status === 'failed' ? 'Report failed' : 'Report in progress'}</h2>
        <p role="status">{job.progress.label}</p>
        {active && <>
          <label htmlFor="report-progress">Sections written</label>
          <progress id="report-progress" max={job.progress.total} value={job.progress.completed} />
          <p>{job.progress.completed} of {job.progress.total} sections</p>
        </>}
        {job.status === 'failed' && <p role="alert">{job.error || 'The worker recorded a failure.'}</p>}
        {job.status === 'completed' && (job.result_available
          ? <a className="button" href={`/api/jobs/${encodeURIComponent(job.id)}/result`}>Download report</a>
          : <p role="alert">The job says completed, but no result is available.</p>)}
      </>}
    </section>
  )
}

function App() {
  const [jobId, setJobId] = useState(() => new URL(location.href).searchParams.get('job'))
  const [mode, setMode] = useState('success')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [jobs, setJobs] = useState([])
  const [listError, setListError] = useState('')
  const creationInFlight = useRef(false)

  async function refreshJobs() {
    try {
      const response = await fetch('/api/jobs', { cache: 'no-store' })
      if (!response.ok) throw new Error('Cannot load jobs')
      setJobs(await response.json())
      setListError('')
    } catch {
      setListError('Unable to retrieve existing jobs. Try refreshing the list.')
    }
  }

  useEffect(() => {
    const onPopState = () => setJobId(new URL(location.href).searchParams.get('job'))
    window.addEventListener('popstate', onPopState)
    void refreshJobs()
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  function openJob(id) {
    const url = new URL(location.href)
    url.searchParams.set('job', id)
    history.pushState(null, '', url)
    setJobId(id)
  }

  async function createJob(event) {
    event.preventDefault()
    if (creationInFlight.current) return
    creationInFlight.current = true
    setCreating(true)
    setCreateError('')
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 10000)
    try {
      const response = await fetch('/api/jobs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }), signal: controller.signal,
      })
      if (!response.ok) throw new Error('Create response failed')
      const job = await response.json()
      if (typeof job.id !== 'string') throw new Error('Missing job identifier')
      openJob(job.id)
      void refreshJobs()
    } catch {
      setCreateError('Could not confirm job creation. Refresh Existing jobs before starting another report.')
    } finally {
      clearTimeout(timeout)
      creationInFlight.current = false
      setCreating(false)
    }
  }

  return (
    <main>
      <header>
        <p className="eyebrow">React + FastAPI · Local teaching example</p>
        <h1>A job you can come back to.</h1>
        <p>Start writing a report, refresh while it is being written, or briefly disconnect. You can return to the same job.</p>
      </header>
      <form onSubmit={createJob}>
        <label htmlFor="outcome">Worker outcome</label>
        <select id="outcome" value={mode} onChange={event => setMode(event.target.value)} disabled={creating}>
          <option value="success">Complete the report</option>
          <option value="failure">Fail during section 2</option>
        </select>
        <button type="submit" disabled={creating}>{creating ? 'Starting…' : 'Write report'}</button>
        {createError && <p role="alert">{createError}</p>}
      </form>
      {jobId && <JobProgress key={jobId} jobId={jobId} />}
      <section aria-label="Existing jobs">
        <h2>Existing jobs</h2>
        <p>This list lets you reconcile a create request if its acknowledgement was lost.</p>
        <button type="button" onClick={refreshJobs}>Refresh existing jobs</button>
        {listError && <p role="alert">{listError}</p>}
        <ul>{jobs.map(job => <li key={job.id}>
          <a href={`?job=${encodeURIComponent(job.id)}`} onClick={event => { event.preventDefault(); openJob(job.id) }}>
            {job.id}
          </a><span> · {job.status}</span>
        </li>)}</ul>
      </section>
      <footer>Local demonstration only. No authentication or multi-worker coordination. Runs without analytics or external providers.</footer>
    </main>
  )
}

createRoot(document.getElementById('root')).render(<App />)
