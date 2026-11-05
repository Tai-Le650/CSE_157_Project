declare module 'plotly.js-cartesian-dist-min' {
  interface PlotlyStatic {
    react(element: HTMLElement, data: Record<string, unknown>[], layout?: Record<string, unknown>, config?: Record<string, unknown>): Promise<unknown>
    purge(element: HTMLElement): void
    Plots: { resize(element: HTMLElement): void }
  }
  const Plotly: PlotlyStatic
  export default Plotly
}
