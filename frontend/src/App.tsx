import { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Toaster } from 'sonner';
import { Wifi, WifiOff } from 'lucide-react';
import Navigation from './components/Navigation';
import Footer from './components/Footer';
import PageSkeleton from './components/PageSkeleton';
import { ProtectedRoute } from './components/ProtectedRoute';
import { useEventStream } from './hooks/useEventStream';
import { ThemeProvider, useTheme } from './contexts/ThemeContext';
import { AuthProvider } from './contexts/AuthContext';

// Lazy-loaded page components for code splitting
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Updates = lazy(() => import('./pages/Updates'));
const History = lazy(() => import('./pages/History'));
const Settings = lazy(() => import('./pages/Settings'));
const About = lazy(() => import('./pages/About'));

// Auth pages (not lazy-loaded for faster initial auth experience)
import Setup from './pages/Setup';
import Login from './pages/Login';
import LinkAccount from './pages/LinkAccount';

function AppContent() {
  // Initialize event stream for real-time updates
  const { connectionStatus } = useEventStream({
    enableToasts: true,
  });

  // Get current theme for dynamic Sonner theming
  const { theme } = useTheme();

  return (
    <Router>
      <Routes>
        {/* Public routes - Auth pages */}
        <Route path="/setup" element={<Setup />} />
        <Route path="/login" element={<Login />} />
        <Route path="/auth/link-account" element={<LinkAccount />} />

        {/* Protected routes - Main app */}
        <Route path="/*" element={
          <ProtectedRoute>
            <div className="min-h-screen bg-tide-bg flex flex-col">
              <Navigation />
              <main className="flex-1">
                <Suspense fallback={<PageSkeleton />}>
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/updates" element={<Updates />} />
                    <Route path="/history" element={<History />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="/about" element={<About />} />
                  </Routes>
                </Suspense>
              </main>
              <Footer />

              {/* Connection Status Indicator */}
              <div className="fixed bottom-4 right-4 z-50">
                {connectionStatus === 'connected' && (
                  <div className="flex items-center gap-2 px-3 py-2 bg-green-500/10 border border-green-500/20 rounded-lg">
                    <Wifi className="w-4 h-4 text-green-400" />
                    <span className="text-xs text-green-400">Live</span>
                  </div>
                )}
                {connectionStatus === 'reconnecting' && (
                  <div className="flex items-center gap-2 px-3 py-2 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
                    <WifiOff className="w-4 h-4 text-yellow-400 animate-pulse" />
                    <span className="text-xs text-yellow-400">Reconnecting...</span>
                  </div>
                )}
                {connectionStatus === 'disconnected' && (
                  <div className="flex items-center gap-2 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg">
                    <WifiOff className="w-4 h-4 text-red-400" />
                    <span className="text-xs text-red-400">Offline</span>
                  </div>
                )}
              </div>
            </div>
          </ProtectedRoute>
        } />
      </Routes>

      <Toaster
        position="top-right"
        richColors
        closeButton
        theme={theme}
        toastOptions={{
          style: {
            background: theme === 'dark' ? '#1f2937' : '#ffffff',
            border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
            color: theme === 'dark' ? '#f9fafb' : '#111827',
          },
        }}
      />
    </Router>
  );
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
