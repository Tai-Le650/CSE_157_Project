import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import { cn } from '@/lib/utils'

export function UPlotChart({
  options,
  data,
  height = 240,
  className,
  onReady,
}: {
  options: Omit<uPlot.Options, 'width' | 'height'>
  data: uPlot.AlignedData
  height?: number
  className?: string
  onReady?: (plot: uPlot | null) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)
  const dataRef = useRef(data)
  dataRef.current = data
  const readyRef = useRef(onReady)
  readyRef.current = onReady

  useEffect(() => {
    const element = container.current
    if (!element) return
    const instance = new uPlot({ ...options, width: Math.max(200, element.clientWidth), height } as uPlot.Options, dataRef.current, element)
    plot.current = instance
    readyRef.current?.(instance)
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width && width > 0) instance.setSize({ width, height })
    })
    observer.observe(element)
    return () => {
      observer.disconnect()
      readyRef.current?.(null)
      instance.destroy()
      plot.current = null
    }
  }, [options, height])

  useEffect(() => {
    plot.current?.setData(data)
  }, [data])

  return <div ref={container} className={cn('w-full min-w-0', className)} />
}
