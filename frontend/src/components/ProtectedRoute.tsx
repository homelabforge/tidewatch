/**
 * ProtectedRoute Component
 *
 * Route guard that protects pages based on authentication status.
 *
 * Behavior:
 * - Shows loading spinner while checking auth
 * - Redirects to /setup if setup not complete
 * - Allows access if auth_mode is "none"
 * - Redirects to /login if not authenticated (with returnUrl)
 * - Renders children if authenticated
 */

import { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

interface ProtectedRouteProps {
  children: ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, authMode, setupComplete } = useAuth();
  const location = useLocation();

  // Still checking auth status - show minimal spinner
  if (isLoading) {
    return (
      <div className="min-h-screen bg-tide-bg flex items-center justify-center">
        <RefreshCw className="animate-spin text-primary" size={32} />
      </div>
    );
  }

  // Setup not complete - redirect to setup page
  if (!setupComplete) {
    return <Navigate to="/setup" replace />;
  }

  // Auth disabled - allow access to all routes
  if (authMode === "none") {
    return <>{children}</>;
  }

  // Auth required but user not authenticated - redirect to login
  if (!isAuthenticated) {
    // Save return URL for redirect after successful login
    const returnUrl = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?returnUrl=${returnUrl}`} replace />;
  }

  // User is authenticated - render protected content
  return <>{children}</>;
}
