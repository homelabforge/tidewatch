/**
 * useAuth Hook
 *
 * Custom hook to consume the AuthContext.
 * Provides access to authentication state and actions throughout the app.
 *
 * Usage:
 *   const { user, isAuthenticated, login, logout } = useAuth();
 *
 * Throws an error if used outside of AuthProvider.
 */

import { useContext } from 'react';
import { AuthContext, type AuthContextType } from '../contexts/AuthContext';

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);

  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }

  return context;
}
