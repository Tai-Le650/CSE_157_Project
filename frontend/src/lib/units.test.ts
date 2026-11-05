import { describe, expect, it } from 'vitest'
import { STANDARD_GRAVITY, accelFactor, gyroFactor, isAccel, unitLabel } from './units'

describe('units', () => {
  it('converts with the standard factors', () => {
    expect(STANDARD_GRAVITY).toBe(9.80665)
    expect(accelFactor('g')).toBe(1)
    expect(accelFactor('m/s2')).toBe(9.80665)
    expect(gyroFactor('deg/s')).toBe(1)
    expect(180 * gyroFactor('rad/s')).toBeCloseTo(Math.PI, 12)
  })

  it('labels each channel with its own unit', () => {
    expect(unitLabel('ax', 'm/s2', 'rad/s')).toBe('m/s²')
    expect(unitLabel('amag', 'g', 'deg/s')).toBe('g')
    expect(unitLabel('gz', 'g', 'deg/s')).toBe('°/s')
    expect(unitLabel('gmag', 'm/s2', 'rad/s')).toBe('rad/s')
    expect(isAccel('az')).toBe(true)
    expect(isAccel('gmag')).toBe(false)
  })
})
