import type { ReactNode } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AppShell } from '@/components/layout/AppShell'
import { AppStateProvider, useAppState } from '@/hooks/useAppState'
import { ThemeProvider } from '@/hooks/useTheme'
import { DashboardPage } from '@/pages/DashboardPage'
import { DatasetsPage } from '@/pages/DatasetsPage'
import { ErrorPage } from '@/pages/ErrorPage'
import { LiveDataPage } from '@/pages/LiveDataPage'
import { MappingsPage } from '@/pages/MappingsPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { RecognitionPage } from '@/pages/RecognitionPage'
import { RecorderPage } from '@/pages/RecorderPage'
import { SensorsPage } from '@/pages/SensorsPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { SoundPage } from '@/pages/SoundPage'
import { TrainingPage } from '@/pages/TrainingPage'

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <ErrorPage />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'sensors', element: <SensorsPage /> },
      { path: 'live', element: <LiveDataPage /> },
      { path: 'recorder', element: <RecorderPage /> },
      { path: 'datasets', element: <DatasetsPage /> },
      { path: 'training', element: <TrainingPage /> },
      { path: 'recognition', element: <RecognitionPage /> },
      { path: 'mappings', element: <MappingsPage /> },
      { path: 'sound', element: <SoundPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

function ThemeBridge({ children }: { children: ReactNode }) {
  const { settings } = useAppState()
  return <ThemeProvider serverTheme={settings?.theme ?? null}>{children}</ThemeProvider>
}

export default function App() {
  return (
    <AppStateProvider>
      <ThemeBridge>
        <TooltipProvider delayDuration={250}>
          <RouterProvider router={router} />
          <Toaster richColors closeButton position="bottom-right" />
        </TooltipProvider>
      </ThemeBridge>
    </AppStateProvider>
  )
}
