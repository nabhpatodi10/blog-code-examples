import { useEffect, useState } from 'react'

export function readJob(value, expectedId) {
  if (
    !value || value.id !== expectedId ||
    !['queued', 'running', 'completed', 'failed'].includes(value.status) ||
    typeof value.progress?.label !== 'string' ||
    !Number.isInteger(value.progress.completed) || value.progress.completed < 0 ||
    !Number.isInteger(value.progress.total) || value.progress.total < 1 ||
    value.progress.completed > value.progress.total ||
    typeof value.result_available !== 'boolean' ||
    !(value.error === null || typeof value.error === 'string')
  ) throw new Error('Invalid job response')
  return value
}

// The caller keys JobProgress by jobId, so each job has an isolated view.
export function useJob(jobId) {
  const [view, setView] = useState({
    job: null, connection: 'checking', message: '',
  })

  useEffect(() => {
    let disposed = false
    let timer
    let request
    let failures = 0

    async function poll() {
      request = new AbortController()
      const deadline = setTimeout(() => request.abort(), 10000)
      let delay = 2000
      try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
          signal: request.signal, cache: 'no-store',
        })
        if (disposed) return
        if ([400, 401, 403, 404, 422].includes(response.status)) {
          setView(previous => ({
            ...previous, connection: 'unavailable',
            message: 'This job is unavailable. Check the identifier and your access.',
          }))
          return
        }
        if (!response.ok) throw new Error('Status request failed')
        const job = readJob(await response.json(), jobId)
        if (disposed) return
        failures = 0
        setView({ job, connection: 'connected', message: '' })
        if (['completed', 'failed'].includes(job.status)) return
      } catch {
        if (disposed) return
        failures += 1
        delay = Math.min(10000, 2000 * 2 ** failures)
        setView(previous => ({
          ...previous, connection: 'reconnecting',
          message: 'Unable to refresh status. Checking again.',
        }))
      } finally {
        clearTimeout(deadline)
      }
      if (!disposed) timer = setTimeout(poll, delay)
    }

    void poll()
    return () => {
      disposed = true
      clearTimeout(timer)
      request?.abort()
    }
  }, [jobId])
  return view
}
