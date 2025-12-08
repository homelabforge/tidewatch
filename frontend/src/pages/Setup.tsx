/**
 * Setup Page - Initial Admin Account Creation
 *
 * Allows first-time setup of admin account when TideWatch is newly installed.
 * Includes real-time password validation matching backend requirements.
 */

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, Check, X } from 'lucide-react';
import { toast } from 'sonner';
import { authApi } from '../services/api';
import { useAuth } from '../hooks/useAuth';

export default function Setup() {
  const navigate = useNavigate();
  const { setupComplete, checkAuth } = useAuth();

  // Form state
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  // Validation state
  const [passwordErrors, setPasswordErrors] = useState<string[]>([]);
  const [usernameError, setUsernameError] = useState('');

  // Redirect if setup already complete
  useEffect(() => {
    if (setupComplete) {
      navigate('/', { replace: true });
    }
  }, [setupComplete, navigate]);

  // Password validation (matches backend exactly)
  const validatePassword = (pwd: string): string[] => {
    const errors: string[] = [];
    if (pwd.length < 8) errors.push('At least 8 characters');
    if (!/[a-z]/.test(pwd)) errors.push('One lowercase letter');
    if (!/[A-Z]/.test(pwd)) errors.push('One uppercase letter');
    if (!/\d/.test(pwd)) errors.push('One digit');
    // Match backend regex exactly: r"[!@#$%^&*(),.?\":{}|<>]"
    if (!/[!@#$%^&*(),.?":{}|<>]/.test(pwd)) {
      errors.push('One special character (!@#$%^&*(),.?":{}|<>)');
    }
    return errors;
  };

  // Username validation (matches backend)
  const validateUsername = (user: string): string => {
    if (user.length < 3) return 'Username must be at least 3 characters';
    if (user.length > 100) return 'Username must be less than 100 characters';
    if (!/^[a-zA-Z0-9_-]+$/.test(user)) {
      return 'Username can only contain letters, numbers, underscores, and hyphens';
    }
    return '';
  };

  // Handle password input change
  const handlePasswordChange = (value: string) => {
    setPassword(value);
    setPasswordErrors(validatePassword(value));
  };

  // Handle username blur (validation)
  const handleUsernameBlur = () => {
    setUsernameError(validateUsername(username));
  };

  // Handle cancel - disable auth and go back to dashboard
  const handleCancel = async () => {
    if (!confirm('Cancel setup? Authentication will be disabled and all API endpoints will be publicly accessible.')) {
      return;
    }

    try {
      setIsCancelling(true);
      await authApi.cancelSetup();
      toast.success('Authentication disabled. Redirecting...');
      setTimeout(() => {
        window.location.href = '/';
      }, 1000);
    } catch {
      toast.error('Failed to disable authentication');
      setIsCancelling(false);
    }
  };

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validate username
    const userError = validateUsername(username);
    if (userError) {
      setUsernameError(userError);
      toast.error(userError);
      return;
    }

    // Validate password
    const pwdErrors = validatePassword(password);
    if (pwdErrors.length > 0) {
      toast.error('Password does not meet requirements');
      return;
    }

    // Validate password confirmation
    if (password !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }

    try {
      setIsSubmitting(true);

      // Create admin account
      await authApi.setup({
        username,
        email,
        password,
        full_name: fullName || undefined,
      });

      toast.success('Admin account created successfully');

      // Refresh auth state (JWT cookie already set by backend)
      await checkAuth();

      // Redirect to dashboard
      navigate('/', { replace: true });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to create admin account';
      toast.error(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Password requirement component
  const PasswordRequirement = ({ met, text }: { met: boolean; text: string }) => (
    <div className="flex items-center gap-2 text-sm">
      {met ? (
        <Check className="w-4 h-4 text-green-500" />
      ) : (
        <X className="w-4 h-4 text-red-500" />
      )}
      <span className={met ? 'text-green-500' : 'text-tide-text-muted'}>{text}</span>
    </div>
  );

  return (
    <div className="min-h-screen bg-tide-bg flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="bg-tide-surface border border-tide-border rounded-lg p-8">
          {/* Header */}
          <div className="mb-6 text-center">
            <h1 className="text-2xl font-bold text-tide-text mb-2">Welcome to TideWatch</h1>
            <p className="text-tide-text-muted">Create your admin account to get started</p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Username */}
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-tide-text mb-1">
                Username *
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onBlur={handleUsernameBlur}
                disabled={isSubmitting}
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                required
              />
              {usernameError && (
                <p className="text-red-500 text-sm mt-1">{usernameError}</p>
              )}
            </div>

            {/* Email */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-tide-text mb-1">
                Email *
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isSubmitting}
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                required
              />
            </div>

            {/* Full Name */}
            <div>
              <label htmlFor="fullName" className="block text-sm font-medium text-tide-text mb-1">
                Full Name (optional)
              </label>
              <input
                id="fullName"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                disabled={isSubmitting}
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
              />
            </div>

            {/* Password */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-tide-text mb-1">
                Password *
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => handlePasswordChange(e.target.value)}
                disabled={isSubmitting}
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                required
              />

              {/* Password strength indicators */}
              {password && (
                <div className="mt-2 space-y-1">
                  <PasswordRequirement met={password.length >= 8} text="At least 8 characters" />
                  <PasswordRequirement met={/[a-z]/.test(password)} text="One lowercase letter" />
                  <PasswordRequirement met={/[A-Z]/.test(password)} text="One uppercase letter" />
                  <PasswordRequirement met={/\d/.test(password)} text="One digit" />
                  <PasswordRequirement
                    met={/[!@#$%^&*(),.?":{}|<>]/.test(password)}
                    text="One special character"
                  />
                </div>
              )}
            </div>

            {/* Confirm Password */}
            <div>
              <label htmlFor="confirmPassword" className="block text-sm font-medium text-tide-text mb-1">
                Confirm Password *
              </label>
              <input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={isSubmitting}
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                required
              />
              {confirmPassword && password !== confirmPassword && (
                <p className="text-red-500 text-sm mt-1">Passwords do not match</p>
              )}
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleCancel}
                disabled={isSubmitting || isCancelling}
                className="flex-1 px-4 py-2 bg-tide-bg hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isCancelling ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin inline mr-2" />
                    Cancelling...
                  </>
                ) : (
                  'Cancel'
                )}
              </button>
              <button
                type="submit"
                disabled={isSubmitting || isCancelling || passwordErrors.length > 0 || password !== confirmPassword}
                className="flex-1 px-4 py-2 bg-teal-500 hover:bg-teal-600 text-white rounded-lg font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Creating Account...
                  </>
                ) : (
                  'Create Admin Account'
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
