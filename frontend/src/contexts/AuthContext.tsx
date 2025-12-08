/**
 * Authentication Context for TideWatch
 *
 * Manages authentication state including:
 * - User profile and session status
 * - Auth mode (none, local, OIDC)
 * - Login/logout flows
 * - Profile updates and password changes
 *
 * Pattern follows ThemeContext.tsx for consistency
 */

import { createContext, useState, useEffect, ReactNode } from 'react';
import { toast } from 'sonner';
import { authApi } from '../services/api';
import type { UserProfile } from '../types/auth';

// ============================================================================
// Context Type Definition
// ============================================================================

interface AuthContextType {
  // State
  user: UserProfile | null;
  authMode: "none" | "local" | "oidc";
  isAuthenticated: boolean;
  isLoading: boolean;
  setupComplete: boolean;
  oidcEnabled: boolean;

  // Actions
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
  updateProfile: (email: string, fullName: string) => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// ============================================================================
// Auth Provider Component
// ============================================================================

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [authMode, setAuthMode] = useState<"none" | "local" | "oidc">("none");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [setupComplete, setSetupComplete] = useState(false);
  const [oidcEnabled, setOidcEnabled] = useState(false);

  // Initialize authentication state on mount
  useEffect(() => {
    let mounted = true;

    async function initialize() {
      try {
        setIsLoading(true);

        // 1. Check auth status (also captures CSRF token)
        const status = await authApi.getStatus();
        if (!mounted) return;

        setSetupComplete(status.setup_complete);
        setAuthMode(status.auth_mode);
        setOidcEnabled(status.oidc_enabled);

        // 2. If setup not complete, stop here
        if (!status.setup_complete) {
          if (mounted) setIsLoading(false);
          return;
        }

        // 3. If auth disabled, mark as authenticated
        if (status.auth_mode === "none") {
          if (mounted) {
            setIsAuthenticated(true);
            setIsLoading(false);
          }
          return;
        }

        // 4. Check if logged in
        try {
          const profile = await authApi.getMe();
          if (!mounted) return;

          setUser(profile);
          setIsAuthenticated(true);
          sessionStorage.setItem('wasAuthenticated', 'true');
        } catch {
          // 401 = not logged in
          if (mounted) setIsAuthenticated(false);
        }
      } catch (error) {
        if (mounted) {
          // If auth endpoints don't exist (404), default to auth disabled
          // This allows the app to work when authentication is not yet implemented
          const errorMessage = error instanceof Error ? error.message : String(error);

          if (errorMessage.includes('404') || errorMessage.includes('Not Found')) {
            console.warn('Authentication endpoints not found - defaulting to auth disabled mode');
            setSetupComplete(true);
            setAuthMode('none');
            setIsAuthenticated(true);
          } else {
            console.error('Failed to check authentication status:', error);
            toast.error('Failed to check authentication status');
          }
        }
      } finally {
        if (mounted) setIsLoading(false);
      }
    }

    initialize();

    return () => {
      mounted = false; // Cleanup to prevent state updates on unmounted component
    };
  }, []);

  // Listen for 401 errors from API calls (session expired)
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'auth:401') {
        setIsAuthenticated(false);
        setUser(null);
        // ProtectedRoute will handle redirect
      }
    };

    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, []);

  // ============================================================================
  // Auth Actions
  // ============================================================================

  const login = async (username: string, password: string) => {
    try {
      await authApi.login({ username, password });
      // JWT cookie now set by backend

      // Fetch user profile
      const profile = await authApi.getMe();
      setUser(profile);
      setIsAuthenticated(true);
      sessionStorage.setItem('wasAuthenticated', 'true');
      toast.success('Logged in successfully');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Invalid username or password';
      toast.error(errorMessage);
      throw error;
    }
  };

  const logout = async () => {
    try {
      await authApi.logout();
      setUser(null);
      setIsAuthenticated(false);
      sessionStorage.removeItem('wasAuthenticated');
      toast.success('Logged out successfully');
    } catch (error) {
      console.error('Logout error:', error);
      // Clear state anyway
      setUser(null);
      setIsAuthenticated(false);
      sessionStorage.removeItem('wasAuthenticated');
    }
  };

  const checkAuth = async () => {
    try {
      const status = await authApi.getStatus();
      setSetupComplete(status.setup_complete);
      setAuthMode(status.auth_mode);
      setOidcEnabled(status.oidc_enabled);

      if (status.auth_mode === "none") {
        setIsAuthenticated(true);
        return;
      }

      if (status.setup_complete && status.auth_mode !== "none") {
        try {
          const profile = await authApi.getMe();
          setUser(profile);
          setIsAuthenticated(true);
          sessionStorage.setItem('wasAuthenticated', 'true');
        } catch {
          setIsAuthenticated(false);
          setUser(null);
        }
      }
    } catch (error) {
      console.error('Failed to check auth:', error);
    }
  };

  const updateProfile = async (email: string, fullName: string) => {
    try {
      const updatedProfile = await authApi.updateProfile({
        email,
        full_name: fullName,
      });
      setUser(updatedProfile);
      toast.success('Profile updated successfully');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to update profile';
      toast.error(errorMessage);
      throw error;
    }
  };

  const changePassword = async (currentPassword: string, newPassword: string) => {
    try {
      await authApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast.success('Password changed successfully');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to change password';
      toast.error(errorMessage);
      throw error;
    }
  };

  // ============================================================================
  // Context Value
  // ============================================================================

  const value: AuthContextType = {
    user,
    authMode,
    isAuthenticated,
    isLoading,
    setupComplete,
    oidcEnabled,
    login,
    logout,
    checkAuth,
    updateProfile,
    changePassword,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export { AuthContext };
export type { AuthContextType };
