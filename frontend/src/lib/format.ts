export const DASH = '—'

export function num(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value) || !Number.isFinite(value)) return DASH
  return value.toFixed(digits)
}

export function hz(value: number | null | undefined, digits = 1): string {
  const text = num(value, digits)
  return text === DASH ? 'not measured' : `${text} Hz`
}

export function seconds(value: number | null | undefined, digits = 2): string {
  const text = num(value, digits)
  return text === DASH ? DASH : `${text} s`
}

export function ms(value: number | null | undefined, digits = 1): string {
  const text = num(value, digits)
  return text === DASH ? DASH : `${text} ms`
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH
  return `${(value * 100).toFixed(digits)}%`
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH
  return value.toLocaleString()
}

export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

export function dateTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return DASH
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return DASH
  return date.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function timeOfDay(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH
  return new Date(value * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function relativeAge(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return DASH
  const diff = Date.now() / 1000 - epochSeconds
  if (diff < 5) return 'just now'
  if (diff < 60) return `${Math.round(diff)} s ago`
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`
  return `${Math.round(diff / 3600)} h ago`
}

export function shortId(id: string | null | undefined, keep = 6): string {
  if (!id) return DASH
  const parts = id.split('_')
  return parts.length > 2 ? `${parts[0]}…${parts[parts.length - 1]}` : id.slice(-keep)
}

export function humanize(code: string | null | undefined): string {
  if (!code) return DASH
  return code.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}
