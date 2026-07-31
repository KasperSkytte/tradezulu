import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { ApiError } from './lib/api'
import { AuthProvider } from './lib/auth'
import { App } from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Re-authenticating is the user's job, not the query client's.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
        return failureCount < 2
      },
    },
  },
})

// The service worker precaches the whole app, so a page that is already open
// keeps running the version it started with. `autoUpdate` installs the new
// worker and lets it claim the page, but nothing reloads -- so after an update
// the app carries on serving the old bundle, and a feature that shipped days
// ago looks like it was never built. Installed as a PWA, where the window is
// rarely closed, that can last indefinitely.
//
// `controllerchange` fires exactly when the new worker takes over. Reloading
// once there is the only moment the fresh assets are guaranteed to be cached
// and ready. The flag guards the reload loop this otherwise invites.
if ('serviceWorker' in navigator) {
  let reloading = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading) return
    reloading = true
    window.location.reload()
  })
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
