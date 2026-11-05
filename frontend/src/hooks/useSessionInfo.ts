import { useEffect, useState } from 'react'
import { currentSessionError, currentSessionInfo, isHostedSite, onSessionError, onSessionInfo, type ApiError } from '@/services/api'
import type { HostedLimits, SessionInfo } from '@/types/api'

export function useSessionInfo(): SessionInfo | null {
  const [info, setInfo] = useState<SessionInfo | null>(currentSessionInfo)
  useEffect(() => onSessionInfo(setInfo), [])
  return info
}

export function useSessionError(): ApiError | null {
  const [error, setError] = useState<ApiError | null>(currentSessionError)
  useEffect(() => onSessionError(setError), [])
  return error
}

export function useHosted(): { hosted: boolean; limits: HostedLimits | null } {
  const info = useSessionInfo()
  return { hosted: info ? info.hosted : isHostedSite(), limits: info?.limits ?? null }
}
