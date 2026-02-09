import { useState, useEffect, useCallback } from 'react';
import { X, RefreshCw, Zap, Eye, PowerOff, Wand2, RotateCw, Pause, Play, Network, Calendar, Star } from 'lucide-react';
import { Container, RestartState, EnableRestartConfig } from '../../types';
import { api } from '../../services/api';
import { toast } from 'sonner';

interface SettingsTabProps {
  container: Container;
  onUpdate?: () => void;
}

export default function SettingsTab({ container, onUpdate }: SettingsTabProps) {
  const [policy, setPolicy] = useState(container.policy);
  const [scope, setScope] = useState(container.scope);
  const [includePrereleases, setIncludePrereleases] = useState<boolean | null>(container.include_prereleases);
  const [vulnforgeEnabled] = useState(container.vulnforge_enabled);
  const [healthCheckMethod, setHealthCheckMethod] = useState(container.health_check_method);
  const [healthCheckUrl, setHealthCheckUrl] = useState(container.health_check_url || '');
  const [healthCheckAuth, setHealthCheckAuth] = useState('');
  const [releaseSource, setReleaseSource] = useState(container.release_source || '');
  const [autoRestartEnabled, setAutoRestartEnabled] = useState(container.auto_restart_enabled);
  const [savingSettings, setSavingSettings] = useState(false);

  // Restart state
  const [restartState, setRestartState] = useState<RestartState | null>(null);
  const [loadingRestartState, setLoadingRestartState] = useState(false);
  const [restartConfig, setRestartConfig] = useState<EnableRestartConfig>({
    max_attempts: 10,
    backoff_strategy: 'exponential',
    base_delay_seconds: 2,
    max_delay_seconds: 300,
    success_window_seconds: 300,
    health_check_enabled: true,
    health_check_timeout: 60,
    rollback_on_health_fail: false,
  });

  // Dependency state
  const [dependencies, setDependencies] = useState<string[]>(container.dependencies || []);
  const [dependents, setDependents] = useState<string[]>(container.dependents || []);
  const [allContainers, setAllContainers] = useState<Container[]>([]);
  const [selectedDependency, setSelectedDependency] = useState<string>('');

  // Update window state
  const [updateWindow, setUpdateWindow] = useState<string>(container.update_window || '');
  const [updateWindowInput, setUpdateWindowInput] = useState<string>(container.update_window || '');

  // My Projects setting
  const [myProjectsEnabled, setMyProjectsEnabled] = useState(true);

  // Load My Projects setting
  useEffect(() => {
    const loadSettings = async () => {
      try {
        const settings = await api.settings.getAll();
        const myProjectsSetting = settings.find(s => s.key === 'my_projects_enabled');
        setMyProjectsEnabled(myProjectsSetting?.value === 'true' || myProjectsSetting?.value === true);
      } catch (error) {
        console.error('Failed to load settings:', error);
      }
    };
    loadSettings();
  }, []);

  const loadRestartState = useCallback(async () => {
    setLoadingRestartState(true);
    try {
      const state = await api.restarts.getState(container.id);
      setRestartState(state);
      if (state) {
        setRestartConfig({
          max_attempts: state.max_attempts,
          backoff_strategy: state.backoff_strategy as 'exponential' | 'linear' | 'fixed',
          base_delay_seconds: state.base_delay_seconds,
          max_delay_seconds: state.max_delay_seconds,
          success_window_seconds: state.success_window_seconds,
          health_check_enabled: state.health_check_enabled,
          health_check_timeout: state.health_check_timeout,
          rollback_on_health_fail: state.rollback_on_health_fail,
        });
      }
    } catch (error) {
      console.error('Failed to load restart state:', error);
    } finally {
      setLoadingRestartState(false);
    }
  }, [container.id]);

  const loadDependencies = useCallback(async () => {
    try {
      const deps = await api.containers.getDependencies(container.id);
      setDependencies(deps.dependencies);
      setDependents(deps.dependents);
    } catch (error) {
      console.error('Failed to load dependencies:', error);
    }
  }, [container.id]);

  const loadAllContainers = useCallback(async () => {
    try {
      const containers = await api.containers.getAll();
      setAllContainers(containers.filter(c => c.id !== container.id));
    } catch (error) {
      console.error('Failed to load containers:', error);
    }
  }, [container.id]);

  useEffect(() => {
    if (autoRestartEnabled) {
      loadRestartState();
    }
    loadDependencies();
    loadAllContainers();
  }, [autoRestartEnabled, loadRestartState, loadDependencies, loadAllContainers]);

  const saveSettings = async (updates: Record<string, unknown>) => {
    setSavingSettings(true);
    try {
      await api.containers.update(container.id, updates);
      toast.success('Settings saved successfully');
      onUpdate?.();
    } catch (error) {
      console.error('Failed to save settings:', error);
      toast.error('Failed to save settings');
    } finally {
      setSavingSettings(false);
    }
  };

  const handlePolicyChange = async (newPolicy: string) => {
    if (newPolicy === 'auto' && scope === 'major') {
      const confirmed = window.confirm(
        '\u26A0\uFE0F Warning: Auto + Major Scope\n\n' +
        'This combination will automatically apply ALL updates, including MAJOR version updates that may contain breaking changes.\n\n' +
        'Consider setting scope to "Minor" or "Patch" for safer auto-updates.\n\n' +
        'Are you sure?'
      );

      if (!confirmed) return;
    }

    setPolicy(newPolicy);
    await saveSettings({ policy: newPolicy });
  };

  const handleScopeChange = async (newScope: string) => {
    const oldScope = scope;
    setScope(newScope);
    await saveSettings({ scope: newScope });

    if (oldScope !== newScope) {
      try {
        await api.containers.recheckUpdates(container.id);
        toast.success('Updates re-checked with new scope');
        onUpdate?.();
      } catch (error) {
        console.error('Failed to re-check updates:', error);
        toast.error('Failed to re-check updates');
      }
    }
  };

  const handlePrereleasesChange = async (value: string) => {
    const newValue: boolean | null = value === 'null' ? null : value === 'true';
    setIncludePrereleases(newValue);
    await saveSettings({ include_prereleases: newValue });
  };

  const handleHealthCheckMethodChange = async (method: string) => {
    setHealthCheckMethod(method);
    await saveSettings({ health_check_method: method });
  };

  const handleSaveHealthCheckUrl = async () => {
    await saveSettings({ health_check_url: healthCheckUrl });
  };

  const handleSaveHealthAuth = async () => {
    await saveSettings({ health_check_auth: healthCheckAuth });
    setHealthCheckAuth('');
  };

  const handleSaveReleaseSource = async () => {
    await saveSettings({ release_source: releaseSource });
  };

  const handleAutoFillHealthCheck = async () => {
    try {
      const response = await fetch(`/api/v1/containers/${container.id}/detect-health-check`);
      const data = await response.json();

      if (data.success && data.detected_url) {
        setHealthCheckUrl(data.detected_url);
        await saveSettings({ health_check_url: data.detected_url });
        toast.success(`Health check URL detected: ${data.detected_url}`);
      } else {
        toast.error(data.message || 'No health check found in compose file');
      }
    } catch (error) {
      console.error('Error detecting health check:', error);
      toast.error('Failed to detect health check URL');
    }
  };

  const handleAutoFillReleaseSource = async () => {
    try {
      const response = await fetch(`/api/v1/containers/${container.id}/detect-release-source`);
      const data = await response.json();

      if (data.success && data.release_source) {
        setReleaseSource(data.release_source);
        await saveSettings({ release_source: data.release_source });
        toast.success(`Release source detected: ${data.release_source}`);
      } else {
        toast(data.message || 'Could not auto-detect release source. Please enter manually.');
      }
    } catch (error) {
      console.error('Error detecting release source:', error);
      toast.error('Failed to detect release source');
    }
  };

  const toggleAutoRestart = async () => {
    const newValue = !autoRestartEnabled;

    try {
      if (newValue) {
        const result = await api.restarts.enable(container.id, restartConfig);
        setRestartState(result.state);
        setAutoRestartEnabled(true);
        toast.success('Auto-restart enabled');
      } else {
        await api.restarts.disable(container.id);
        setAutoRestartEnabled(false);
        toast.success('Auto-restart disabled');
      }
      onUpdate?.();
    } catch (error) {
      console.error('Error toggling auto-restart:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to toggle auto-restart');
    }
  };

  const handleSaveRestartConfig = async () => {
    try {
      const result = await api.restarts.enable(container.id, restartConfig);
      setRestartState(result.state);
      toast.success('Restart configuration saved');
      onUpdate?.();
    } catch (error) {
      console.error('Error saving restart config:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to save configuration');
    }
  };

  const handleResetRestartState = async () => {
    if (!confirm('Are you sure you want to reset the restart failure count?')) return;

    try {
      await api.restarts.reset(container.id);
      await loadRestartState();
      toast.success('Restart state reset');
    } catch (error) {
      console.error('Error resetting restart state:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to reset state');
    }
  };

  const handlePauseRestart = async () => {
    const hours = prompt('Pause auto-restart for how many hours?', '24');
    if (!hours) return;

    const duration = parseInt(hours) * 3600;
    if (isNaN(duration) || duration <= 0) {
      toast.error('Invalid duration');
      return;
    }

    try {
      await api.restarts.pause(container.id, duration);
      await loadRestartState();
      toast.success(`Auto-restart paused for ${hours} hours`);
    } catch (error) {
      console.error('Error pausing restart:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to pause');
    }
  };

  const handleResumeRestart = async () => {
    try {
      await api.restarts.resume(container.id);
      await loadRestartState();
      toast.success('Auto-restart resumed');
    } catch (error) {
      console.error('Error resuming restart:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to resume');
    }
  };

  const handleAddDependency = async () => {
    if (!selectedDependency) return;

    const newDeps = [...dependencies, selectedDependency];
    try {
      await api.containers.updateDependencies(container.id, newDeps);
      setDependencies(newDeps);
      setSelectedDependency('');
      toast.success('Dependency added');
      onUpdate?.();
    } catch (error) {
      console.error('Error adding dependency:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to add dependency');
    }
  };

  const handleRemoveDependency = async (dep: string) => {
    const newDeps = dependencies.filter(d => d !== dep);
    try {
      await api.containers.updateDependencies(container.id, newDeps);
      setDependencies(newDeps);
      toast.success('Dependency removed');
      onUpdate?.();
    } catch (error) {
      console.error('Error removing dependency:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to remove dependency');
    }
  };

  const handleSaveUpdateWindow = async () => {
    try {
      await api.containers.updateUpdateWindow(container.id, updateWindowInput || null);
      setUpdateWindow(updateWindowInput);
      toast.success('Update window saved');
      onUpdate?.();
    } catch (error) {
      console.error('Error saving update window:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to save update window');
    }
  };

  const handleToggleMyProject = async () => {
    try {
      const newValue = !container.is_my_project;
      await api.containers.update(container.id, { is_my_project: newValue });
      container.is_my_project = newValue;
      toast.success(newValue ? 'Added to My Projects' : 'Removed from My Projects');
      onUpdate?.();
    } catch (error) {
      console.error('Error toggling My Project:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to update My Project status');
    }
  };

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
  };

  return (
    <div>
      <h3 className="text-lg font-semibold text-tide-text mb-6">Container Settings</h3>

      {/* My Project Section - Only show if feature is enabled */}
      {myProjectsEnabled && (
        <div className="bg-tide-surface/50 rounded-lg p-6 border border-tide-border-light mb-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Star size={20} className={container.is_my_project ? 'fill-primary text-primary' : 'text-tide-text-muted'} />
              <div>
                <h4 className="text-base font-semibold text-tide-text">My Project</h4>
                <p className="text-sm text-tide-text-muted mt-1">
                  Mark this as your own project to group it separately and track application dependencies. Dev containers are auto-detected from your projects directory.
                </p>
              </div>
            </div>
            <button
              onClick={handleToggleMyProject}
              disabled={savingSettings}
              className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                container.is_my_project
                  ? 'bg-primary text-tide-text hover:bg-primary/80'
                  : 'bg-tide-surface-light text-tide-text hover:bg-gray-500'
              } disabled:opacity-50`}
            >
              {container.is_my_project ? 'Remove from My Projects' : 'Add to My Projects'}
            </button>
          </div>
        </div>
      )}

      {/* CSS columns for masonry-style layout with natural card sizing */}
      <div className="columns-1 xl:columns-2 gap-6 space-y-6 xl:space-y-0" style={{ columnGap: '1.5rem' }}>

        {/* Auto-Restart Section */}
        <div className="bg-tide-surface/50 rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg flex items-center justify-center bg-gray-500/10 border border-gray-500/20">
                <RotateCw className="w-5 h-5 text-tide-text-muted" />
              </div>
              <div>
                <h4 className="text-base font-semibold text-tide-text">Auto-Restart</h4>
                <p className="text-sm text-tide-text-muted">
                  {autoRestartEnabled ? (
                    restartState?.is_paused ? 'Enabled (Paused)' : 'Enabled'
                  ) : 'Disabled'}
                </p>
              </div>
            </div>
            <button
              onClick={toggleAutoRestart}
              disabled={savingSettings}
              className="px-4 py-2 bg-primary text-tide-text rounded-lg hover:bg-primary/80 transition-colors disabled:opacity-50"
            >
              {autoRestartEnabled ? 'Disable' : 'Enable'}
            </button>
          </div>

          {autoRestartEnabled && !loadingRestartState && restartState && (
            <div className="mt-4 space-y-4 pt-4 border-t border-tide-border-light">
              {/* Restart Statistics */}
              <div>
                <h5 className="text-sm font-medium text-tide-text mb-3">Current State</h5>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-tide-surface/50 rounded-lg p-3">
                    <div className="text-xs text-tide-text-muted mb-1">Consecutive Failures</div>
                    <div className={`text-lg font-semibold ${restartState.consecutive_failures > 0 ? 'text-red-400' : 'text-green-400'}`}>
                      {restartState.consecutive_failures}
                    </div>
                  </div>
                  <div className="bg-tide-surface/50 rounded-lg p-3">
                    <div className="text-xs text-tide-text-muted mb-1">Total Restarts</div>
                    <div className="text-lg font-semibold text-tide-text">{restartState.total_restarts}</div>
                  </div>
                  <div className="bg-tide-surface/50 rounded-lg p-3">
                    <div className="text-xs text-tide-text-muted mb-1">Current Backoff</div>
                    <div className="text-lg font-semibold text-tide-text">{formatDuration(restartState.current_backoff_seconds)}</div>
                  </div>
                  <div className="bg-tide-surface/50 rounded-lg p-3">
                    <div className="text-xs text-tide-text-muted mb-1">Max Retries</div>
                    <div className={`text-lg font-semibold ${restartState.max_retries_reached ? 'text-red-400' : 'text-tide-text'}`}>
                      {restartState.max_retries_reached ? 'Reached' : 'Not Reached'}
                    </div>
                  </div>
                </div>
              </div>

              {/* Configuration */}
              <div>
                <h5 className="text-sm font-medium text-tide-text mb-3">Configuration</h5>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs text-tide-text-muted mb-1">Backoff Strategy</label>
                    <select
                      value={restartConfig.backoff_strategy}
                      onChange={(e) => setRestartConfig({ ...restartConfig, backoff_strategy: e.target.value as 'exponential' | 'linear' | 'fixed' })}
                      className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                    >
                      <option value="exponential">Exponential</option>
                      <option value="linear">Linear</option>
                      <option value="fixed">Fixed</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs text-tide-text-muted mb-1">Max Attempts ({restartConfig.max_attempts})</label>
                    <input
                      type="range"
                      min="1"
                      max="100"
                      value={restartConfig.max_attempts}
                      onChange={(e) => setRestartConfig({ ...restartConfig, max_attempts: parseInt(e.target.value) })}
                      className="w-full accent-teal-500"
                    />
                  </div>

                  <div>
                    <label className="block text-xs text-tide-text-muted mb-1">Base Delay ({restartConfig.base_delay_seconds}s)</label>
                    <input
                      type="range"
                      min="1"
                      max="60"
                      value={restartConfig.base_delay_seconds}
                      onChange={(e) => setRestartConfig({ ...restartConfig, base_delay_seconds: parseFloat(e.target.value) })}
                      className="w-full accent-teal-500"
                    />
                  </div>

                  <div>
                    <label className="block text-xs text-tide-text-muted mb-1">Max Delay ({formatDuration(restartConfig.max_delay_seconds)})</label>
                    <input
                      type="range"
                      min="60"
                      max="3600"
                      value={restartConfig.max_delay_seconds}
                      onChange={(e) => setRestartConfig({ ...restartConfig, max_delay_seconds: parseFloat(e.target.value) })}
                      className="w-full accent-teal-500"
                    />
                  </div>

                  <div>
                    <label className="block text-xs text-tide-text-muted mb-1">Success Window ({formatDuration(restartConfig.success_window_seconds)})</label>
                    <input
                      type="range"
                      min="60"
                      max="1800"
                      value={restartConfig.success_window_seconds}
                      onChange={(e) => setRestartConfig({ ...restartConfig, success_window_seconds: parseInt(e.target.value) })}
                      className="w-full accent-teal-500"
                    />
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-tide-text">Health Check Enabled</span>
                    <button
                      onClick={() => setRestartConfig({ ...restartConfig, health_check_enabled: !restartConfig.health_check_enabled })}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        restartConfig.health_check_enabled ? 'bg-primary' : 'bg-tide-surface-light'
                      }`}
                    >
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        restartConfig.health_check_enabled ? 'translate-x-6' : 'translate-x-1'
                      }`} />
                    </button>
                  </div>

                  {restartConfig.health_check_enabled && (
                    <div>
                      <label className="block text-xs text-tide-text-muted mb-1">Health Check Timeout ({restartConfig.health_check_timeout}s)</label>
                      <input
                        type="number"
                        min="10"
                        max="300"
                        value={restartConfig.health_check_timeout}
                        onChange={(e) => setRestartConfig({ ...restartConfig, health_check_timeout: parseInt(e.target.value) })}
                        className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text text-sm"
                      />
                    </div>
                  )}

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-tide-text">Rollback on Health Fail</span>
                    <button
                      onClick={() => setRestartConfig({ ...restartConfig, rollback_on_health_fail: !restartConfig.rollback_on_health_fail })}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        restartConfig.rollback_on_health_fail ? 'bg-primary' : 'bg-tide-surface-light'
                      }`}
                    >
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        restartConfig.rollback_on_health_fail ? 'translate-x-6' : 'translate-x-1'
                      }`} />
                    </button>
                  </div>

                  <button
                    onClick={handleSaveRestartConfig}
                    className="w-full px-4 py-2 bg-primary text-tide-text rounded-lg hover:bg-primary/80 transition-colors"
                  >
                    Save Configuration
                  </button>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-2">
                <button
                  onClick={handleResetRestartState}
                  disabled={restartState.consecutive_failures === 0}
                  className="flex-1 px-3 py-2 bg-tide-surface text-tide-text rounded-lg hover:bg-tide-surface-light transition-colors disabled:opacity-50 text-sm flex items-center justify-center gap-2"
                >
                  <RefreshCw className="w-4 h-4" />
                  Reset State
                </button>
                {restartState.is_paused ? (
                  <button
                    onClick={handleResumeRestart}
                    className="flex-1 px-3 py-2 bg-green-600 text-tide-text rounded-lg hover:bg-green-700 transition-colors text-sm flex items-center justify-center gap-2"
                  >
                    <Play className="w-4 h-4" />
                    Resume
                  </button>
                ) : (
                  <button
                    onClick={handlePauseRestart}
                    className="flex-1 px-3 py-2 bg-yellow-600 text-tide-text rounded-lg hover:bg-yellow-700 transition-colors text-sm flex items-center justify-center gap-2"
                  >
                    <Pause className="w-4 h-4" />
                    Pause
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Update Policy */}
        <div className="bg-tide-surface/50 rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
          <h4 className="text-base font-semibold text-tide-text mb-3">Update Policy</h4>
          <p className="text-sm text-tide-text-muted mb-4">Choose how updates should be handled for this container.</p>

          {/* Segmented Control */}
          <div className="flex gap-1 p-1 bg-tide-surface/50 rounded-lg border border-tide-border">
            {[
              { value: 'auto', label: 'Auto', icon: Zap },
              { value: 'monitor', label: 'Monitor', icon: Eye },
              { value: 'disabled', label: 'Off', icon: PowerOff },
            ].map((item) => (
              <button
                key={item.value}
                onClick={() => handlePolicyChange(item.value)}
                disabled={savingSettings}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium transition-all ${
                  policy === item.value
                    ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30 rounded-md'
                    : 'text-tide-text-muted hover:text-tide-text hover:bg-tide-surface rounded-md border border-transparent'
                } disabled:opacity-50`}
              >
                <item.icon size={16} />
                {item.label}
              </button>
            ))}
          </div>

          {/* Dynamic Description */}
          <p className="text-xs text-tide-text-muted mt-3">
            {policy === 'auto'
              ? 'Updates within the configured scope will be automatically applied.'
              : policy === 'monitor'
                ? 'Updates are detected and shown, but require manual approval before applying.'
                : 'Update checking is disabled for this container.'}
          </p>
        </div>

        {/* Version Scope */}
        <div className={`bg-tide-surface/50 rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border transition-opacity ${policy === 'disabled' ? 'opacity-50 pointer-events-none' : ''}`}>
          <h4 className="text-base font-semibold text-tide-text mb-3">Version Scope</h4>
          <p className="text-sm text-tide-text-muted mb-4">Control which version changes are allowed during updates.</p>
          <div className="grid grid-cols-3 gap-3">
            {[
              { value: 'patch', label: 'Patch', desc: 'Only patch updates (1.2.3 \u2192 1.2.4)' },
              { value: 'minor', label: 'Minor', desc: 'Minor + patch (1.2.x \u2192 1.3.x)' },
              { value: 'major', label: 'Major', desc: 'All updates (1.x.x \u2192 2.x.x)' }
            ].map((item) => (
              <button
                key={item.value}
                onClick={() => handleScopeChange(item.value)}
                disabled={savingSettings}
                className={`p-4 rounded-lg border-2 transition-all text-left ${
                  scope === item.value
                    ? 'border-primary bg-primary/10'
                    : 'border-tide-border bg-tide-surface hover:border-tide-border-light'
                }`}
              >
                <div className="mb-2">
                  <span className={`font-medium ${scope === item.value ? 'text-tide-text' : 'text-tide-text'}`}>{item.label}</span>
                </div>
                <p className="text-xs text-tide-text-muted">{item.desc}</p>
              </button>
            ))}
          </div>
        </div>

        {/* Pre-releases */}
        <div className={`bg-tide-surface/50 rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border transition-opacity ${policy === 'disabled' ? 'opacity-50 pointer-events-none' : ''}`}>
          <h4 className="text-base font-semibold text-tide-text mb-3">Pre-release Versions</h4>
          <p className="text-sm text-tide-text-muted mb-4">Control whether to include pre-release tags when checking for updates.</p>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-tide-text">Pre-release Policy</p>
              <p className="text-xs text-tide-text-muted mt-1">
                {includePrereleases === null
                  ? 'Using global setting'
                  : includePrereleases
                    ? 'Including pre-releases'
                    : 'Stable releases only'}
              </p>
            </div>
            <select
              value={includePrereleases === null ? 'null' : String(includePrereleases)}
              onChange={(e) => handlePrereleasesChange(e.target.value)}
              disabled={savingSettings}
              className="bg-tide-surface border border-tide-border rounded-md px-3 py-1.5 text-sm text-tide-text focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="null">Use Global Setting</option>
              <option value="false">Stable Releases Only</option>
              <option value="true">Include Pre-releases</option>
            </select>
          </div>
        </div>

        {/* Vulnerability Scanning */}
        <div className="bg-tide-surface/50 rounded-lg p-6">
          <h4 className="text-base font-semibold text-tide-text mb-3">Vulnerability Scanning</h4>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-tide-text">VulnForge Integration</p>
              <p className="text-xs text-tide-text-muted mt-1">Scan for security vulnerabilities</p>
            </div>
            <div className={`px-3 py-1.5 rounded ${
              vulnforgeEnabled ? 'bg-green-500/10 text-green-500' : 'bg-gray-500/10 text-tide-text-muted'
            }`}>
              {vulnforgeEnabled ? 'Enabled' : 'Disabled'}
            </div>
          </div>
        </div>

        {/* Health Check */}
        <div className="bg-tide-surface/50 rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
          <h4 className="text-base font-semibold text-tide-text mb-3">Health Check</h4>
          <p className="text-sm text-tide-text-muted mb-3">Control how TideWatch validates this container after updates.</p>
          <div className="space-y-4">
            <div>
              <label className="text-xs uppercase tracking-wide text-tide-text-muted mb-1 block">Health Check URL</label>
              <div className="flex gap-2">
                <input
                  placeholder="http://container:port/health"
                  className="flex-1 px-3 py-2 bg-tide-surface border border-tide-border text-tide-text placeholder-gray-500 rounded-lg"
                  type="text"
                  value={healthCheckUrl}
                  onChange={(e) => setHealthCheckUrl(e.target.value)}
                />
                <button
                  onClick={handleAutoFillHealthCheck}
                  className="px-3 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg flex items-center gap-1"
                  title="Auto-fill from compose labels"
                >
                  <Wand2 className="w-4 h-4" />
                </button>
                <button
                  onClick={handleSaveHealthCheckUrl}
                  disabled={savingSettings}
                  className="px-4 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg disabled:opacity-50"
                >
                  Save
                </button>
              </div>
              <p className="text-xs text-tide-text-muted mt-1">HTTP endpoint to check container health after updates.</p>
            </div>
            <div>
              <label className="text-xs uppercase tracking-wide text-tide-text-muted mb-1 block">Method</label>
              <select
                value={healthCheckMethod}
                onChange={(e) => handleHealthCheckMethodChange(e.target.value)}
                disabled={savingSettings}
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border text-tide-text rounded-lg focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
              >
                <option value="auto">Auto (HTTP if URL, otherwise Docker)</option>
                <option value="http">HTTP only (always hit the URL)</option>
                <option value="docker">Docker inspect only</option>
              </select>
            </div>
            <div>
              <label className="text-xs uppercase tracking-wide text-tide-text-muted mb-1 block">Auth Token</label>
              <div className="flex gap-2">
                <input
                  placeholder="apikey=XYZ or token:Bearer ..."
                  className="flex-1 px-3 py-2 bg-tide-surface border border-tide-border text-tide-text placeholder-gray-500 rounded-lg"
                  type="password"
                  value={healthCheckAuth}
                  onChange={(e) => setHealthCheckAuth(e.target.value)}
                />
                <button
                  onClick={handleSaveHealthAuth}
                  disabled={!healthCheckAuth || savingSettings}
                  className="px-4 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Save
                </button>
              </div>
              <p className="text-xs text-tide-text-muted mt-1">
                {container.health_check_has_auth ? 'Auth token configured' : 'No auth token stored'}
              </p>
            </div>
          </div>
        </div>

        {/* Release Source */}
        <div className="bg-tide-surface/50 rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
          <h4 className="text-base font-semibold text-tide-text mb-3">Release Source</h4>
          <p className="text-sm text-tide-text-muted mb-3">Provide a GitHub repo or changelog URL for release notes.</p>
          <div className="flex gap-2">
            <input
              placeholder="github:user/repo or https://example.com/changelog"
              className="flex-1 px-3 py-2 bg-tide-surface border border-tide-border text-tide-text placeholder-gray-500 rounded-lg"
              type="text"
              value={releaseSource}
              onChange={(e) => setReleaseSource(e.target.value)}
            />
            <button
              onClick={handleAutoFillReleaseSource}
              className="px-3 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg flex items-center gap-1"
              title="Auto-detect from image name"
            >
              <Wand2 className="w-4 h-4" />
            </button>
            <button
              onClick={handleSaveReleaseSource}
              disabled={savingSettings}
              className="px-4 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg disabled:opacity-50"
            >
              Save
            </button>
          </div>
          <p className="text-xs text-tide-text-muted mt-2">
            Examples: github:linuxserver/docker-sonarr, https://lscr.io/changelog/sonarr
          </p>
        </div>

        {/* Dependency Management Section */}
        <div className="bg-tide-surface/50 rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg flex items-center justify-center bg-gray-500/10 border border-gray-500/20">
              <Network className="w-5 h-5 text-tide-text-muted" />
            </div>
            <div>
              <h4 className="text-base font-semibold text-tide-text">Dependency Management</h4>
              <p className="text-sm text-tide-text-muted">Define update order based on container dependencies</p>
            </div>
          </div>

          {/* Current Dependencies */}
          <div className="mb-4">
            <label className="block text-xs uppercase tracking-wide text-tide-text-muted mb-2">
              This container depends on:
            </label>
            {dependencies.length > 0 ? (
              <div className="flex flex-wrap gap-2 mb-3">
                {dependencies.map((dep) => (
                  <span
                    key={dep}
                    className="px-3 py-1 bg-primary/20 text-primary rounded-lg text-sm flex items-center gap-2"
                  >
                    {dep}
                    <button
                      onClick={() => handleRemoveDependency(dep)}
                      className="hover:text-red-400 transition-colors"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-tide-text-muted text-sm mb-3">No dependencies configured. This container can update independently.</p>
            )}
          </div>

          {/* Add Dependency */}
          <div className="mb-4">
            <label className="block text-xs uppercase tracking-wide text-tide-text-muted mb-2">
              Add Dependency
            </label>
            <div className="flex gap-2">
              <select
                value={selectedDependency}
                onChange={(e) => setSelectedDependency(e.target.value)}
                className="flex-1 px-3 py-2 bg-tide-surface border border-tide-border text-tide-text rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="">Select container...</option>
                {allContainers
                  .filter(c => !dependencies.includes(c.name))
                  .map(c => (
                    <option key={c.id} value={c.name}>{c.name}</option>
                  ))
                }
              </select>
              <button
                onClick={handleAddDependency}
                disabled={!selectedDependency}
                className="px-4 py-2 bg-primary hover:bg-primary/80 text-tide-text rounded-lg transition-colors disabled:opacity-50"
              >
                Add
              </button>
            </div>
            <p className="text-xs text-tide-text-muted mt-2">
              Dependencies will be updated before this container
            </p>
          </div>

          {/* Dependents (read-only) */}
          <div className="pt-4 border-t border-tide-border-light">
            <label className="block text-xs uppercase tracking-wide text-tide-text-muted mb-2">
              Containers that depend on this one:
            </label>
            {dependents.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {dependents.map((dep) => (
                  <span
                    key={dep}
                    className="px-3 py-1 bg-tide-surface-light/50 text-tide-text rounded-lg text-sm"
                  >
                    {dep}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-tide-text-muted text-sm">No containers depend on this one</p>
            )}
          </div>
        </div>

        {/* Update Window Section */}
        <div className="bg-tide-surface/50 rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg flex items-center justify-center bg-gray-500/10 border border-gray-500/20">
              <Calendar className="w-5 h-5 text-tide-text-muted" />
            </div>
            <div>
              <h4 className="text-base font-semibold text-tide-text">Update Window</h4>
              <p className="text-sm text-tide-text-muted">Restrict updates to specific time periods</p>
            </div>
          </div>

          {/* Current Window Display */}
          <div className="mb-4">
            <label className="block text-xs uppercase tracking-wide text-tide-text-muted mb-2">
              Allowed Update Window
            </label>
            {updateWindow ? (
              <div className="bg-tide-surface border border-tide-border rounded-lg p-3 mb-2 flex items-center justify-between">
                <span className="text-tide-text font-mono text-sm">{updateWindow}</span>
                <button
                  onClick={() => {
                    setUpdateWindow('');
                    setUpdateWindowInput('');
                  }}
                  className="text-red-400 hover:text-red-300 text-sm transition-colors"
                >
                  Clear
                </button>
              </div>
            ) : (
              <p className="text-tide-text-muted text-sm mb-2">No restrictions - updates allowed anytime</p>
            )}
          </div>

          {/* Window Input */}
          <div className="mb-3">
            <label className="block text-xs uppercase tracking-wide text-tide-text-muted mb-1">
              Set Update Window
            </label>
            <input
              type="text"
              placeholder="HH:MM-HH:MM or Days:HH:MM-HH:MM"
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border text-tide-text placeholder-gray-500 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              value={updateWindowInput}
              onChange={(e) => setUpdateWindowInput(e.target.value)}
            />
          </div>

          {/* Quick Presets */}
          <div className="mb-4">
            <label className="block text-xs uppercase tracking-wide text-tide-text-muted mb-2">
              Quick Presets
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setUpdateWindowInput('02:00-06:00')}
                className="px-3 py-2 bg-tide-surface hover:bg-tide-surface border border-tide-border text-tide-text rounded-lg text-sm text-left transition-colors"
              >
                <div className="font-medium">Night Window</div>
                <div className="text-xs text-tide-text-muted">02:00-06:00 daily</div>
              </button>
              <button
                onClick={() => setUpdateWindowInput('Sat,Sun:00:00-23:59')}
                className="px-3 py-2 bg-tide-surface hover:bg-tide-surface border border-tide-border text-tide-text rounded-lg text-sm text-left transition-colors"
              >
                <div className="font-medium">Weekends Only</div>
                <div className="text-xs text-tide-text-muted">Sat,Sun anytime</div>
              </button>
              <button
                onClick={() => setUpdateWindowInput('Mon-Fri:22:00-06:00')}
                className="px-3 py-2 bg-tide-surface hover:bg-tide-surface border border-tide-border text-tide-text rounded-lg text-sm text-left transition-colors"
              >
                <div className="font-medium">Weeknights</div>
                <div className="text-xs text-tide-text-muted">Mon-Fri 22:00-06:00</div>
              </button>
              <button
                onClick={() => setUpdateWindowInput('Sat,Sun:02:00-10:00')}
                className="px-3 py-2 bg-tide-surface hover:bg-tide-surface border border-tide-border text-tide-text rounded-lg text-sm text-left transition-colors"
              >
                <div className="font-medium">Weekend Mornings</div>
                <div className="text-xs text-tide-text-muted">Sat,Sun 02:00-10:00</div>
              </button>
            </div>
          </div>

          {/* Save Button */}
          <button
            onClick={handleSaveUpdateWindow}
            disabled={savingSettings}
            className="w-full px-4 py-2 bg-primary hover:bg-primary/80 text-tide-text rounded-lg transition-colors disabled:opacity-50"
          >
            Save Update Window
          </button>

          {/* Format Help */}
          <div className="mt-3 text-xs text-tide-text-muted">
            <p className="font-medium mb-1">Format Examples:</p>
            <ul className="list-disc list-inside space-y-1 ml-2">
              <li>02:00-06:00 (daily window)</li>
              <li>Sat,Sun:00:00-23:59 (weekends)</li>
              <li>Mon-Fri:22:00-06:00 (crosses midnight)</li>
            </ul>
          </div>
        </div>

      </div>
    </div>
  );
}
