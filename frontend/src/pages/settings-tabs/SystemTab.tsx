import { useState, useEffect } from 'react';
import { RotateCcw, Shield, Cpu, X, ChevronDown, ChevronRight, Sun, Moon, Lock, User, Eye, EyeOff, Check, Info, RefreshCw, CircleCheck, Settings as SettingsIcon } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '../../services/api';
import type { SettingCategory } from '../../types';
import type { OIDCConfig } from '../../types/auth';
import { useTheme } from '../../contexts/ThemeContext';
import { useAuth } from '../../hooks/useAuth';
import { HelpTooltip } from '../../components/HelpTooltip';

interface SystemTabProps {
  settings: Record<string, unknown>;
  saving: boolean;
  updateSetting: (key: string, value: unknown, updateState?: boolean) => Promise<void>;
  handleTextChange: (key: string, value: string) => void;
  categories: SettingCategory[];
  loadSettings: () => Promise<void>;
}

export default function SystemTab({ settings, saving, updateSetting, categories, loadSettings }: SystemTabProps) {
  const { theme, setTheme } = useTheme();
  const { user, authMode, updateProfile, changePassword } = useAuth();

  // Category state
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());

  // Auth modal states
  const [editProfileModalOpen, setEditProfileModalOpen] = useState(false);
  const [changePasswordModalOpen, setChangePasswordModalOpen] = useState(false);
  const [enableLocalAuthModalOpen, setEnableLocalAuthModalOpen] = useState(false);
  const [enableOidcAuthModalOpen, setEnableOidcAuthModalOpen] = useState(false);
  const [oidcConfigModalOpen, setOidcConfigModalOpen] = useState(false);

  // Profile editing state
  const [profileEmail, setProfileEmail] = useState('');
  const [profileFullName, setProfileFullName] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);

  // Password change state
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [changingPassword, setChangingPassword] = useState(false);
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // OIDC state
  const [oidcConfig, setOidcConfig] = useState({
    enabled: false,
    issuer_url: '',
    client_id: '',
    client_secret: '',
    provider_name: '',
    scopes: 'openid email profile',
    redirect_uri: '',
  });
  const [savingOidc, setSavingOidc] = useState(false);
  const [testingOidc, setTestingOidc] = useState(false);
  const [showOidcSecret, setShowOidcSecret] = useState(false);

  // Initialize profile form when modal opens
  useEffect(() => {
    if (editProfileModalOpen && user) {
      setProfileEmail(user.email || '');
      setProfileFullName(user.full_name || '');
    }
  }, [editProfileModalOpen, user]);

  // Load user profile when tab mounts
  useEffect(() => {
    if (user) {
      setProfileEmail(user.email);
      setProfileFullName(user.full_name || '');
    }
  }, [user]);

  // Load OIDC config
  useEffect(() => {
    if (authMode !== 'none') {
      api.auth.oidc.getConfig().then((config) => {
        setOidcConfig(config as OIDCConfig);
      }).catch((error) => {
        console.error('Failed to load OIDC config:', error);
      });
    }
  }, [authMode]);

  const toggleCategory = (category: string) => {
    setCollapsedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  const getCategoryIcon = (category: string) => {
    const icons: Record<string, typeof SettingsIcon> = {
      system: Cpu,
      docker: Cpu,
    };
    return icons[category] || SettingsIcon;
  };

  const getCategoryTitle = (category: string) => {
    const titles: Record<string, string> = {
      system: 'System Configuration',
      docker: 'Docker Settings',
    };
    return titles[category] || category.charAt(0).toUpperCase() + category.slice(1);
  };

  const handleResetSettings = async () => {
    if (!confirm('Are you sure you want to reset ALL settings to defaults? This action cannot be undone.')) {
      return;
    }

    try {
      const result = await api.settings.reset();
      toast.success(result.message || 'Settings reset to defaults');
      await loadSettings();
    } catch (error) {
      console.error('Failed to reset settings:', error);
      toast.error('Failed to reset settings');
    }
  };

  const handleSaveOidcConfig = async () => {
    try {
      setSavingOidc(true);
      await api.auth.oidc.updateConfig(oidcConfig as OIDCConfig);
      toast.success('OIDC configuration saved successfully');
    } catch (error) {
      console.error('Failed to save OIDC config:', error);
      toast.error('Failed to save OIDC configuration');
    } finally {
      setSavingOidc(false);
    }
  };

  const handleTestOidcConnection = async () => {
    try {
      setTestingOidc(true);
      const result = await api.auth.oidc.testConnection(oidcConfig as OIDCConfig);

      if (result.success) {
        toast.success('OIDC connection successful!');
      } else {
        toast.error(`OIDC connection failed: ${result.errors.join(', ')}`);
      }
    } catch (error) {
      console.error('Failed to test OIDC:', error);
      toast.error('Failed to test OIDC connection');
    } finally {
      setTestingOidc(false);
    }
  };

  return (
    <>
      <div className="space-y-6">
        {/* Category-based view if categories available */}
        {categories.length > 0 && (
          <div className="space-y-4">
            {categories
              .filter((cat) => cat.category === 'system' || cat.category === 'docker')
              .map((category) => {
                const Icon = getCategoryIcon(category.category);
                const isCollapsed = collapsedCategories.has(category.category);

                return (
                  <div key={category.category} className="bg-tide-surface/50 rounded-lg border border-tide-border">
                    {/* Category Header */}
                    <button
                      onClick={() => toggleCategory(category.category)}
                      className="w-full flex items-center justify-between p-4 hover:bg-tide-surface/70 transition-colors rounded-lg"
                    >
                      <div className="flex items-center gap-3">
                        <Icon className="w-5 h-5 text-teal-400" />
                        <div className="text-left">
                          <h3 className="text-sm font-semibold text-tide-text">{getCategoryTitle(category.category)}</h3>
                          <p className="text-xs text-tide-text-muted mt-0.5">
                            {category.settings.length} {category.settings.length === 1 ? 'setting' : 'settings'}
                          </p>
                        </div>
                      </div>
                      {isCollapsed ? (
                        <ChevronRight className="w-5 h-5 text-tide-text-muted" />
                      ) : (
                        <ChevronDown className="w-5 h-5 text-tide-text-muted" />
                      )}
                    </button>

                    {/* Category Content */}
                    {!isCollapsed && (
                      <div className="p-4 pt-0 space-y-4">
                        {category.settings.map((setting) => (
                          <div key={setting.key} className="bg-tide-surface/50 rounded-lg p-4">
                            <div className="flex items-start justify-between gap-4">
                              <div className="flex-1">
                                <label className="block text-sm font-medium text-tide-text">
                                  {setting.key.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                                </label>
                                {setting.description && (
                                  <p className="text-xs text-tide-text-muted mt-1">{setting.description}</p>
                                )}
                              </div>
                              <div className="flex-shrink-0">
                                {/* Boolean Toggle */}
                                {typeof settings[setting.key] === 'boolean' && (
                                  <button
                                    type="button"
                                    onClick={() => updateSetting(setting.key, !settings[setting.key])}
                                    disabled={saving}
                                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                                      settings[setting.key] ? 'bg-teal-500' : 'bg-red-500'
                                    }`}
                                  >
                                    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                      settings[setting.key] ? 'translate-x-6' : 'translate-x-1'
                                    }`}></span>
                                  </button>
                                )}
                                {/* Text/Number Input */}
                                {typeof settings[setting.key] !== 'boolean' && (
                                  <input
                                    type={typeof settings[setting.key] === 'number' ? 'number' : 'text'}
                                    value={String(settings[setting.key] || '')}
                                    onChange={(e) => {
                                      const value = typeof settings[setting.key] === 'number'
                                        ? parseInt(e.target.value) || 0
                                        : e.target.value;
                                      updateSetting(setting.key, value);
                                    }}
                                    disabled={saving}
                                    className="w-48 bg-tide-surface text-tide-text text-sm rounded px-3 py-1.5 border border-tide-border-light focus:border-teal-500 focus:outline-none"
                                  />
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        )}

        {/* Original hardcoded cards (show when NO categories) */}
        {categories.length === 0 && (
        <>
          {/* Danger Zone - At Top */}
          <div className="border border-red-500/30 bg-red-500/5 rounded-lg p-6">
            <div className="flex items-start gap-3 mb-4">
              <Shield className="w-6 h-6 text-red-500 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <h2 className="text-xl font-semibold text-red-500 mb-1">Danger Zone</h2>
                <p className="text-sm text-tide-text-muted">Destructive actions that cannot be undone</p>
              </div>
            </div>
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-tide-surface/50 rounded-lg border border-tide-border">
                <div>
                  <h3 className="text-sm font-semibold text-tide-text mb-1">Reset All Settings</h3>
                  <p className="text-xs text-tide-text-muted">Restore all configuration settings to their default values</p>
                </div>
                <button
                  onClick={handleResetSettings}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 text-tide-text rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                >
                  <RotateCcw className="w-4 h-4" />
                  Reset to Defaults
                </button>
              </div>
            </div>
          </div>

          {/* Masonry Two-Column Layout */}
          <div className="columns-1 md:columns-2 gap-4 space-y-4">
            {/* Theme Card */}
            <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  {theme === 'dark' ? (
                    <Moon className="w-6 h-6 text-teal-500" />
                  ) : (
                    <Sun className="w-6 h-6 text-teal-500" />
                  )}
                  <div>
                    <h2 className="text-xl font-semibold text-tide-text">Theme</h2>
                    <p className="text-sm text-tide-text-muted mt-0.5">Choose your preferred interface theme</p>
                  </div>
                </div>
                <HelpTooltip content="Select your preferred visual theme. Dark mode is easier on the eyes in low-light conditions, while Light mode provides better visibility in bright environments. Your preference is saved automatically." />
              </div>

              <div className="flex gap-3">
                <button
                  onClick={() => setTheme('dark')}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                    theme === 'dark'
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-tide-border-light bg-tide-surface text-tide-text hover:border-tide-border-light'
                  }`}
                >
                  <Moon className="w-5 h-5" />
                  <span className="font-medium">Dark</span>
                </button>
                <button
                  onClick={() => setTheme('light')}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                    theme === 'light'
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-tide-border-light bg-tide-surface text-tide-text hover:border-tide-border-light'
                  }`}
                >
                  <Sun className="w-5 h-5" />
                  <span className="font-medium">Light</span>
                </button>
              </div>
            </div>

            {/* Authentication Card */}
            <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <Lock className="w-6 h-6 text-teal-500" />
                  <div>
                    <h2 className="text-xl font-semibold text-tide-text">Authentication</h2>
                    <p className="text-sm text-tide-text-muted mt-0.5">
                      {authMode === 'none' ? 'Authentication is disabled' :
                       authMode === 'local' ? 'Local username/password authentication' :
                       'SSO/OIDC authentication'}
                    </p>
                  </div>
                </div>
                <HelpTooltip content="Control authentication settings. When disabled, all API endpoints are publicly accessible. Enable local auth for username/password or OIDC for Single Sign-On integration." />
              </div>

              {authMode === 'none' ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 px-4 py-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
                    <Info className="w-5 h-5 text-yellow-500 flex-shrink-0" />
                    <p className="text-sm text-yellow-500">
                      All API endpoints are publicly accessible. Enable authentication below to secure your instance.
                    </p>
                  </div>

                  {/* Auth Mode Selector */}
                  <div className="space-y-3">
                    <label className="block text-sm font-medium text-tide-text">
                      Choose Authentication Method
                    </label>
                    <div className="space-y-2">
                      <button
                        onClick={() => setEnableLocalAuthModalOpen(true)}
                        className="w-full px-4 py-3 bg-tide-bg hover:bg-tide-surface-light text-left border border-tide-border rounded-lg transition-colors group"
                      >
                        <div className="flex items-center gap-3">
                          <div className="flex-shrink-0 w-10 h-10 bg-teal-500/10 rounded-lg flex items-center justify-center group-hover:bg-teal-500/20 transition-colors">
                            <User className="w-5 h-5 text-teal-500" />
                          </div>
                          <div className="flex-1">
                            <div className="font-medium text-tide-text">Local Authentication</div>
                            <div className="text-sm text-tide-text-muted">Username and password login</div>
                          </div>
                        </div>
                      </button>

                      <button
                        onClick={() => setEnableOidcAuthModalOpen(true)}
                        className="w-full px-4 py-3 bg-tide-bg hover:bg-tide-surface-light text-left border border-tide-border rounded-lg transition-colors group"
                      >
                        <div className="flex items-center gap-3">
                          <div className="flex-shrink-0 w-10 h-10 bg-teal-500/10 rounded-lg flex items-center justify-center group-hover:bg-teal-500/20 transition-colors">
                            <Shield className="w-5 h-5 text-teal-500" />
                          </div>
                          <div className="flex-1">
                            <div className="font-medium text-tide-text">OIDC/SSO Authentication</div>
                            <div className="text-sm text-tide-text-muted">Single Sign-On with OAuth2/OpenID Connect</div>
                          </div>
                        </div>
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* User info summary */}
                  {user && (
                    <div className="flex items-center gap-3 px-4 py-3 bg-tide-bg rounded-lg">
                      <User className="w-5 h-5 text-teal-500" />
                      <div className="flex-1">
                        <p className="text-sm font-medium text-tide-text">{user.username}</p>
                        <p className="text-xs text-tide-text-muted">{user.email}</p>
                      </div>
                      <span className="px-2 py-1 bg-teal-500/10 text-teal-500 rounded text-xs font-medium">
                        {user.auth_method === 'oidc' ? `SSO (${user.oidc_provider})` : 'Local'}
                      </span>
                    </div>
                  )}

                  {/* Quick actions */}
                  <div className="grid grid-cols-2 gap-3">
                    <button
                      onClick={() => setEditProfileModalOpen(true)}
                      className="px-4 py-2 bg-tide-bg hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg font-medium transition-colors text-sm"
                    >
                      Edit Profile
                    </button>
                    {user?.auth_method === 'local' && (
                      <button
                        onClick={() => setChangePasswordModalOpen(true)}
                        className="px-4 py-2 bg-tide-bg hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg font-medium transition-colors text-sm"
                      >
                        Change Password
                      </button>
                    )}
                  </div>

                  {/* OIDC and Disable Auth Buttons */}
                  <div className="grid grid-cols-2 gap-3">
                    <button
                      onClick={() => setOidcConfigModalOpen(true)}
                      className="px-4 py-2 bg-tide-bg hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg font-medium transition-colors text-sm flex items-center justify-center gap-2"
                    >
                      <Shield className="w-4 h-4" />
                      OIDC/SSO
                    </button>
                    <button
                      onClick={async () => {
                        if (!confirm('Are you sure you want to disable authentication? All API endpoints will become publicly accessible.')) {
                          return;
                        }
                        try {
                          await api.settings.update('auth_mode', 'none');
                          toast.success('Authentication disabled. Refreshing...');
                          setTimeout(() => window.location.reload(), 1000);
                        } catch {
                          toast.error('Failed to disable authentication');
                        }
                      }}
                      className="px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-500 border border-red-500/30 rounded-lg font-medium transition-colors text-sm"
                    >
                      Disable Auth
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Timezone Card */}
            <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <Cpu className="w-6 h-6 text-teal-500" />
                  <div>
                    <h2 className="text-xl font-semibold text-tide-text">Timezone</h2>
                    <p className="text-sm text-tide-text-muted mt-0.5">Set system timezone for schedules and timestamps</p>
                  </div>
                </div>
                <HelpTooltip content="Affects log timestamps and scheduled task times. Use the dropdown for common timezones or enter a custom IANA identifier (e.g., America/Phoenix). Changes apply immediately to new timestamps." />
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-tide-text mb-2">
                    Timezone
                  </label>
                  <select
                    value={String(settings.timezone || 'UTC')}
                    onChange={(e) => updateSetting('timezone', e.target.value)}
                    className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                  >
                    <option value="UTC">UTC</option>
                    <option value="America/New_York">America/New_York (EST/EDT)</option>
                    <option value="America/Chicago">America/Chicago (CST/CDT)</option>
                    <option value="America/Denver">America/Denver (MST/MDT)</option>
                    <option value="America/Los_Angeles">America/Los_Angeles (PST/PDT)</option>
                    <option value="Europe/London">Europe/London</option>
                    <option value="Europe/Paris">Europe/Paris</option>
                    <option value="Asia/Tokyo">Asia/Tokyo</option>
                    <option value="Asia/Shanghai">Asia/Shanghai</option>
                    <option value="Australia/Sydney">Australia/Sydney</option>
                  </select>
                  <p className="text-xs text-tide-text-muted mt-1">
                    Used for displaying times and scheduling updates
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-tide-text mb-2">
                    Custom Timezone (IANA format)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g., America/Phoenix"
                    value={String(settings.timezone || '')}
                    onChange={(e) => updateSetting('timezone', e.target.value)}
                    className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                  />
                  <p className="text-xs text-tide-text-muted mt-1">
                    Override with any IANA timezone identifier
                  </p>
                </div>
              </div>
            </div>
          </div>
        </>
        )}
      </div>

      {/* Enable Local Authentication Modal */}
      {enableLocalAuthModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-tide-surface rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-teal-500/10 rounded-lg flex items-center justify-center">
                  <User className="w-5 h-5 text-teal-500" />
                </div>
                <h2 className="text-xl font-semibold text-tide-text">Enable Local Authentication</h2>
              </div>
              <button
                onClick={() => setEnableLocalAuthModalOpen(false)}
                className="text-tide-text-muted hover:text-tide-text transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <p className="text-tide-text">
                Enabling local authentication will allow you to secure TideWatch with username and password login.
              </p>

              <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4">
                <div className="flex gap-3">
                  <Info className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-2 text-sm">
                    <p className="font-medium text-amber-500">What happens next:</p>
                    <ul className="list-disc list-inside text-tide-text space-y-1">
                      <li>Authentication mode will be set to "local"</li>
                      <li>You'll be redirected to create an admin account</li>
                      <li>All API endpoints will require authentication</li>
                      <li>You can disable authentication anytime from settings</li>
                    </ul>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setEnableLocalAuthModalOpen(false)}
                className="flex-1 px-4 py-2 bg-tide-bg hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  try {
                    await api.settings.update('auth_mode', 'local');
                    toast.success('Enabled local authentication. Redirecting to setup...');
                    setTimeout(() => window.location.href = '/setup', 1000);
                  } catch {
                    toast.error('Failed to enable authentication');
                  }
                }}
                className="flex-1 px-4 py-2 bg-teal-500 hover:bg-teal-600 text-white rounded-lg transition-colors font-medium"
              >
                Enable & Setup
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Enable OIDC Authentication Modal */}
      {enableOidcAuthModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-tide-surface rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-teal-500/10 rounded-lg flex items-center justify-center">
                  <Shield className="w-5 h-5 text-teal-500" />
                </div>
                <h2 className="text-xl font-semibold text-tide-text">Enable OIDC/SSO Authentication</h2>
              </div>
              <button
                onClick={() => setEnableOidcAuthModalOpen(false)}
                className="text-tide-text-muted hover:text-tide-text transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <p className="text-tide-text">
                Enabling OIDC/SSO authentication will allow users to log in using Single Sign-On with OAuth2/OpenID Connect providers like Authentik, Keycloak, or Okta.
              </p>

              <div className="bg-teal-500/10 border border-teal-500/30 rounded-lg p-4">
                <div className="flex gap-3">
                  <Info className="w-5 h-5 text-teal-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-2 text-sm">
                    <p className="font-medium text-teal-500">What happens next:</p>
                    <ul className="list-disc list-inside text-tide-text space-y-1">
                      <li>Authentication mode will be set to "oidc"</li>
                      <li>OIDC configuration section will appear below</li>
                      <li>Configure your OIDC provider settings</li>
                      <li>Test the connection before using</li>
                      <li>All API endpoints will require SSO authentication</li>
                    </ul>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setEnableOidcAuthModalOpen(false)}
                className="flex-1 px-4 py-2 bg-tide-bg hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  try {
                    await api.settings.update('auth_mode', 'oidc');
                    toast.success('Enabled OIDC authentication. Refreshing...');
                    setTimeout(() => window.location.reload(), 1000);
                  } catch {
                    toast.error('Failed to enable OIDC');
                  }
                }}
                className="flex-1 px-4 py-2 bg-teal-500 hover:bg-teal-600 text-white rounded-lg transition-colors font-medium"
              >
                Enable OIDC
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Profile Modal */}
      {editProfileModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-tide-surface rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-tide-text">Edit Profile</h2>
              <button
                onClick={() => setEditProfileModalOpen(false)}
                className="text-tide-text-muted hover:text-tide-text transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              {/* Username (read-only) */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  Username
                </label>
                <input
                  type="text"
                  value={user?.username || ''}
                  disabled
                  className="w-full px-4 py-2 bg-tide-bg border border-tide-border rounded-lg text-tide-text-muted cursor-not-allowed"
                />
              </div>

              {/* Email */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  Email
                </label>
                <input
                  type="email"
                  value={profileEmail}
                  onChange={(e) => setProfileEmail(e.target.value)}
                  className="w-full px-4 py-2 bg-tide-bg border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
                  placeholder="your@email.com"
                />
              </div>

              {/* Full Name */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  Full Name
                </label>
                <input
                  type="text"
                  value={profileFullName}
                  onChange={(e) => setProfileFullName(e.target.value)}
                  className="w-full px-4 py-2 bg-tide-bg border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
                  placeholder="John Doe"
                />
              </div>

              {/* Auth Method Badge */}
              <div className="flex items-center gap-2 text-sm text-tide-text-muted">
                <Lock className="w-4 h-4" />
                <span>Authentication: {user?.auth_method === 'oidc' ? `SSO (${user.oidc_provider})` : 'Local'}</span>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setEditProfileModalOpen(false)}
                className="flex-1 px-4 py-2 bg-tide-bg hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  try {
                    setSavingProfile(true);
                    await updateProfile(profileEmail, profileFullName);
                    toast.success('Profile updated successfully');
                    setEditProfileModalOpen(false);
                  } catch {
                    toast.error('Failed to update profile');
                  } finally {
                    setSavingProfile(false);
                  }
                }}
                disabled={savingProfile}
                className="flex-1 px-4 py-2 bg-teal-500 hover:bg-teal-600 disabled:bg-teal-500/50 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
              >
                {savingProfile ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Change Password Modal */}
      {changePasswordModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-tide-surface rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-tide-text">Change Password</h2>
              <button
                onClick={() => {
                  setChangePasswordModalOpen(false);
                  setCurrentPassword('');
                  setNewPassword('');
                  setConfirmPassword('');
                  setShowCurrentPassword(false);
                  setShowNewPassword(false);
                  setShowConfirmPassword(false);
                }}
                className="text-tide-text-muted hover:text-tide-text transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              {/* Current Password */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  Current Password
                </label>
                <div className="relative">
                  <input
                    type={showCurrentPassword ? 'text' : 'password'}
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    className="w-full px-4 py-2 pr-10 bg-tide-bg border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
                    placeholder="Enter current password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-tide-text-muted hover:text-tide-text"
                  >
                    {showCurrentPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* New Password */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  New Password
                </label>
                <div className="relative">
                  <input
                    type={showNewPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full px-4 py-2 pr-10 bg-tide-bg border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
                    placeholder="Enter new password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPassword(!showNewPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-tide-text-muted hover:text-tide-text"
                  >
                    {showNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Confirm Password */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  Confirm Password
                </label>
                <div className="relative">
                  <input
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="w-full px-4 py-2 pr-10 bg-tide-bg border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
                    placeholder="Confirm new password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-tide-text-muted hover:text-tide-text"
                  >
                    {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Password validation */}
              {newPassword && (
                <div className="text-xs space-y-1">
                  <div className={`flex items-center gap-2 ${newPassword.length >= 8 ? 'text-teal-500' : 'text-tide-text-muted'}`}>
                    {newPassword.length >= 8 ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
                    <span>At least 8 characters</span>
                  </div>
                  <div className={`flex items-center gap-2 ${/[A-Z]/.test(newPassword) ? 'text-teal-500' : 'text-tide-text-muted'}`}>
                    {/[A-Z]/.test(newPassword) ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
                    <span>One uppercase letter</span>
                  </div>
                  <div className={`flex items-center gap-2 ${/[a-z]/.test(newPassword) ? 'text-teal-500' : 'text-tide-text-muted'}`}>
                    {/[a-z]/.test(newPassword) ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
                    <span>One lowercase letter</span>
                  </div>
                  <div className={`flex items-center gap-2 ${/[0-9]/.test(newPassword) ? 'text-teal-500' : 'text-tide-text-muted'}`}>
                    {/[0-9]/.test(newPassword) ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
                    <span>One number</span>
                  </div>
                  <div className={`flex items-center gap-2 ${/[!@#$%^&*(),.?":{}|<>]/.test(newPassword) ? 'text-teal-500' : 'text-tide-text-muted'}`}>
                    {/[!@#$%^&*(),.?":{}|<>]/.test(newPassword) ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
                    <span>One special character</span>
                  </div>
                  {confirmPassword && (
                    <div className={`flex items-center gap-2 ${newPassword === confirmPassword ? 'text-teal-500' : 'text-red-500'}`}>
                      {newPassword === confirmPassword ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
                      <span>Passwords match</span>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => {
                  setChangePasswordModalOpen(false);
                  setCurrentPassword('');
                  setNewPassword('');
                  setConfirmPassword('');
                  setShowCurrentPassword(false);
                  setShowNewPassword(false);
                  setShowConfirmPassword(false);
                }}
                className="flex-1 px-4 py-2 bg-tide-bg hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  if (newPassword !== confirmPassword) {
                    toast.error('Passwords do not match');
                    return;
                  }
                  try {
                    setChangingPassword(true);
                    await changePassword(currentPassword, newPassword);
                    toast.success('Password changed successfully');
                    setChangePasswordModalOpen(false);
                    setCurrentPassword('');
                    setNewPassword('');
                    setConfirmPassword('');
                    setShowCurrentPassword(false);
                    setShowNewPassword(false);
                    setShowConfirmPassword(false);
                  } catch {
                    toast.error('Failed to change password');
                  } finally {
                    setChangingPassword(false);
                  }
                }}
                disabled={changingPassword || !currentPassword || !newPassword || newPassword !== confirmPassword}
                className="flex-1 px-4 py-2 bg-teal-500 hover:bg-teal-600 disabled:bg-teal-500/50 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
              >
                {changingPassword ? 'Changing...' : 'Change Password'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* OIDC Configuration Modal */}
      {oidcConfigModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-tide-surface rounded-lg shadow-xl max-w-2xl w-full p-6">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <Shield className="w-6 h-6 text-primary" />
                <h2 className="text-xl font-semibold text-tide-text">OIDC/SSO Configuration</h2>
              </div>
              <button
                onClick={() => setOidcConfigModalOpen(false)}
                className="text-tide-text-muted hover:text-tide-text transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              {/* Enable OIDC Toggle */}
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-sm font-medium text-tide-text mb-1">
                    Enable OIDC/SSO
                  </label>
                  <p className="text-sm text-tide-text-muted">
                    Allow users to log in with Single Sign-On
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setOidcConfig({ ...oidcConfig, enabled: !oidcConfig.enabled })}
                  disabled={savingOidc}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                    oidcConfig.enabled ? 'bg-teal-500' : 'bg-red-500'
                  }`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    oidcConfig.enabled ? 'translate-x-6' : 'translate-x-1'
                  }`}></span>
                </button>
              </div>

              {/* OIDC Fields (shown when enabled) */}
              {oidcConfig.enabled && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-tide-text mb-1">
                      Issuer URL
                    </label>
                    <input
                      type="url"
                      value={oidcConfig.issuer_url}
                      onChange={(e) => setOidcConfig({ ...oidcConfig, issuer_url: e.target.value })}
                      disabled={savingOidc}
                      placeholder="https://auth.example.com"
                      className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-tide-text mb-1">
                      Client ID
                    </label>
                    <input
                      type="text"
                      value={oidcConfig.client_id}
                      onChange={(e) => setOidcConfig({ ...oidcConfig, client_id: e.target.value })}
                      disabled={savingOidc}
                      className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-tide-text mb-1">
                      Client Secret
                    </label>
                    <div className="relative">
                      <input
                        type={showOidcSecret ? 'text' : 'password'}
                        value={oidcConfig.client_secret}
                        onChange={(e) => setOidcConfig({ ...oidcConfig, client_secret: e.target.value })}
                        disabled={savingOidc}
                        className="w-full px-3 py-2 pr-10 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                      />
                      <button
                        type="button"
                        onClick={() => setShowOidcSecret(!showOidcSecret)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-tide-text-muted hover:text-tide-text"
                      >
                        {showOidcSecret ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-tide-text mb-1">
                      Provider Name
                    </label>
                    <input
                      type="text"
                      value={oidcConfig.provider_name}
                      onChange={(e) => setOidcConfig({ ...oidcConfig, provider_name: e.target.value })}
                      disabled={savingOidc}
                      placeholder="Authentik"
                      className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-tide-text mb-1">
                      Scopes
                    </label>
                    <input
                      type="text"
                      value={oidcConfig.scopes}
                      onChange={(e) => setOidcConfig({ ...oidcConfig, scopes: e.target.value })}
                      disabled={savingOidc}
                      className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-tide-text mb-1">
                      Redirect URI (read-only)
                    </label>
                    <input
                      type="text"
                      value={oidcConfig.redirect_uri || `${window.location.origin}/api/v1/auth/oidc/callback`}
                      disabled
                      className="w-full px-3 py-2 bg-tide-bg border border-tide-border rounded-lg text-tide-text-muted cursor-not-allowed"
                    />
                  </div>
                </>
              )}
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setOidcConfigModalOpen(false)}
                className="flex-1 px-4 py-2 bg-tide-bg hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg transition-colors"
              >
                Cancel
              </button>
              {oidcConfig.enabled && (
                <>
                  <button
                    onClick={handleTestOidcConnection}
                    disabled={testingOidc || savingOidc}
                    className="px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text border border-tide-border rounded-lg font-medium flex items-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {testingOidc ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        Testing...
                      </>
                    ) : (
                      <>
                        <CircleCheck className="w-4 h-4" />
                        Test Connection
                      </>
                    )}
                  </button>
                  <button
                    onClick={handleSaveOidcConfig}
                    disabled={savingOidc || testingOidc}
                    className="px-4 py-2 bg-teal-500 hover:bg-teal-600 disabled:bg-teal-500/50 disabled:cursor-not-allowed text-white rounded-lg font-medium flex items-center gap-2 transition-colors"
                  >
                    {savingOidc ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        Saving...
                      </>
                    ) : (
                      <>
                        <Check className="w-4 h-4" />
                        Save Configuration
                      </>
                    )}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
