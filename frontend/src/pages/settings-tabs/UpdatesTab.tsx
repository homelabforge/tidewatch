import { useState, useEffect, useCallback } from 'react';
import { RotateCcw, RefreshCw, CircleCheck, HardDrive, Database, Clock, ChevronDown, ChevronRight, Settings as SettingsIcon } from 'lucide-react';
import { toast } from 'sonner';
import { formatDistanceToNow } from 'date-fns';
import { api } from '../../services/api';
import type { SettingCategory } from '../../types';
import { HelpTooltip } from '../../components/HelpTooltip';

interface UpdatesTabProps {
  settings: Record<string, unknown>;
  saving: boolean;
  updateSetting: (key: string, value: unknown, updateState?: boolean) => Promise<void>;
  handleTextChange: (key: string, value: string) => void;
  categories: SettingCategory[];
}

export default function UpdatesTab({ settings, saving, updateSetting, handleTextChange, categories }: UpdatesTabProps) {
  const [schedulerStatus, setSchedulerStatus] = useState<Record<string, unknown> | null>(null);
  const [loadingScheduler, setLoadingScheduler] = useState(false);
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());

  const loadSchedulerStatus = useCallback(async () => {
    try {
      setLoadingScheduler(true);
      const status = await api.updates.getSchedulerStatus();
      setSchedulerStatus(status.scheduler);
    } catch (error) {
      console.error('Failed to load scheduler status:', error);
    } finally {
      setLoadingScheduler(false);
    }
  }, []);

  useEffect(() => {
    loadSchedulerStatus();
  }, [loadSchedulerStatus]);

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
      updates: RotateCcw,
      cleanup: HardDrive,
    };
    return icons[category] || SettingsIcon;
  };

  const getCategoryTitle = (category: string) => {
    const titles: Record<string, string> = {
      updates: 'Update Management',
      cleanup: 'Cleanup & Maintenance',
    };
    return titles[category] || category.charAt(0).toUpperCase() + category.slice(1);
  };

  return (
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
              {Boolean(schedulerStatus.next_run) && (
                <div className="text-right">
                  <p className="text-xs text-tide-text-muted">Next Run</p>
                  <p className="text-sm font-medium text-tide-text">
                    {formatDistanceToNow(new Date(String(schedulerStatus.next_run)), { addSuffix: true })}
                  </p>
                </div>
              )}
              {Boolean(schedulerStatus.last_check) && (
                <div className="text-right">
                  <p className="text-xs text-tide-text-muted">Last Check</p>
                  <p className="text-sm font-medium text-tide-text">
                    {formatDistanceToNow(new Date(String(schedulerStatus.last_check)), { addSuffix: true })}
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
                                  value={String(settings[setting.key] || '')}
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
                  value={String(settings.check_schedule || '')}
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
                  <span className="text-sm text-tide-text-muted">{String(settings.auto_update_max_concurrent || 3)}</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={String(Number(settings.auto_update_max_concurrent || 3))}
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
                  <span className="text-sm text-tide-text-muted">{String(settings.update_retry_max_attempts || 4)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="10"
                  value={String(Number(settings.update_retry_max_attempts || 4))}
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
                  <span className="text-sm text-tide-text-muted">{String(settings.update_retry_backoff_multiplier || 3)}</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="10"
                  step="0.5"
                  value={String(Number(settings.update_retry_backoff_multiplier || 3))}
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
                  value={String(settings.default_update_window || '')}
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
                  value={String(settings.update_window_enforcement || 'strict')}
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
                  <span className="text-sm text-tide-text-muted">{String(settings.stale_detection_threshold_days || 7)}</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="90"
                  value={String(Number(settings.stale_detection_threshold_days || 7))}
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
                  <span className="text-sm text-tide-text-muted">{String(settings.cleanup_after_days || 7)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="90"
                  value={String(Number(settings.cleanup_after_days || 7))}
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
                  value={String(settings.cleanup_mode || 'dangling')}
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
                  value={String(settings.cleanup_schedule || '0 4 * * *')}
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
                  value={String(settings.cleanup_exclude_patterns || '-dev,rollback')}
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
  );
}
