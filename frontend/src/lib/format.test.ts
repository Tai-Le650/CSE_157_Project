import { describe, expect, it, vi } from 'vitest'
import { DASH, bytes, hz, humanize, ms, num, pct, relativeAge, seconds, shortId } from './format'

describe('format', () => {
  it('shows a dash for missing or non-finite numbers', () => {
    for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(num(value)).toBe(DASH)
      expect(seconds(value)).toBe(DASH)
      expect(ms(value)).toBe(DASH)
      expect(pct(value)).toBe(DASH)
      expect(bytes(value)).toBe(DASH)
    }
  })

  it('says a rate is not measured instead of inventing one', () => {
    expect(hz(null)).toBe('not measured')
    expect(hz(Number.NaN)).toBe('not measured')
    expect(hz(104.0123, 2)).toBe('104.01 Hz')
  })

  it('formats values with units', () => {
    expect(num(3.14159, 2)).toBe('3.14')
    expect(seconds(0.9)).toBe('0.90 s')
    expect(ms(12.345)).toBe('12.3 ms')
    expect(pct(0.9604)).toBe('96.0%')
    expect(bytes(512)).toBe('512 B')
    expect(bytes(2048)).toBe('2.0 KB')
    expect(bytes(3 * 1024 * 1024)).toBe('3.0 MB')
  })

  it('formats relative ages', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-04T12:00:00Z'))
    const now = Date.now() / 1000
    expect(relativeAge(now - 2)).toBe('just now')
    expect(relativeAge(now - 30)).toBe('30 s ago')
    expect(relativeAge(now - 600)).toBe('10 min ago')
    expect(relativeAge(now - 7200)).toBe('2 h ago')
    expect(relativeAge(null)).toBe(DASH)
  })

  it('shortens identifiers and humanizes codes', () => {
    expect(shortId('rec_1730000000000_swipe_left_S1_ab12')).toBe('rec…ab12')
    expect(shortId('abcdef123456')).toBe('123456')
    expect(shortId(null)).toBe(DASH)
    expect(humanize('insufficient_grouped_data')).toBe('Insufficient grouped data')
    expect(humanize('')).toBe(DASH)
  })
})
