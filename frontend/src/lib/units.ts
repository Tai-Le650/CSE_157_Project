import type { Channel } from '@/types/api'

export const STANDARD_GRAVITY = 9.80665
export const DEG_TO_RAD = Math.PI / 180

export type AccelUnit = 'g' | 'm/s2'
export type GyroUnit = 'deg/s' | 'rad/s'

export const CHANNELS: Channel[] = ['ax', 'ay', 'az', 'gx', 'gy', 'gz', 'amag', 'gmag']
export const ACCEL_CHANNELS: Channel[] = ['ax', 'ay', 'az', 'amag']
export const GYRO_CHANNELS: Channel[] = ['gx', 'gy', 'gz', 'gmag']

export const CHANNEL_LABELS: Record<Channel, string> = {
  ax: 'ax',
  ay: 'ay',
  az: 'az',
  gx: 'gx',
  gy: 'gy',
  gz: 'gz',
  amag: '|a|',
  gmag: '|ω|',
}

export function isAccel(channel: Channel): boolean {
  return ACCEL_CHANNELS.includes(channel)
}

export function accelFactor(unit: AccelUnit): number {
  return unit === 'm/s2' ? STANDARD_GRAVITY : 1
}

export function gyroFactor(unit: GyroUnit): number {
  return unit === 'rad/s' ? DEG_TO_RAD : 1
}

export function unitLabel(channel: Channel, accel: AccelUnit, gyro: GyroUnit): string {
  if (isAccel(channel)) return accel === 'm/s2' ? 'm/s²' : 'g'
  return gyro === 'rad/s' ? 'rad/s' : '°/s'
}

export function seriesColorVar(channel: Channel): string {
  return `--series-${channel}`
}

export function cssVar(name: string, fallback = '#888'): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}
