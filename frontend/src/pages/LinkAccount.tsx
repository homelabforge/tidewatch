/**
 * Link Account Page - OIDC Password Verification
 *
 * This page is shown after OIDC callback when the admin account requires
 * password verification to link the OIDC identity.
 *
 * Security:
 * - Max 3 password attempts per token
 * - Token expires after 5 minutes
 * - One-time use (token deleted after success)
 */

import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { RefreshCw, Eye, EyeOff, Shield, X } from 'lucide-react';
import { toast } from 'sonner';
import { authApi } from '../services/api';
import { useAuth } from '../hooks/useAuth';

const MAX_ATTEMPTS = 3;

export default function LinkAccount() {
  const navigate = useNavigate();
  const location = useLocation();
  const { checkAuth } = useAuth();

  // Parse token from URL
  const searchParams = new URLSearchParams(location.search);
  const token = searchParams.get('token');

  // Form state
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [attemptCount, setAttemptCount] = useState(0);

  // Redirect if no token
  useEffect(() => {
    if (!token) {
      toast.error('Invalid or missing link token');
      navigate('/login', { replace: true });
    }
  }, [token, navigate]);

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!token) return;

    try {
      setIsSubmitting(true);

      // Attempt to link account with password verification
      await authApi.oidc.linkAccount({ token, password });

      toast.success('Account linked successfully');

      // Refresh auth state (JWT cookie now set)
      await checkAuth();

      // Redirect to dashboard
      navigate('/', { replace: true });
    } catch {
      setAttemptCount((prev) => prev + 1);

      if (attemptCount + 1 >= MAX_ATTEMPTS) {
        toast.error('Maximum attempts exceeded. Logging out.');

        // Logout and redirect to login
        try {
          await authApi.logout();
        } catch {
          // Ignore logout errors
        }

        navigate('/login', { replace: true });
      } else {
        const remaining = MAX_ATTEMPTS - attemptCount - 1;
        toast.error(`Invalid password. ${remaining} attempt${remaining !== 1 ? 's' : ''} remaining.`);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle cancel
  const handleCancel = async () => {
    try {
      await authApi.logout();
    } catch {
      // Ignore logout errors
    }

    navigate('/login', { replace: true });
  };

  // Handle Enter key
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !isSubmitting) {
      handleSubmit(e as unknown as React.FormEvent);
    }
  };

  return (
    <div className="min-h-screen bg-tide-bg flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="bg-tide-surface border border-tide-border rounded-lg p-8">
          {/* Header */}
          <div className="mb-6 text-center">
            <div className="inline-flex items-center justify-center w-12 h-12 bg-teal-500/10 rounded-full mb-4">
              <Shield className="w-6 h-6 text-teal-500" />
            </div>
            <h1 className="text-2xl font-bold text-tide-text mb-2">Link SSO Account</h1>
            <p className="text-tide-text-muted">
              Please verify your admin password to link this SSO account to your TideWatch profile.
            </p>
          </div>

          {/* Attempt Counter */}
          {attemptCount > 0 && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
              <p className="text-sm text-red-500 text-center">
                {attemptCount} of {MAX_ATTEMPTS} attempts used
              </p>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} onKeyDown={handleKeyDown} className="space-y-4">
            {/* Password */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-tide-text mb-1">
                Admin Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isSubmitting}
                  aria-label="Password"
                  aria-describedby="password-toggle"
                  className="w-full px-3 py-2 pr-10 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                  required
                  autoComplete="current-password"
                  autoFocus
                />
                <button
                  id="password-toggle"
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-tide-text-muted hover:text-tide-text transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            {/* Buttons */}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleCancel}
                disabled={isSubmitting}
                className="flex-1 px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <X className="w-4 h-4" />
                Cancel
              </button>

              <button
                type="submit"
                disabled={isSubmitting}
                className="flex-1 px-4 py-2 bg-teal-500 hover:bg-teal-600 text-white rounded-lg font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Verifying...
                  </>
                ) : (
                  <>
                    <Shield className="w-4 h-4" />
                    Link Account
                  </>
                )}
              </button>
            </div>
          </form>

          {/* Help Text */}
          <div className="mt-6 text-center">
            <p className="text-sm text-tide-text-muted">
              This is a one-time verification to securely link your SSO identity.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
