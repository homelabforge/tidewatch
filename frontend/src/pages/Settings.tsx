import { useState, useEffect, useRef } from 'react';
import { RotateCcw, Server, Plug, Bell, Database, RefreshCw, Settings as SettingsIcon, CircleCheck, HardDrive, Shield, Upload, Plus, Download, Trash2, Info, Cpu, X, ChevronDown, ChevronRight, Clock, Star, FolderOpen, Scan, FileText, Sun, Moon, Lock, User, Eye, EyeOff, Check } from 'lucide-react';
import { toast } from 'sonner';
import { formatDistanceToNow } from 'date-fns';
import { api } from '../services/api';
import type { BackupListResponse, BackupFile, SettingCategory } from '../types';
import type { OIDCConfig } from '../types/auth';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../hooks/useAuth';
import { HelpTooltip } from '../components/HelpTooltip';
import {
  NotificationSubTabs,
  type NotificationSubTab,
  EventNotificationsCard,
  NtfyConfig,
  GotifyConfig,
  PushoverConfig,
  SlackConfig,
  DiscordConfig,
  TelegramConfig,
  EmailConfig,
} from '../components/notifications';

type TabType = 'system' | 'updates' | 'docker' | 'integrations' | 'notifications' | 'backup' | 'security';

export default function Settings() {
  const [activeTab, setActiveTab] = useState<TabType>('system');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Theme hook
  const { theme, setTheme } = useTheme();

  // Auth hook
  const { user, authMode, updateProfile, changePassword } = useAuth();

  // Settings state
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [categories, setCategories] = useState<SettingCategory[]>([]);
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());

  // Test connection loading states
  const [testingDockerHub, setTestingDockerHub] = useState(false);
  const [testingGHCR, setTestingGHCR] = useState(false);
  const [testingVulnForge, setTestingVulnForge] = useState(false);
  const [testingNtfy, setTestingNtfy] = useState(false);
  const [testingGotify, setTestingGotify] = useState(false);
  const [testingPushover, setTestingPushover] = useState(false);
  const [testingSlack, setTestingSlack] = useState(false);
  const [testingDiscord, setTestingDiscord] = useState(false);
  const [testingTelegram, setTestingTelegram] = useState(false);
  const [testingEmail, setTestingEmail] = useState(false);

  // Notification sub-tab state
  const [notificationSubTab, setNotificationSubTab] = useState<NotificationSubTab>('ntfy');

  // Backup state
  const [backups, setBackups] = useState<BackupListResponse | null>(null);
  const [loadingBackups, setLoadingBackups] = useState(false);
  const [creatingBackup, setCreatingBackup] = useState(false);
  const [uploadingBackup, setUploadingBackup] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Modal state for backup operations
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [restoreModalOpen, setRestoreModalOpen] = useState(false);
  const [selectedBackup, setSelectedBackup] = useState<BackupFile | null>(null);

  // Scheduler status state
  const [schedulerStatus, setSchedulerStatus] = useState<Record<string, unknown> | null>(null);
  const [loadingScheduler, setLoadingScheduler] = useState(false);

  // My Projects scanning state
  const [scanningProjects, setScanningProjects] = useState(false);

  // Authentication tab state
  const [profileEmail, setProfileEmail] = useState('');
  const [profileFullName, setProfileFullName] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [changingPassword, setChangingPassword] = useState(false);
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
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

  // Modal states for auth actions
  const [editProfileModalOpen, setEditProfileModalOpen] = useState(false);
  const [changePasswordModalOpen, setChangePasswordModalOpen] = useState(false);
  const [enableLocalAuthModalOpen, setEnableLocalAuthModalOpen] = useState(false);
  const [enableOidcAuthModalOpen, setEnableOidcAuthModalOpen] = useState(false);
  const [oidcConfigModalOpen, setOidcConfigModalOpen] = useState(false);

  // Debounce timer for text inputs
  const debounceTimers = useRef<Record<string, number>>({});

  // Initialize profile form when modal opens
  useEffect(() => {
    if (editProfileModalOpen && user) {
      setProfileEmail(user.email || '');
      setProfileFullName(user.full_name || '');
    }
  }, [editProfileModalOpen, user]);

  // Format bytes to human-readable size
  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
  };

  const tabs = [
    { id: 'system', label: 'System', icon: Cpu },
    { id: 'updates', label: 'Updates', icon: RotateCcw },
    { id: 'docker', label: 'Docker', icon: Server },
    { id: 'integrations', label: 'Integrations', icon: Plug },
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'backup', label: 'Backup & Maintenance', icon: Database },
  ];

  // Load settings on mount
  useEffect(() => {
    loadSettings();
  }, []);

  // Load backups when backup tab is active
  useEffect(() => {
    if (activeTab === 'backup') {
      loadBackups();
    }
  }, [activeTab]);

  // Load scheduler status when updates tab is active
  useEffect(() => {
    if (activeTab === 'updates') {
      loadSchedulerStatus();
    }
  }, [activeTab]);

  const loadSettings = async () => {
    try {
      setLoading(true);
      // Load flat settings list (card-based UI)
      const settingsData = await api.settings.getAll();
      setCategories([]); // Disable categories to show card-based UI
      const settingsMap: Record<string, unknown> = {};
      settingsData.forEach((setting) => {
        // Convert string "true"/"false" to boolean for toggles
        let value = setting.value;
        if (value === 'true') value = true;
        else if (value === 'false') value = false;
        else if (!isNaN(Number(value)) && value !== '') {
          // Convert numeric strings to numbers
          value = Number(value);
        }
        settingsMap[setting.key] = value;
      });
      setSettings(settingsMap);
    } catch (error) {
      console.error('Failed to load settings:', error);
      toast.error('Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const icons: Record<string, any> = {
      system: Cpu,
      docker: Server,
      updates: RotateCcw,
      cleanup: HardDrive,
      registry: Server,
      integrations: Plug,
      notifications: Bell,
      backup: Database,
    };
    return icons[category] || SettingsIcon;
  };

  const getCategoryTitle = (category: string) => {
    const titles: Record<string, string> = {
      system: 'System Configuration',
      docker: 'Docker Settings',
      updates: 'Update Management',
      cleanup: 'Cleanup & Maintenance',
      registry: 'Registry Authentication',
      integrations: 'Integrations',
      notifications: 'Notifications',
      backup: 'Backup Settings',
    };
    return titles[category] || category.charAt(0).toUpperCase() + category.slice(1);
  };

  const updateSetting = async (key: string, value: unknown, updateState: boolean = true) => {
    try {
      setSaving(true);
      // Convert all values to strings for backend
      const apiValue = String(value);
      await api.settings.update(key, apiValue);
      // Update state if requested (for toggles, selects, numbers)
      if (updateState) {
        setSettings((prev) => ({ ...prev, [key]: value }));
      }
      toast.success('Setting updated successfully');
    } catch (error) {
      console.error(`Failed to update ${key}:`, error);
      toast.error('Failed to update setting');
      // Reload settings on error to restore correct state
      await loadSettings();
    } finally {
      setSaving(false);
    }
  };

  // Handle text input changes with debouncing
  const handleTextChange = (key: string, value: string) => {
    // Update local state immediately for responsive UI
    setSettings((prev) => ({ ...prev, [key]: value }));

    // Clear existing timer for this key
    if (debounceTimers.current[key]) {
      clearTimeout(debounceTimers.current[key]);
    }

    // Set new timer to save after user stops typing (1 second delay)
    debounceTimers.current[key] = setTimeout(async () => {
      // Pass false to avoid duplicate state update
      await updateSetting(key, value, false);

      // Auto-reload scheduler when check schedule changes
      if (key === 'check_schedule') {
        try {
          await api.updates.reloadScheduler();
          toast.success('Scheduler reloaded with new schedule');
          await loadSchedulerStatus();
        } catch (error) {
          console.error('Failed to reload scheduler:', error);
          toast.error('Failed to reload scheduler');
        }
      }
    }, 1000);
  };

  const loadBackups = async () => {
    try {
      setLoadingBackups(true);
      const backupData = await api.backup.list();
      setBackups(backupData);
    } catch (error) {
      console.error('Failed to load backups:', error);
      toast.error('Failed to load backups');
    } finally {
      setLoadingBackups(false);
    }
  };

  const loadSchedulerStatus = async () => {
    try {
      setLoadingScheduler(true);
      const status = await api.updates.getSchedulerStatus();
      setSchedulerStatus(status.scheduler);
    } catch (error) {
      console.error('Failed to load scheduler status:', error);
      // Don't show error toast - just fail silently for status display
    } finally {
      setLoadingScheduler(false);
    }
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

  // Authentication handlers
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

  // Load user profile and OIDC config when system tab is active
  useEffect(() => {
    if (activeTab === 'system' && user) {
      setProfileEmail(user.email);
      setProfileFullName(user.full_name || '');
    }
  }, [activeTab, user]);

  useEffect(() => {
    if (activeTab === 'system' && authMode !== 'none') {
      // Load OIDC config
      api.auth.oidc.getConfig().then((config) => {
        setOidcConfig(config as OIDCConfig);
      }).catch((error) => {
        console.error('Failed to load OIDC config:', error);
      });
    }
  }, [activeTab, authMode]);

  const handleCreateBackup = async () => {
    try {
      setCreatingBackup(true);
      const result = await api.backup.create();
      toast.success(result.message);
      await loadBackups();
    } catch (error) {
      console.error('Failed to create backup:', error);
      toast.error('Failed to create backup');
    } finally {
      setCreatingBackup(false);
    }
  };

  const handleUploadBackup = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      setUploadingBackup(true);
      await api.backup.upload(file);
      toast.success('Backup uploaded successfully');
      await loadBackups();
    } catch (error) {
      console.error('Failed to upload backup:', error);
      toast.error('Failed to upload backup');
    } finally {
      setUploadingBackup(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleDownloadBackup = (filename: string) => {
    const url = api.backup.download(filename);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    toast.success('Backup download started');
  };

  const openRestoreModal = (backup: BackupFile) => {
    setSelectedBackup(backup);
    setRestoreModalOpen(true);
  };

  const openDeleteModal = (backup: BackupFile) => {
    if (backup.is_safety) {
      toast.error('Safety backups cannot be deleted');
      return;
    }
    setSelectedBackup(backup);
    setDeleteModalOpen(true);
  };

  const confirmRestore = async () => {
    if (!selectedBackup) return;

    try {
      const result = await api.backup.restore(selectedBackup.filename);
      toast.success(result.message);
      await loadSettings();
      await loadBackups();
      setRestoreModalOpen(false);
      setSelectedBackup(null);
    } catch (error) {
      console.error('Failed to restore backup:', error);
      toast.error('Failed to restore backup');
    }
  };

  const confirmDelete = async () => {
    if (!selectedBackup) return;

    try {
      const result = await api.backup.delete(selectedBackup.filename);
      toast.success(result.message);
      await loadBackups();
      setDeleteModalOpen(false);
      setSelectedBackup(null);
    } catch (error) {
      console.error('Failed to delete backup:', error);
      toast.error('Failed to delete backup');
    }
  };

  const handleTestConnection = async (type: 'docker' | 'dockerhub' | 'ghcr' | 'vulnforge' | 'ntfy' | 'gotify' | 'pushover' | 'slack' | 'discord' | 'telegram' | 'email') => {
    const setTestingState = {
      docker: setTestingDocker,
      dockerhub: setTestingDockerHub,
      ghcr: setTestingGHCR,
      vulnforge: setTestingVulnForge,
      ntfy: setTestingNtfy,
      gotify: setTestingGotify,
      pushover: setTestingPushover,
      slack: setTestingSlack,
      discord: setTestingDiscord,
      telegram: setTestingTelegram,
      email: setTestingEmail,
    }[type];

    const testFunction = {
      docker: api.settings.testDocker,
      dockerhub: api.settings.testDockerHub,
      ghcr: api.settings.testGHCR,
      vulnforge: api.settings.testVulnForge,
      ntfy: api.settings.testNtfy,
      gotify: api.settings.testGotify,
      pushover: api.settings.testPushover,
      slack: api.settings.testSlack,
      discord: api.settings.testDiscord,
      telegram: api.settings.testTelegram,
      email: api.settings.testEmail,
    }[type];

    try {
      setTestingState(true);
      const result = await testFunction();

      if (result.success) {
        toast.success(result.message, {
          description: result.details ? Object.entries(result.details).map(([k, v]) => `${k}: ${v}`).join(', ') : undefined,
        });
      } else {
        toast.error(result.message, {
          description: result.details ? Object.entries(result.details).map(([k, v]) => `${k}: ${v}`).join(', ') : undefined,
        });
      }
    } catch (error) {
      console.error(`Failed to test ${type} connection:`, error);
      toast.error(`Failed to test ${type} connection`);
    } finally {
      setTestingState(false);
    }
  };

  const handleScanMyProjects = async () => {
    try {
      setScanningProjects(true);
      const response = await api.containers.scanMyProjects();

      if (response.success) {
        const { added, updated, skipped, errors } = response.results;
        toast.success('Project scan completed', {
          description: `Added: ${added}, Updated: ${updated}, Skipped: ${skipped}${errors ? `, Errors: ${errors.length}` : ''}`,
        });
      } else {
        toast.error('Failed to scan projects');
      }
    } catch (error) {
      console.error('Failed to scan my projects:', error);
      toast.error('Failed to scan my projects');
    } finally {
      setScanningProjects(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-tide-bg flex items-center justify-center">
        <RefreshCw className="animate-spin text-primary" size={48} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-tide-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-tide-text mb-2">Settings</h1>
          <p className="text-tide-text-muted">Configure TideWatch to match your needs</p>
        </div>

        {/* Tabs */}
        <div className="border-b border-tide-border mb-6">
          <nav className="-mb-px flex space-x-8">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as TabType)}
                  className={`flex items-center gap-2 px-1 py-4 border-b-2 font-medium text-sm transition-colors ${
                    isActive
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text hover:border-tide-border'
                  }`}
                >
                  <Icon size={18} />
                  {tab.label}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Content */}
        <div className="bg-tide-surface-light rounded-lg p-6 mt-6">
          {/* Category View Toggle (if categories available) */}
          {categories.length > 0 && (
            <div className="mb-6 pb-6 border-b border-tide-border">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-tide-text mb-1">Settings Organization</h3>
                  <p className="text-xs text-tide-text-muted">
                    Settings are grouped by category. Click to expand/collapse sections.
                  </p>
                </div>
                <div className="text-xs text-teal-400 bg-teal-500/10 px-3 py-1 rounded-full border border-teal-500/30">
                  EXPERIMENTAL
                </div>
              </div>
            </div>
          )}

          {/* System Tab */}
          {activeTab === 'system' && (
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
                                          value={settings[setting.key] || ''}
                                          onChange={(e) => {
                                            const value = typeof settings[setting.key] === 'number'
                                              ? parseInt(e.target.value) || 0
                                              : e.target.value;
                                            handleTextChange(setting.key, String(value));
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
                                // Wait a moment then reload to reset auth state
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
                          value={settings.timezone || 'UTC'}
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
                          value={settings.timezone || ''}
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
          )}

          {/* Updates Tab */}
          {activeTab === 'updates' && (
            <div className="space-y-6">
              {/* Scheduler Status Card */}
              {!loadingScheduler && schedulerStatus && (
                <div className="bg-tide-surface/50 border border-tide-border rounded-lg p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <RefreshCw className={`w-5 h-5 ${schedulerStatus.running ? 'text-green-500' : 'text-tide-text-muted'}`} />
                      <div>
                        <h3 className="text-sm font-semibold text-tide-text">Update Scheduler</h3>
                        <p className="text-xs text-tide-text-muted">Background update checking service</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <p className="text-xs text-tide-text-muted">Status</p>
                        <p className="text-sm font-medium text-tide-text">
                          {schedulerStatus.running ? (
                            <span className="text-green-500">● Running</span>
                          ) : (
                            <span className="text-tide-text-muted">⏸ Paused</span>
                          )}
                        </p>
                      </div>
                      {schedulerStatus.next_run && (
                        <div className="text-right">
                          <p className="text-xs text-tide-text-muted">Next Run</p>
                          <p className="text-sm font-medium text-tide-text">
                            {formatDistanceToNow(new Date(schedulerStatus.next_run), { addSuffix: true })}
                          </p>
                        </div>
                      )}
                      {schedulerStatus.last_check && (
                        <div className="text-right">
                          <p className="text-xs text-tide-text-muted">Last Check</p>
                          <p className="text-sm font-medium text-tide-text">
                            {formatDistanceToNow(new Date(schedulerStatus.last_check), { addSuffix: true })}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Category-based view if categories available */}
              {categories.length > 0 && (
                <div className="space-y-4">
                  {categories
                    .filter((cat) => cat.category === 'updates' || cat.category === 'cleanup')
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
                                          value={settings[setting.key] || ''}
                                          onChange={(e) => {
                                            const value = typeof settings[setting.key] === 'number'
                                              ? parseInt(e.target.value) || 0
                                              : e.target.value;
                                            handleTextChange(setting.key, String(value));
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

              {/* Settings Cards */}
              {categories.length === 0 && (
                <div className="columns-1 xl:columns-2 gap-6" style={{ columnGap: '1.5rem' }}>
                  {/* Update Checks Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <RotateCcw className="w-6 h-6 text-teal-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">Update Checks</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Configure how often to check for updates</p>
                        </div>
                      </div>
                      <HelpTooltip content="Controls automatic update checking. The schedule uses cron syntax (e.g., '0 */6 * * *' checks every 6 hours). Disable to manually trigger checks only." />
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Check Enabled
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Automatically check for container image updates
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('check_enabled', !settings.check_enabled)}
                          disabled={saving}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                            settings.check_enabled ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.check_enabled ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Check Schedule
                        </label>
                        <input
                          type="text"
                          value={settings.check_schedule || ''}
                          onChange={(e) => handleTextChange('check_schedule', e.target.value)}
                          disabled={saving}
                          className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                          placeholder="0 */6 * * *"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Cron expression for update checks
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Automatic Updates Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <CircleCheck className="w-6 h-6 text-green-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">Automatic Updates</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Configure automatic update behavior</p>
                        </div>
                      </div>
                      <HelpTooltip content="When enabled, approved updates are applied automatically. Max concurrent limits how many containers update simultaneously to reduce system load and allow rollback if issues occur." />
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Auto Update Enabled
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Automatically apply approved updates
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('auto_update_enabled', !settings.auto_update_enabled)}
                          disabled={saving}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                            settings.auto_update_enabled ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.auto_update_enabled ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>

                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <label className="block text-sm font-medium text-tide-text">
                            Max Concurrent Updates
                          </label>
                          <span className="text-sm text-tide-text-muted">{settings.auto_update_max_concurrent || 3}</span>
                        </div>
                        <input
                          type="range"
                          min="1"
                          max="10"
                          value={settings.auto_update_max_concurrent || 3}
                          onChange={(e) => updateSetting('auto_update_max_concurrent', parseInt(e.target.value))}
                          disabled={saving}
                          className="w-full h-2 bg-tide-bg rounded-lg appearance-none cursor-pointer accent-teal-500"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Maximum number of updates to auto-apply per run (rate limiting)
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Retry Configuration Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <RotateCcw className="w-6 h-6 text-orange-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">Retry Configuration</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Configure automatic retry behavior for failed updates</p>
                        </div>
                      </div>
                      <HelpTooltip content="Failed updates retry automatically with exponential backoff. The multiplier controls delay increase between attempts (e.g., 3x: 5min → 15min → 45min). Set max attempts to 0 to disable retries." />
                    </div>

                    <div className="space-y-4">
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <label className="block text-sm font-medium text-tide-text">
                            Max Retry Attempts
                          </label>
                          <span className="text-sm text-tide-text-muted">{settings.update_retry_max_attempts || 4}</span>
                        </div>
                        <input
                          type="range"
                          min="0"
                          max="10"
                          value={settings.update_retry_max_attempts || 4}
                          onChange={(e) => updateSetting('update_retry_max_attempts', parseInt(e.target.value))}
                          disabled={saving}
                          className="w-full h-2 bg-tide-bg rounded-lg appearance-none cursor-pointer accent-teal-500"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Maximum number of automatic retry attempts (0-10)
                        </p>
                      </div>

                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <label className="block text-sm font-medium text-tide-text">
                            Backoff Multiplier
                          </label>
                          <span className="text-sm text-tide-text-muted">{settings.update_retry_backoff_multiplier || 3}</span>
                        </div>
                        <input
                          type="range"
                          min="1"
                          max="10"
                          step="0.5"
                          value={settings.update_retry_backoff_multiplier || 3}
                          onChange={(e) => updateSetting('update_retry_backoff_multiplier', parseFloat(e.target.value))}
                          disabled={saving}
                          className="w-full h-2 bg-tide-bg rounded-lg appearance-none cursor-pointer accent-teal-500"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Exponential backoff multiplier for retry delays (1.0-5min, 15min, 1hr, 4hr)
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Default Update Window Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <Clock className="w-6 h-6 text-teal-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">Default Update Window</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Configure default time restrictions for updates</p>
                        </div>
                      </div>
                      <HelpTooltip content="Restrict updates to specific times. Format: 'HH:MM-HH:MM' for daily windows or 'Day-Day:HH:MM-HH:MM' for specific days. Strict mode blocks all updates outside the window; Advisory mode only warns." />
                    </div>

                    <div className="space-y-4">
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Default Window
                        </label>
                        <input
                          type="text"
                          value={settings.default_update_window || ''}
                          onChange={(e) => handleTextChange('default_update_window', e.target.value)}
                          disabled={saving}
                          className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-purple-500 focus:outline-none"
                          placeholder='Time range (e.g., "02:00-06:00")'
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Time range when updates are allowed (e.g., &quot;02:00-06:00&quot; or &quot;Sat-Sun:00:00-23:59&quot;)
                        </p>
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Window Enforcement
                        </label>
                        <select
                          value={settings.update_window_enforcement || 'strict'}
                          onChange={(e) => updateSetting('update_window_enforcement', e.target.value)}
                          disabled={saving}
                          className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-purple-500 focus:outline-none"
                        >
                          <option value="strict">Strict (never update outside window)</option>
                          <option value="advisory">Advisory (warn but allow)</option>
                        </select>
                        <p className="text-xs text-tide-text-muted mt-1">
                          How strictly to enforce update windows
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Stale Container Detection Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <Database className="w-6 h-6 text-orange-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">Stale Container Detection</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Automatically detect inactive containers</p>
                        </div>
                      </div>
                      <HelpTooltip content="Identifies containers that have been removed from compose files but still exist. The threshold sets how long before marking as stale. Excludes dev containers to avoid flagging temporary development instances." />
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Enable Stale Detection
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Detect containers removed from compose files
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('stale_detection_enabled', !settings.stale_detection_enabled)}
                          disabled={saving}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                            settings.stale_detection_enabled ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.stale_detection_enabled ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>

                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <label className="block text-sm font-medium text-tide-text">
                            Stale Threshold (Days)
                          </label>
                          <span className="text-sm text-tide-text-muted">{settings.stale_detection_threshold_days || 7}</span>
                        </div>
                        <input
                          type="range"
                          min="1"
                          max="90"
                          value={settings.stale_detection_threshold_days || 7}
                          onChange={(e) => updateSetting('stale_detection_threshold_days', parseInt(e.target.value))}
                          disabled={saving}
                          className="w-full h-2 bg-tide-bg rounded-lg appearance-none cursor-pointer accent-teal-500"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Days before container is marked stale
                        </p>
                      </div>

                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Exclude Dev Containers
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Skip containers ending in -dev from stale detection
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('stale_detection_exclude_dev', !settings.stale_detection_exclude_dev)}
                          disabled={saving}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                            settings.stale_detection_exclude_dev ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.stale_detection_exclude_dev ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Cleanup Policy Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <HardDrive className="w-6 h-6 text-teal-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">Cleanup Policy</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Manage old container images</p>
                        </div>
                      </div>
                      <HelpTooltip content="Controls Docker resource cleanup. Dangling removes only untagged images; Moderate adds exited containers; Aggressive includes unused images older than threshold. Exclude patterns protect matching containers/images from cleanup." />
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Auto-Remove Old Images
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Remove old images after successful update
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('cleanup_old_images', !settings.cleanup_old_images)}
                          disabled={saving}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                            settings.cleanup_old_images ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.cleanup_old_images ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>

                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <label className="block text-sm font-medium text-tide-text">
                            Cleanup After Days
                          </label>
                          <span className="text-sm text-tide-text-muted">{settings.cleanup_after_days || 7}</span>
                        </div>
                        <input
                          type="range"
                          min="0"
                          max="90"
                          value={settings.cleanup_after_days || 7}
                          onChange={(e) => updateSetting('cleanup_after_days', parseInt(e.target.value))}
                          disabled={saving}
                          className="w-full h-2 bg-tide-bg rounded-lg appearance-none cursor-pointer accent-teal-500"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Days to keep old images before cleanup in aggressive mode
                        </p>
                      </div>

                      {/* Cleanup Mode */}
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Cleanup Mode
                        </label>
                        <select
                          value={settings.cleanup_mode || 'dangling'}
                          onChange={(e) => updateSetting('cleanup_mode', e.target.value)}
                          disabled={saving}
                          className="w-full px-3 py-2 bg-tide-bg border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="dangling">Dangling - Untagged images only</option>
                          <option value="moderate">Moderate - + Exited containers</option>
                          <option value="aggressive">Aggressive - + Old unused images</option>
                        </select>
                        <p className="text-xs text-tide-text-muted mt-1">
                          How aggressively to clean up Docker resources
                        </p>
                      </div>

                      {/* Cleanup Containers Toggle */}
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Cleanup Containers
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Also remove exited/dead containers during cleanup
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('cleanup_containers', settings.cleanup_containers === false ? true : !settings.cleanup_containers)}
                          disabled={saving}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                            settings.cleanup_containers !== false ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.cleanup_containers !== false ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>

                      {/* Cleanup Schedule */}
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Cleanup Schedule
                        </label>
                        <input
                          type="text"
                          value={settings.cleanup_schedule || '0 4 * * *'}
                          onChange={(e) => updateSetting('cleanup_schedule', e.target.value)}
                          disabled={saving}
                          placeholder="0 4 * * *"
                          className="w-full px-3 py-2 bg-tide-bg border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500 font-mono text-sm"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Cron schedule for automatic cleanup (default: 4 AM daily)
                        </p>
                      </div>

                      {/* Exclude Patterns */}
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Exclude Patterns
                        </label>
                        <input
                          type="text"
                          value={settings.cleanup_exclude_patterns || '-dev,rollback'}
                          onChange={(e) => updateSetting('cleanup_exclude_patterns', e.target.value)}
                          disabled={saving}
                          placeholder="-dev,rollback"
                          className="w-full px-3 py-2 bg-tide-bg border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Comma-separated patterns to exclude (e.g., -dev,rollback)
                        </p>
                      </div>

                      {/* Run Now Button */}
                      <div className="pt-2 border-t border-tide-border">
                        <button
                          type="button"
                          onClick={async () => {
                            try {
                              const response = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/v1/cleanup/run-now`, {
                                method: 'POST',
                              });
                              const result = await response.json();
                              if (result.success) {
                                toast.success(result.message || `Removed ${result.images_removed || 0} images and ${result.containers_removed || 0} containers, reclaimed ${result.space_reclaimed_formatted || '0 B'}`, {
                                  duration: 5000,
                                });
                              } else {
                                toast.error('Cleanup failed: ' + (result.message || 'Unknown error'));
                              }
                            } catch (err) {
                              toast.error('Failed to run cleanup: ' + (err instanceof Error ? err.message : 'Unknown error'));
                            }
                          }}
                          disabled={saving}
                          className="w-full px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg transition-colors flex items-center justify-center gap-2"
                        >
                          <HardDrive className="w-4 h-4" />
                          Run Cleanup Now
                        </button>
                        <p className="text-xs text-tide-text-muted mt-2 text-center">
                          Trigger immediate cleanup using current settings
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Docker Tab */}
          {activeTab === 'docker' && (
            <div className="space-y-6">
              {/* Category-based view if categories available */}
              {categories.length > 0 && (
                <div className="space-y-4">
                  {categories
                    .filter((cat) => cat.category === 'docker' || cat.category === 'registry')
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
                                        {setting.encrypted && <span className="text-xs text-tide-text-muted bg-tide-surface px-1.5 py-0.5 rounded ml-2">Encrypted</span>}
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
                                          type={setting.encrypted ? 'password' : typeof settings[setting.key] === 'number' ? 'number' : 'text'}
                                          value={settings[setting.key] || ''}
                                          onChange={(e) => {
                                            const value = typeof settings[setting.key] === 'number'
                                              ? parseInt(e.target.value) || 0
                                              : e.target.value;
                                            handleTextChange(setting.key, String(value));
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

              {/* Docker Settings Cards */}
              {categories.length === 0 && (
                <div className="columns-1 xl:columns-2 gap-6" style={{ columnGap: '1.5rem' }}>
                  {/* Registry Authentication Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <Cpu className="w-6 h-6 text-teal-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">Registry Authentication</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Configure registry credentials</p>
                        </div>
                      </div>
                      <HelpTooltip content="Registry credentials are optional but recommended to avoid rate limits. Docker Hub tokens can be created at hub.docker.com/settings/security. GitHub PATs need read:packages scope for GHCR access. Credentials are stored encrypted in the database." />
                    </div>

                    <div className="space-y-6">
                      {/* Docker Hub Section */}
                      <div>
                        <h3 className="text-sm font-semibold text-tide-text mb-3">Docker Hub</h3>
                        <div className="space-y-3">
                          <div>
                            <label className="block text-sm font-medium text-tide-text mb-2">
                              Username
                            </label>
                            <input
                              type="text"
                              value={settings.dockerhub_username || ''}
                              onChange={(e) => handleTextChange('dockerhub_username', e.target.value)}
                              disabled={saving}
                              className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                            />
                          </div>

                          <div className="flex items-center gap-2">
                            <div className="flex-1">
                              <label className="block text-sm font-medium text-tide-text mb-2 flex items-center gap-2">
                                Token
                                <span className="text-xs text-tide-text-muted bg-tide-surface px-1.5 py-0.5 rounded">Encrypted</span>
                              </label>
                              <input
                                type="password"
                                value={settings.dockerhub_token || ''}
                                onChange={(e) => handleTextChange('dockerhub_token', e.target.value)}
                                disabled={saving}
                                className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                              />
                            </div>
                            <button
                              type="button"
                              onClick={() => handleTestConnection('dockerhub')}
                              disabled={testingDockerHub || saving}
                              className="mt-7 px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50 border border-tide-border"
                            >
                              {testingDockerHub ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CircleCheck className="w-4 h-4" />}
                              {testingDockerHub ? 'Testing...' : 'Test Connection'}
                            </button>
                          </div>
                        </div>
                      </div>

                      {/* GitHub Container Registry Section */}
                      <div>
                        <h3 className="text-sm font-semibold text-tide-text mb-3">GitHub (GHCR)</h3>
                        <div className="space-y-3">
                          <div>
                            <label className="block text-sm font-medium text-tide-text mb-2">
                              Username
                            </label>
                            <input
                              type="text"
                              value={settings.ghcr_username || ''}
                              onChange={(e) => handleTextChange('ghcr_username', e.target.value)}
                              disabled={saving}
                              className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                            />
                          </div>

                          <div className="flex items-center gap-2">
                            <div className="flex-1">
                              <label className="block text-sm font-medium text-tide-text mb-2 flex items-center gap-2">
                                Token
                                <span className="text-xs text-tide-text-muted bg-tide-surface px-1.5 py-0.5 rounded">Encrypted</span>
                              </label>
                              <input
                                type="password"
                                value={settings.ghcr_token || ''}
                                onChange={(e) => handleTextChange('ghcr_token', e.target.value)}
                                disabled={saving}
                                className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                              />
                            </div>
                            <button
                              type="button"
                              onClick={() => handleTestConnection('ghcr')}
                              disabled={testingGHCR || saving}
                              className="mt-7 px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50 border border-tide-border"
                            >
                              {testingGHCR ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CircleCheck className="w-4 h-4" />}
                              {testingGHCR ? 'Testing...' : 'Test Connection'}
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Docker Configuration Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <Server className="w-6 h-6 text-teal-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">Docker Configuration</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Configure Docker daemon connection</p>
                        </div>
                      </div>
                      <HelpTooltip content="Docker socket enables TideWatch to monitor and update containers. Compose directory should contain all your docker-compose.yml files. The compose command template supports placeholders: {compose_file}, {env_file}, {service}." />
                    </div>

                    <div className="space-y-4">
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Compose Directory
                        </label>
                        <input
                          type="text"
                          value={settings.compose_directory || ''}
                          onChange={(e) => handleTextChange('compose_directory', e.target.value)}
                          disabled={saving}
                          placeholder="/compose"
                          className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Directory containing docker-compose files
                        </p>
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Docker Compose Command
                        </label>
                        <input
                          type="text"
                          value={settings.docker_compose_command || ''}
                          onChange={(e) => handleTextChange('docker_compose_command', e.target.value)}
                          disabled={saving}
                          placeholder='docker compose -p homelab -f /compose/base.yml -f /compose/backup.yml'
                          className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Docker compose command template. Use {'{compose_file}'}, {'{env_file}'}, {'{service}'} placeholders
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* My Projects Configuration Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <Star className="w-6 h-6 text-yellow-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">My Projects Configuration</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Manage dev containers and dependency tracking</p>
                        </div>
                      </div>
                      <HelpTooltip content="My Projects groups dev containers separately on the Dashboard. Auto-scan discovers containers from {projects_directory}/*/compose.yaml files. Dependencies tab scans package.json, pyproject.toml, etc. You can also manually mark any container as 'My Project' in its Settings tab." />
                    </div>

                    <div className="space-y-4">
                      {/* Enable My Projects Feature */}
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Enable My Projects
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Show My Project toggle and Dependencies tab for dev containers
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('my_projects_enabled', !settings.my_projects_enabled)}
                          disabled={saving}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                            settings.my_projects_enabled ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.my_projects_enabled ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>

                      {/* Projects Directory */}
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2 flex items-center gap-2">
                          <FolderOpen className="w-4 h-4" />
                          Projects Directory
                        </label>
                        <input
                          type="text"
                          value={settings.projects_directory || ''}
                          onChange={(e) => handleTextChange('projects_directory', e.target.value)}
                          disabled={saving || !settings.my_projects_enabled}
                          placeholder="/projects"
                          className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none disabled:opacity-50"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Directory containing project source code (mounted into Tidewatch)
                        </p>
                      </div>

                      {/* Auto-Scan Enable/Disable */}
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Auto-Scan Projects
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Automatically discover dev containers on startup
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('my_projects_auto_scan', !settings.my_projects_auto_scan)}
                          disabled={saving || !settings.my_projects_enabled}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none disabled:opacity-50 ${
                            settings.my_projects_auto_scan ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.my_projects_auto_scan ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>

                      {/* Docker Compose Command for My Projects */}
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          My Projects Docker Compose Command
                        </label>
                        <input
                          type="text"
                          value={settings.my_projects_compose_command || ''}
                          onChange={(e) => handleTextChange('my_projects_compose_command', e.target.value)}
                          disabled={saving || !settings.my_projects_enabled}
                          placeholder='docker compose'
                          className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none disabled:opacity-50"
                        />
                        <p className="text-xs text-tide-text-muted mt-1">
                          Simple Docker Compose command for dev containers (use {'{compose_file}'}, {'{service}'} placeholders)
                        </p>
                      </div>

                      {/* Manual Scan Button */}
                      <div className="pt-2">
                        <button
                          type="button"
                          onClick={handleScanMyProjects}
                          disabled={scanningProjects || !settings.my_projects_enabled}
                          className="w-full px-4 py-2 bg-teal-600 hover:bg-teal-700 text-tide-text rounded-lg font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {scanningProjects ? (
                            <>
                              <RefreshCw className="w-4 h-4 animate-spin" />
                              Scanning Projects...
                            </>
                          ) : (
                            <>
                              <Scan className="w-4 h-4" />
                              Scan Projects Now
                            </>
                          )}
                        </button>
                        <p className="text-xs text-tide-text-muted mt-2 text-center">
                          Manually scan {settings.projects_directory || '/projects'} for dev containers
                        </p>
                      </div>
                    </div>

                  </div>

                  {/* Dockerfile Dependencies Configuration Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <FileText className="w-6 h-6 text-primary" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">Dockerfile Dependency Tracking</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Automatically track base and build images in Dockerfiles</p>
                        </div>
                      </div>
                      <HelpTooltip content="Scans FROM statements in Dockerfiles to track base and build images, including multi-stage builds. Checks for updated image tags on schedule. View Dockerfile dependencies in the Dependencies tab (My Projects). Notifications sent when updates are available." />
                    </div>

                    <div className="space-y-4">
                      {/* Auto-Scan Dockerfiles */}
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Auto-Scan Dockerfiles
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Automatically scan Dockerfiles when containers are added
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('dockerfile_auto_scan', !settings.dockerfile_auto_scan)}
                          disabled={saving}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                            settings.dockerfile_auto_scan ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.dockerfile_auto_scan ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>

                      {/* Dockerfile Scan Schedule */}
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Update Check Schedule
                        </label>
                        <select
                          value={settings.dockerfile_scan_schedule || 'daily'}
                          onChange={(e) => updateSetting('dockerfile_scan_schedule', e.target.value)}
                          disabled={saving}
                          className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none disabled:opacity-50"
                        >
                          <option value="disabled">Disabled</option>
                          <option value="daily">Daily (3 AM)</option>
                          <option value="weekly">Weekly (Sunday 3 AM)</option>
                        </select>
                        <p className="text-xs text-tide-text-muted mt-1">
                          How often to check for updated base/build images
                        </p>
                      </div>

                      {/* Manual Check All Button */}
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-2">
                          Manual Update Check
                        </label>
                        <button
                          onClick={async () => {
                            try {
                              const result = await api.containers.checkAllDockerfileUpdates();
                              toast.success(`Checked ${result.total_scanned} Dockerfiles, found ${result.updates_found} updates`);
                            } catch {
                              toast.error('Failed to check Dockerfile updates');
                            }
                          }}
                          className="px-4 py-2 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors flex items-center gap-2"
                        >
                          <RefreshCw size={16} />
                          Check All Dockerfile Updates
                        </button>
                        <p className="text-xs text-tide-text-muted mt-1">
                          Manually trigger an update check for all tracked Dockerfiles
                        </p>
                      </div>
                    </div>

                  </div>
                </div>
              )}
            </div>
          )}

          {/* Integrations Tab */}
          {activeTab === 'integrations' && (
            <div className="space-y-6">
              {/* Category-based view if categories available */}
              {categories.length > 0 && (
                <div className="space-y-4">
                  {categories
                    .filter((cat) => cat.category === 'integrations')
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
                                        {setting.encrypted && <span className="text-xs text-tide-text-muted bg-tide-surface px-1.5 py-0.5 rounded ml-2">Encrypted</span>}
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
                                          type={setting.encrypted ? 'password' : typeof settings[setting.key] === 'number' ? 'number' : 'text'}
                                          value={settings[setting.key] || ''}
                                          onChange={(e) => {
                                            const value = typeof settings[setting.key] === 'number'
                                              ? parseInt(e.target.value) || 0
                                              : e.target.value;
                                            handleTextChange(setting.key, String(value));
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

              {/* Integrations Cards */}
              {categories.length === 0 && (
                <div className="columns-1 xl:columns-2 gap-6" style={{ columnGap: '1.5rem' }}>
                  {/* VulnForge Integration Card */}
                  <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <Plug className="w-6 h-6 text-teal-500" />
                        <div>
                          <h2 className="text-xl font-semibold text-tide-text">VulnForge Integration</h2>
                          <p className="text-sm text-tide-text-muted mt-0.5">Vulnerability scanning with authentication</p>
                        </div>
                      </div>
                      <HelpTooltip content="VulnForge URL should point to your VulnForge instance (e.g., http://vulnforge:8787). API key authentication is recommended for automated scanning. Basic auth is useful for testing or manual integration. Test connection after changing authentication settings." />
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <label className="block text-sm font-medium text-tide-text">
                            Enable Integration
                          </label>
                          <p className="text-xs text-tide-text-muted mt-1">
                            Enable VulnForge vulnerability scanning
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => updateSetting('vulnforge_enabled', !settings.vulnforge_enabled)}
                          disabled={saving}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                            settings.vulnforge_enabled ? 'bg-teal-500' : 'bg-red-500'
                          }`}
                        >
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            settings.vulnforge_enabled ? 'translate-x-6' : 'translate-x-1'
                          }`}></span>
                        </button>
                      </div>

                      <div className="flex items-start gap-2">
                        <div className="flex-1">
                          <label className="block text-sm font-medium text-tide-text mb-2">
                            VulnForge URL
                          </label>
                          <input
                            type="text"
                            value={settings.vulnforge_url || ''}
                            onChange={(e) => handleTextChange('vulnforge_url', e.target.value)}
                            disabled={saving}
                            placeholder="http://vulnforge:8787"
                            className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                          />
                          <p className="text-xs text-tide-text-muted mt-1">
                            URL to VulnForge instance
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleTestConnection('vulnforge')}
                          disabled={testingVulnForge}
                          className="mt-7 px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50 border border-tide-border"
                        >
                          {testingVulnForge ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CircleCheck className="w-4 h-4" />}
                          {testingVulnForge ? 'Testing...' : 'Test Connection'}
                        </button>
                      </div>

                      {/* Authentication Section */}
                      <div>
                        <label className="block text-sm font-medium text-tide-text mb-3">
                          <div className="flex items-center gap-2">
                            <Info className="w-4 h-4 text-teal-500" />
                            Authentication
                          </div>
                        </label>
                        <p className="text-xs text-tide-text-muted mb-3">
                          Select authentication method
                        </p>

                        {/* Auth Type Selector */}
                        <div className="grid grid-cols-3 gap-2 mb-4">
                          <button
                            type="button"
                            onClick={() => updateSetting('vulnforge_auth_type', 'none')}
                            disabled={saving}
                            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                              (settings.vulnforge_auth_type || 'none') === 'none'
                                ? 'bg-teal-500 text-tide-text'
                                : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
                            }`}
                          >
                            None
                          </button>
                          <button
                            type="button"
                            onClick={() => updateSetting('vulnforge_auth_type', 'basic_auth')}
                            disabled={saving}
                            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                              settings.vulnforge_auth_type === 'basic_auth'
                                ? 'bg-teal-500 text-tide-text'
                                : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
                            }`}
                          >
                            Basic Auth
                          </button>
                          <button
                            type="button"
                            onClick={() => updateSetting('vulnforge_auth_type', 'api_key')}
                            disabled={saving}
                            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                              settings.vulnforge_auth_type === 'api_key'
                                ? 'bg-teal-500 text-tide-text'
                                : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
                            }`}
                          >
                            API Key
                          </button>
                        </div>

                        {/* Auth Info Message */}
                        {(settings.vulnforge_auth_type || 'none') === 'none' && (
                          <div className="bg-teal-500/10 border border-teal-500/30 rounded p-3">
                            <p className="text-xs text-teal-400">
                              No authentication configured. VulnForge will be accessed without credentials.
                            </p>
                          </div>
                        )}

                        {/* Basic Auth Fields */}
                        {settings.vulnforge_auth_type === 'basic_auth' && (
                          <div className="space-y-3 mt-3">
                            <div>
                              <label className="block text-sm font-medium text-tide-text mb-2">
                                Username
                              </label>
                              <input
                                type="text"
                                value={settings.vulnforge_username || ''}
                                onChange={(e) => handleTextChange('vulnforge_username', e.target.value)}
                                disabled={saving}
                                className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                              />
                            </div>
                            <div>
                              <label className="block text-sm font-medium text-tide-text mb-2">
                                Password
                              </label>
                              <input
                                type="password"
                                value={settings.vulnforge_password || ''}
                                onChange={(e) => handleTextChange('vulnforge_password', e.target.value)}
                                disabled={saving}
                                className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                              />
                            </div>
                          </div>
                        )}

                        {/* API Key Field */}
                        {settings.vulnforge_auth_type === 'api_key' && (
                          <div className="mt-3">
                            <label className="block text-sm font-medium text-tide-text mb-2">
                              API Key
                            </label>
                            <input
                              type="password"
                              value={settings.vulnforge_api_key || ''}
                              onChange={(e) => handleTextChange('vulnforge_api_key', e.target.value)}
                              disabled={saving}
                              className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                            />
                          </div>
                        )}
                      </div>

                      {/* About VulnForge Link */}
                      <div className="pt-4 border-t border-tide-border flex items-center gap-2">
                        <Info className="w-4 h-4 text-teal-500" />
                        <span className="text-sm text-tide-text">Learn more:</span>
                        <HelpTooltip content="VulnForge scans container images for security vulnerabilities. Provides CVE tracking and vulnerability data comparisons. Enables security-driven update policies. Integration is optional but highly recommended for production use. Works with Docker Hub, GHCR, and custom registries." />
                        <span className="text-sm text-tide-text-muted">About VulnForge</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Notifications Tab */}
          {activeTab === 'notifications' && (
            <div className="space-y-6">
              {/* Sub-tabs for notification services */}
              <NotificationSubTabs
                activeSubTab={notificationSubTab}
                onSubTabChange={setNotificationSubTab}
                enabledServices={{
                  ntfy: Boolean(settings.ntfy_enabled),
                  gotify: Boolean(settings.gotify_enabled),
                  pushover: Boolean(settings.pushover_enabled),
                  slack: Boolean(settings.slack_enabled),
                  discord: Boolean(settings.discord_enabled),
                  telegram: Boolean(settings.telegram_enabled),
                  email: Boolean(settings.email_enabled),
                }}
              />

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Service Configuration */}
                <div>
                  {notificationSubTab === 'ntfy' && (
                    <NtfyConfig
                      settings={settings}
                      onSettingChange={updateSetting}
                      onTextChange={handleTextChange}
                      onTest={() => handleTestConnection('ntfy')}
                      testing={testingNtfy}
                      saving={saving}
                    />
                  )}
                  {notificationSubTab === 'gotify' && (
                    <GotifyConfig
                      settings={settings}
                      onSettingChange={updateSetting}
                      onTextChange={handleTextChange}
                      onTest={() => handleTestConnection('gotify')}
                      testing={testingGotify}
                      saving={saving}
                    />
                  )}
                  {notificationSubTab === 'pushover' && (
                    <PushoverConfig
                      settings={settings}
                      onSettingChange={updateSetting}
                      onTextChange={handleTextChange}
                      onTest={() => handleTestConnection('pushover')}
                      testing={testingPushover}
                      saving={saving}
                    />
                  )}
                  {notificationSubTab === 'slack' && (
                    <SlackConfig
                      settings={settings}
                      onSettingChange={updateSetting}
                      onTextChange={handleTextChange}
                      onTest={() => handleTestConnection('slack')}
                      testing={testingSlack}
                      saving={saving}
                    />
                  )}
                  {notificationSubTab === 'discord' && (
                    <DiscordConfig
                      settings={settings}
                      onSettingChange={updateSetting}
                      onTextChange={handleTextChange}
                      onTest={() => handleTestConnection('discord')}
                      testing={testingDiscord}
                      saving={saving}
                    />
                  )}
                  {notificationSubTab === 'telegram' && (
                    <TelegramConfig
                      settings={settings}
                      onSettingChange={updateSetting}
                      onTextChange={handleTextChange}
                      onTest={() => handleTestConnection('telegram')}
                      testing={testingTelegram}
                      saving={saving}
                    />
                  )}
                  {notificationSubTab === 'email' && (
                    <EmailConfig
                      settings={settings}
                      onSettingChange={updateSetting}
                      onTextChange={handleTextChange}
                      onTest={() => handleTestConnection('email')}
                      testing={testingEmail}
                      saving={saving}
                    />
                  )}
                </div>

                {/* Event Notifications Card */}
                <EventNotificationsCard
                  settings={settings}
                  onSettingChange={updateSetting}
                  onTextChange={handleTextChange}
                  saving={saving}
                  hasEnabledService={
                    Boolean(settings.ntfy_enabled) ||
                    Boolean(settings.gotify_enabled) ||
                    Boolean(settings.pushover_enabled) ||
                    Boolean(settings.slack_enabled) ||
                    Boolean(settings.discord_enabled) ||
                    Boolean(settings.telegram_enabled) ||
                    Boolean(settings.email_enabled)
                  }
                />
              </div>
            </div>
          )}

          {/* Backup Tab */}
          {activeTab === 'backup' && (
            <div className="space-y-6">
              {loadingBackups ? (
                <div className="flex items-center justify-center py-12">
                  <RefreshCw className="w-8 h-8 animate-spin text-primary" />
                </div>
              ) : backups ? (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Database Card */}
                    <div className="bg-tide-surface rounded-lg p-6">
                      <div className="flex items-center gap-3 mb-4">
                        <Database className="w-6 h-6 text-primary" />
                        <h2 className="text-xl font-semibold text-tide-text">Database</h2>
                      </div>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between items-start">
                          <span className="text-tide-text-muted">Path:</span>
                          <span className="font-mono text-tide-text text-right ml-4 break-all">{backups.stats.database_path}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-tide-text-muted">Size:</span>
                          <span className="font-mono text-tide-text">{(backups.stats.database_size / 1024 / 1024).toFixed(2)} MB</span>
                        </div>
                        <div className="flex justify-between items-start">
                          <span className="text-tide-text-muted">Last Modified:</span>
                          <span className="font-mono text-tide-text text-right ml-4">{new Date(backups.stats.database_modified).toLocaleString()}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-tide-text-muted">Status:</span>
                          <span className={`font-mono ${backups.stats.database_exists ? 'text-green-400' : 'text-red-400'}`}>
                            {backups.stats.database_exists ? 'Exists' : 'Missing'}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Backups Card */}
                    <div className="bg-tide-surface rounded-lg p-6">
                      <div className="flex items-center gap-3 mb-4">
                        <HardDrive className="w-6 h-6 text-primary" />
                        <h2 className="text-xl font-semibold text-tide-text">Backups</h2>
                      </div>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span className="text-tide-text-muted">Total Backups:</span>
                          <span className="font-mono text-tide-text">{backups.stats.total_backups}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-tide-text-muted">Total Size:</span>
                          <span className="font-mono text-tide-text">{(backups.stats.total_size / 1024 / 1024).toFixed(2)} MB</span>
                        </div>
                        <div className="flex justify-between items-start">
                          <span className="text-tide-text-muted">Directory:</span>
                          <span className="font-mono text-tide-text text-right ml-4 break-all">{backups.stats.backup_directory}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Backup Management Card */}
                  <div className="bg-tide-surface rounded-lg p-6">
                    <div className="flex items-center justify-between mb-4">
                      <h2 className="text-xl font-semibold text-tide-text">Backup Management</h2>
                      <div className="flex gap-2">
                        <label className={`px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors cursor-pointer border border-tide-border ${
                          uploadingBackup ? 'opacity-50 cursor-not-allowed' : ''
                        }`}>
                          {uploadingBackup ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Upload className="w-5 h-5" />}
                          {uploadingBackup ? 'Uploading...' : 'Upload'}
                          <input
                            ref={fileInputRef}
                            accept=".json"
                            className="hidden"
                            type="file"
                            onChange={handleUploadBackup}
                            disabled={uploadingBackup}
                          />
                        </label>
                        <button
                          onClick={handleCreateBackup}
                          disabled={creatingBackup}
                          className="px-4 py-2 bg-primary hover:bg-primary/80 text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50"
                        >
                          {creatingBackup ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Plus className="w-5 h-5" />}
                          {creatingBackup ? 'Creating...' : 'Create Backup'}
                        </button>
                      </div>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead className="bg-tide-surface/50">
                          <tr>
                            <th className="px-4 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">Filename</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">Size</th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">Created</th>
                            <th className="px-4 py-3 text-right text-xs font-medium text-tide-text-muted uppercase tracking-wider">Actions</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800">
                          {backups.backups.length === 0 ? (
                            <tr>
                              <td colSpan={4} className="px-4 py-8 text-center text-tide-text-muted">
                                No backups found. Create your first backup to get started.
                              </td>
                            </tr>
                          ) : (
                            backups.backups.map((backup) => (
                              <tr key={backup.filename} className="hover:bg-tide-surface/30 cursor-pointer transition-colors">
                                <td className="px-4 py-4 text-sm">
                                  <div className="flex items-center gap-2">
                                    {backup.is_safety && (
                                      <span title="Safety Backup" className="flex-shrink-0">
                                        <Shield className="w-4 h-4 text-blue-400" />
                                      </span>
                                    )}
                                    <div className="flex flex-col">
                                      <span className="font-mono text-tide-text">{backup.filename}</span>
                                      {backup.is_safety && (
                                        <span className="text-xs text-blue-400 mt-0.5">Protected Safety Backup</span>
                                      )}
                                    </div>
                                  </div>
                                </td>
                                <td className="px-4 py-4 text-sm">
                                  <div className="flex flex-col">
                                    <span className="font-mono text-tide-text">{formatBytes(backup.size_bytes)}</span>
                                    <span className="text-xs text-tide-text-muted mt-0.5">{backup.size_mb.toFixed(2)} MB</span>
                                  </div>
                                </td>
                                <td className="px-4 py-4 text-sm">
                                  <div className="flex flex-col">
                                    <span className="text-tide-text">{formatDistanceToNow(new Date(backup.created), { addSuffix: true })}</span>
                                    <span className="text-xs text-tide-text-muted mt-0.5">{new Date(backup.created).toLocaleString()}</span>
                                  </div>
                                </td>
                                <td className="px-4 py-4 text-sm text-right">
                                  <div className="flex items-center justify-end gap-2">
                                    <button
                                      onClick={() => handleDownloadBackup(backup.filename)}
                                      className="p-2 text-primary hover:bg-primary/10 rounded transition-colors"
                                      title="Download backup"
                                    >
                                      <Download className="w-4 h-4" />
                                    </button>
                                    <button
                                      onClick={() => openRestoreModal(backup)}
                                      className="p-2 text-orange-500 hover:bg-orange-500/10 rounded transition-colors"
                                      title="Restore from backup"
                                    >
                                      <RotateCcw className="w-4 h-4" />
                                    </button>
                                    <button
                                      onClick={() => openDeleteModal(backup)}
                                      disabled={backup.is_safety}
                                      className="p-2 text-red-500 hover:bg-red-500/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                      title={backup.is_safety ? 'Safety backups cannot be deleted' : 'Delete backup'}
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Info Cards Grid */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Configuration Tips */}
                    <div className="bg-tide-surface/50 border border-tide-border rounded-lg p-4">
                      <h3 className="text-sm font-semibold text-tide-text mb-3 flex items-center gap-2">
                        <Info className="w-4 h-4 text-blue-400" />
                        Configuration Tips
                      </h3>
                      <ul className="text-xs text-tide-text-muted space-y-1.5">
                        <li>• Create backups before major configuration changes</li>
                        <li>• Backups include all settings and container metadata</li>
                        <li>• Download backups to external storage for disaster recovery</li>
                        <li>• Restoring creates a safety backup of current settings first</li>
                        <li>• Regular backups help prevent data loss from misconfigurations</li>
                      </ul>
                    </div>

                    {/* About Backups */}
                    <div className="bg-tide-surface/50 border border-tide-border rounded-lg p-4">
                      <h3 className="text-sm font-semibold text-tide-text mb-3 flex items-center gap-2">
                        <Info className="w-4 h-4 text-blue-400" />
                        About Backups
                      </h3>
                      <ul className="text-xs text-tide-text-muted space-y-1.5">
                        <li>• Backups are stored in <code className="bg-tide-surface/50 px-1 rounded text-tide-text">/data/backups</code> directory</li>
                        <li>• Backups include all TideWatch settings (credentials, configuration, policies)</li>
                        <li>• Restoring creates an automatic <span className="text-blue-400">safety backup</span> of current settings</li>
                        <li>• Safety backups are protected and cannot be deleted</li>
                        <li>• Container and update history data is not included in backups</li>
                        <li>• Encrypted values (API keys, tokens) remain encrypted in backups</li>
                      </ul>
                    </div>
                  </div>
                </>
              ) : (
                <div className="bg-tide-surface rounded-lg p-12 text-center">
                  <p className="text-tide-text-muted">Failed to load backup information</p>
                  <button
                    onClick={loadBackups}
                    className="mt-4 px-4 py-2 bg-primary hover:bg-primary/80 text-tide-text rounded-lg text-sm"
                  >
                    Retry
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {deleteModalOpen && selectedBackup && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-tide-surface rounded-lg max-w-md w-full p-6 border border-tide-border">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-tide-text">Delete Backup</h3>
              <button
                onClick={() => {
                  setDeleteModalOpen(false);
                  setSelectedBackup(null);
                }}
                className="text-tide-text-muted hover:text-tide-text transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
                <p className="text-red-400 text-sm font-medium mb-2">Warning: This action cannot be undone</p>
                <p className="text-tide-text text-sm">
                  Are you sure you want to delete this backup? Once deleted, it cannot be recovered.
                </p>
              </div>

              <div className="space-y-2 bg-tide-surface/50 rounded-lg p-4">
                <div className="flex justify-between text-sm">
                  <span className="text-tide-text-muted">Filename:</span>
                  <span className="text-tide-text font-mono">{selectedBackup.filename}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-tide-text-muted">Size:</span>
                  <span className="text-tide-text">{formatBytes(selectedBackup.size_bytes)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-tide-text-muted">Created:</span>
                  <span className="text-tide-text">{formatDistanceToNow(new Date(selectedBackup.created), { addSuffix: true })}</span>
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => {
                    setDeleteModalOpen(false);
                    setSelectedBackup(null);
                  }}
                  className="flex-1 px-4 py-2 bg-tide-surface-light hover:bg-tide-border-light text-tide-text rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDelete}
                  className="flex-1 px-4 py-2 bg-red-500 hover:bg-red-600 text-tide-text rounded-lg transition-colors"
                >
                  Delete Backup
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Restore Confirmation Modal */}
      {restoreModalOpen && selectedBackup && backups && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-tide-surface rounded-lg max-w-md w-full p-6 border border-tide-border">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-tide-text">Restore Backup</h3>
              <button
                onClick={() => {
                  setRestoreModalOpen(false);
                  setSelectedBackup(null);
                }}
                className="text-tide-text-muted hover:text-tide-text transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div className="bg-orange-500/10 border border-orange-500/20 rounded-lg p-4">
                <p className="text-orange-400 text-sm font-medium mb-2">Before Restoring</p>
                <p className="text-tide-text text-sm">
                  A safety backup of your current settings will be created automatically before restoring.
                  This ensures you can rollback if needed.
                </p>
              </div>

              <div className="space-y-3">
                <div className="bg-tide-surface/50 rounded-lg p-4">
                  <p className="text-xs text-tide-text-muted uppercase tracking-wide mb-2">Backup to Restore</p>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Filename:</span>
                      <span className="text-tide-text font-mono text-xs">{selectedBackup.filename}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Backup Size:</span>
                      <span className="text-tide-text">{formatBytes(selectedBackup.size_bytes)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Created:</span>
                      <span className="text-tide-text">{formatDistanceToNow(new Date(selectedBackup.created), { addSuffix: true })}</span>
                    </div>
                  </div>
                </div>

                <div className="bg-tide-surface/50 rounded-lg p-4">
                  <p className="text-xs text-tide-text-muted uppercase tracking-wide mb-2">Current Database</p>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Current Size:</span>
                      <span className="text-tide-text">{formatBytes(backups.stats.database_size)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Last Modified:</span>
                      <span className="text-tide-text">
                        {formatDistanceToNow(new Date(backups.stats.database_modified), { addSuffix: true })}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => {
                    setRestoreModalOpen(false);
                    setSelectedBackup(null);
                  }}
                  className="flex-1 px-4 py-2 bg-tide-surface-light hover:bg-tide-border-light text-tide-text rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmRestore}
                  className="flex-1 px-4 py-2 bg-orange-500 hover:bg-orange-600 text-tide-text rounded-lg transition-colors"
                >
                  Restore Backup
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

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
    </div>
  );
}
