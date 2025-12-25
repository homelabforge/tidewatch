import { useState, useEffect, useCallback } from 'react';
import { X, Info, Activity, FileText, Clock, Settings, CircleCheckBig, RefreshCw, AlertCircle, CheckCircle2, XCircle, History, ArrowRight, RotateCw, TrendingUp, Power, Shield, Ban, Wand2, Undo2, Pause, Play, Network, Calendar, Copy, Download, ChevronDown, ChevronUp, Search, FileDown, Package, Star, ShieldAlert, Container as ContainerIcon, Server, Eye, EyeOff } from 'lucide-react';
import { Container, ContainerMetrics, UpdateHistory, RestartState, EnableRestartConfig, AppDependenciesResponse, DockerfileDependenciesResponse, HttpServersResponse, AppDependency, DockerfileDependency, HttpServer } from '../types';
import { formatDistanceToNow, format } from 'date-fns';
import { api } from '../services/api';
import { toast } from 'sonner';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import StatusBadge from './StatusBadge';
import DependencyIgnoreModal from './DependencyIgnoreModal';
import DependencyUpdatePreviewModal, { type PreviewData } from './DependencyUpdatePreviewModal';

interface ContainerModalProps {
  container: Container;
  onClose: () => void;
  onUpdate?: () => void;
}

type TabType = 'overview' | 'metrics' | 'logs' | 'history' | 'dependencies' | 'settings';

type MetricType = 'cpu' | 'memory' | 'network' | 'disk' | 'pids';

type TimePeriod = '1h' | '6h' | '24h' | '7d' | '30d';

interface MetricsHistoryDataPoint {
  timestamp: string;
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  network_rx: number;
  network_tx: number;
  block_read: number;
  block_write: number;
  pids: number;
}

export default function ContainerModal({ container, onClose, onUpdate }: ContainerModalProps) {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [metrics, setMetrics] = useState<ContainerMetrics | null>(null);
  const [loadingMetrics, setLoadingMetrics] = useState(false);
  const [selectedMetric, setSelectedMetric] = useState<MetricType | null>(null);
  const [timePeriod, setTimePeriod] = useState<TimePeriod>('24h');
  const [historyData, setHistoryData] = useState<MetricsHistoryDataPoint[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [logs, setLogs] = useState<string>('');
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [autoRefreshLogs, setAutoRefreshLogs] = useState(true);
  const [logLines, setLogLines] = useState(100);
  const [logSearchQuery, setLogSearchQuery] = useState('');
  const [followMode, setFollowMode] = useState(true);
  const [compareMetrics, setCompareMetrics] = useState(false);
  const [history, setHistory] = useState<UpdateHistory[]>([]);
  const [loadingHistory2, setLoadingHistory2] = useState(false);
  const [policy, setPolicy] = useState(container.policy);
  const [scope, setScope] = useState(container.scope);
  const [includePrereleases, setIncludePrereleases] = useState(container.include_prereleases);
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

  // App Dependencies state
  const [appDependencies, setAppDependencies] = useState<AppDependenciesResponse | null>(null);
  const [loadingAppDependencies, setLoadingAppDependencies] = useState(false);
  const [scanningAppDeps, setScanningAppDeps] = useState(false);
  const [dependencyFilter, setDependencyFilter] = useState<'all' | 'updates' | 'security'>('updates');

  // Dockerfile Dependencies state
  const [dockerfileDependencies, setDockerfileDependencies] = useState<DockerfileDependenciesResponse | null>(null);
  const [loadingDockerfileDeps, setLoadingDockerfileDeps] = useState(false);

  // HTTP Servers state
  const [httpServers, setHttpServers] = useState<HttpServersResponse | null>(null);
  const [loadingHttpServers, setLoadingHttpServers] = useState(false);

  // Dependencies sub-tab state
  const [dependenciesSubTab, setDependenciesSubTab] = useState<'infra' | 'dependencies' | 'dev-dependencies'>('infra');

  // Ignore modal state
  const [ignoreModalOpen, setIgnoreModalOpen] = useState(false);
  const [dependencyToIgnore, setDependencyToIgnore] = useState<{
    dependency: AppDependency | DockerfileDependency | HttpServer;
    type: 'app' | 'dockerfile' | 'http_server';
  } | null>(null);

  // Preview modal state
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [dependencyToPreview, setDependencyToPreview] = useState<{
    dependency: AppDependency | DockerfileDependency | HttpServer;
    type: 'app' | 'dockerfile' | 'http_server';
  } | null>(null);

  // Settings state
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

  const loadMetrics = useCallback(async () => {
    setLoadingMetrics(true);
    try {
      const data = await api.containers.getMetrics(container.id);
      setMetrics(data);
    } catch (error) {
      console.error('Failed to load metrics:', error);
      setMetrics(null);
    } finally {
      setLoadingMetrics(false);
    }
  }, [container.id]);

  const loadHistoricalData = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const response = await fetch(`/api/v1/containers/${container.id}/metrics/history?period=${timePeriod}`);
      if (!response.ok) throw new Error('Failed to fetch history');
      const data = await response.json();
      setHistoryData(data);
    } catch (error) {
      console.error('Failed to load historical data:', error);
      setHistoryData([]);
    } finally {
      setLoadingHistory(false);
    }
  }, [container.id, timePeriod]);

  const loadLogs = useCallback(async () => {
    setLoadingLogs(true);
    try {
      const data = await api.containers.getLogs(container.id, logLines);
      setLogs(data.logs.join('\n') || '');
    } catch (error) {
      console.error('Failed to load logs:', error);
      setLogs('Failed to load logs');
    } finally {
      setLoadingLogs(false);
    }
  }, [container.id, logLines]);

  useEffect(() => {
    if (activeTab === 'logs') {
      loadLogs();

      // Set up auto-refresh if enabled
      if (autoRefreshLogs) {
        const interval = setInterval(loadLogs, 2000); // Refresh every 2 seconds
        return () => clearInterval(interval);
      }
    }
  }, [activeTab, autoRefreshLogs, loadLogs]);

  const loadUpdateHistory = useCallback(async () => {
    setLoadingHistory2(true);
    try {
      const response = await fetch(`/api/v1/containers/${container.id}/details`);
      if (!response.ok) throw new Error('Failed to fetch history');
      const data = await response.json();
      console.log('History data:', data.history);
      setHistory(data.history || []);
    } catch (error) {
      console.error('Failed to load update history:', error);
      setHistory([]);
    } finally {
      setLoadingHistory2(false);
    }
  }, [container.id]);

  const saveSettings = async (updates: Record<string, unknown>) => {
    setSavingSettings(true);
    try {
      await api.containers.update(container.id, updates);
      toast.success('Settings saved successfully');
      if (onUpdate) onUpdate();
    } catch (error) {
      console.error('Failed to save settings:', error);
      toast.error('Failed to save settings');
    } finally {
      setSavingSettings(false);
    }
  };

  const handlePolicyChange = async (newPolicy: string) => {
    // Warn about auto policy (all updates including breaking changes)
    if (newPolicy === 'auto') {
      const confirmed = window.confirm(
        '⚠️ Warning: Auto Policy\n\n' +
        'The "Auto" policy will automatically apply ALL updates, including MAJOR version updates that may contain breaking changes.\n\n' +
        'Consider using:\n' +
        '• "Patch Only" - Only patch updates (safest)\n' +
        '• "Minor + Patch" - Minor and patch updates (no breaking changes)\n' +
        '• "Security Only" - Only security updates\n\n' +
        'Are you sure you want to enable the Auto policy?'
      );

      if (!confirmed) {
        return; // User cancelled
      }
    }

    setPolicy(newPolicy);
    await saveSettings({ policy: newPolicy });
  };

  const handleScopeChange = async (newScope: string) => {
    const oldScope = scope;
    setScope(newScope);
    await saveSettings({ scope: newScope });

    // Auto re-check updates if scope changed
    if (oldScope !== newScope) {
      try {
        await api.containers.recheckUpdates(container.id);
        toast.success('Updates re-checked with new scope');
        if (onUpdate) onUpdate(); // Refresh parent view
      } catch (error) {
        console.error('Failed to re-check updates:', error);
        toast.error('Failed to re-check updates');
      }
    }
  };

  const handlePrereleasesToggle = async () => {
    const newValue = !includePrereleases;
    setIncludePrereleases(newValue);
    await saveSettings({ include_prereleases: newValue });
  };

  const handleHealthCheckMethodChange = async (method: string) => {
    setHealthCheckMethod(method);
    await saveSettings({ health_check_method: method });
  };

  const handleSaveHealthCheckUrl = async () => {
    console.log('Saving health check URL:', healthCheckUrl);
    await saveSettings({ health_check_url: healthCheckUrl });
  };

  const handleSaveHealthAuth = async () => {
    console.log('Saving health check auth');
    await saveSettings({ health_check_auth: healthCheckAuth });
    setHealthCheckAuth('');
  };

  const handleSaveReleaseSource = async () => {
    console.log('Saving release source:', releaseSource);
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

  const toggleAutoRestart = async () => {
    const newValue = !autoRestartEnabled;

    try {
      if (newValue) {
        // Enable with current config
        const result = await api.restarts.enable(container.id, restartConfig);
        setRestartState(result.state);
        setAutoRestartEnabled(true);
        toast.success('Auto-restart enabled');
      } else {
        // Disable
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

  const loadAppDependencies = useCallback(async () => {
    setLoadingAppDependencies(true);
    try {
      // Always perform fresh scan to ensure up-to-date data
      try {
        await api.containers.scanAppDependencies(container.id);
      } catch {
        // Silent fail - scan might fail if no package files found
        console.log('App dependency scan skipped');
      }

      // Load the (now fresh) data
      const data = await api.containers.getAppDependencies(container.id);
      setAppDependencies(data);
    } catch (error) {
      console.error('Error loading app dependencies:', error);
      toast.error('Failed to load app dependencies');
    } finally {
      setLoadingAppDependencies(false);
    }
  }, [container.id]);

  const loadDockerfileDependencies = useCallback(async () => {
    setLoadingDockerfileDeps(true);
    try {
      // Always perform fresh scan to ensure up-to-date data
      try {
        await api.containers.scanDockerfileDependencies(container.id);
      } catch {
        // Silent fail - it's okay if there's no Dockerfile
        console.log('Dockerfile scan skipped: no Dockerfile found');
      }

      // Load the (now fresh) data
      const data = await api.containers.getDockerfileDependencies(container.id);
      setDockerfileDependencies(data);
    } catch (error) {
      console.error('Error loading Dockerfile dependencies:', error);
      // Don't show error toast - it's normal if there's no Dockerfile
      setDockerfileDependencies(null);
    } finally {
      setLoadingDockerfileDeps(false);
    }
  }, [container.id]);

  const loadHttpServers = useCallback(async () => {
    setLoadingHttpServers(true);
    try {
      // Always perform fresh scan to ensure up-to-date data
      try {
        await api.containers.scanHttpServers(container.id);
      } catch {
        // Silent fail - scan might fail if container isn't running
        console.log('HTTP server scan skipped');
      }

      // Load the (now fresh) data
      const data = await api.containers.getHttpServers(container.id);
      setHttpServers(data);
    } catch (error) {
      console.error('Error loading HTTP servers:', error);
      setHttpServers(null);
    } finally {
      setLoadingHttpServers(false);
    }
  }, [container.id]);

  // Ignore/Unignore handlers
  const handleIgnoreDependency = (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: 'app' | 'dockerfile' | 'http_server'
  ) => {
    setDependencyToIgnore({ dependency, type });
    setIgnoreModalOpen(true);
  };

  const handleConfirmIgnore = async (reason?: string) => {
    if (!dependencyToIgnore) return;

    try {
      const { dependency, type } = dependencyToIgnore;

      if (type === 'app') {
        await api.dependencies.ignoreAppDependency((dependency as AppDependency).id, reason);
        await loadAppDependencies();
        toast.success(`Ignored update for ${(dependency as AppDependency).name}`);
      } else if (type === 'dockerfile') {
        await api.dependencies.ignoreDockerfile((dependency as DockerfileDependency).id, reason);
        await loadDockerfileDependencies();
        toast.success(`Ignored update for ${(dependency as DockerfileDependency).image_name}`);
      } else if (type === 'http_server') {
        await api.dependencies.ignoreHttpServer((dependency as HttpServer).id, reason);
        await loadHttpServers();
        toast.success(`Ignored update for ${(dependency as HttpServer).name}`);
      }
    } catch (error) {
      console.error('Failed to ignore dependency:', error);
      toast.error('Failed to ignore update');
    }
  };

  const handleUnignoreDependency = async (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: 'app' | 'dockerfile' | 'http_server'
  ) => {
    try {
      if (type === 'app') {
        await api.dependencies.unignoreAppDependency((dependency as AppDependency).id);
        await loadAppDependencies();
        toast.success(`Unignored update for ${(dependency as AppDependency).name}`);
      } else if (type === 'dockerfile') {
        await api.dependencies.unignoreDockerfile((dependency as DockerfileDependency).id);
        await loadDockerfileDependencies();
        toast.success(`Unignored update for ${(dependency as DockerfileDependency).image_name}`);
      } else if (type === 'http_server') {
        await api.dependencies.unignoreHttpServer((dependency as HttpServer).id);
        await loadHttpServers();
        toast.success(`Unignored update for ${(dependency as HttpServer).name}`);
      }
    } catch (error) {
      console.error('Failed to unignore dependency:', error);
      toast.error('Failed to unignore update');
    }
  };

  // Preview and Update handlers
  const handlePreviewUpdate = (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: 'app' | 'dockerfile' | 'http_server'
  ) => {
    setDependencyToPreview({ dependency, type });
    setPreviewModalOpen(true);
  };

  const handlePreviewLoad = async (): Promise<PreviewData> => {
    if (!dependencyToPreview) throw new Error('No dependency to preview');

    const { dependency, type } = dependencyToPreview;

    if (type === 'app') {
      const dep = dependency as AppDependency;
      console.log('Preview app dependency:', { id: dep.id, name: dep.name, latest_version: dep.latest_version });
      if (!dep.id) {
        throw new Error(`Dependency ${dep.name} is missing ID field`);
      }
      return await api.dependencies.previewAppDependencyUpdate(dep.id, dep.latest_version || '');
    } else if (type === 'dockerfile') {
      const dep = dependency as DockerfileDependency;
      console.log('Preview dockerfile dependency:', { id: dep.id, image: dep.image_name, latest_tag: dep.latest_tag });
      if (!dep.id) {
        throw new Error(`Dependency ${dep.image_name} is missing ID field`);
      }
      return await api.dependencies.previewDockerfileUpdate(dep.id, dep.latest_tag || '');
    } else if (type === 'http_server') {
      const dep = dependency as HttpServer;
      console.log('Preview http server:', { id: dep.id, name: dep.name, latest_version: dep.latest_version });
      if (!dep.id) {
        throw new Error(`HTTP server ${dep.name} is missing ID field`);
      }
      return await api.dependencies.previewHttpServerUpdate(dep.id, dep.latest_version || '');
    }

    throw new Error('Invalid dependency type');
  };

  const handleDirectUpdate = async (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: 'app' | 'dockerfile' | 'http_server'
  ) => {
    try {
      if (type === 'app') {
        const dep = dependency as AppDependency;
        const newVersion = dep.latest_version || '';
        await api.dependencies.updateAppDependency(dep.id, newVersion);
        await loadAppDependencies();
        toast.success(`Updated ${dep.name} to ${newVersion}`);
      } else if (type === 'dockerfile') {
        const dep = dependency as DockerfileDependency;
        const newVersion = dep.latest_tag || '';
        await api.dependencies.updateDockerfile(dep.id, newVersion);
        await loadDockerfileDependencies();
        toast.success(`Updated ${dep.image_name} to ${newVersion}`);
      } else if (type === 'http_server') {
        const dep = dependency as HttpServer;
        const newVersion = dep.latest_version || '';
        await api.dependencies.updateHttpServer(dep.id, newVersion);
        await loadHttpServers();
        toast.success(`Updated ${dep.name} to ${newVersion}`);
      }
    } catch (error) {
      console.error('Failed to update dependency:', error);
      toast.error('Failed to update dependency');
    }
  };

  const handleConfirmUpdate = async () => {
    if (!dependencyToPreview) return;

    try {
      const { dependency, type } = dependencyToPreview;

      if (type === 'app') {
        const dep = dependency as AppDependency;
        const newVersion = dep.latest_version || '';
        await api.dependencies.updateAppDependency(dep.id, newVersion);
        await loadAppDependencies();
        toast.success(`Updated ${dep.name} to ${newVersion}`);
      } else if (type === 'dockerfile') {
        const dep = dependency as DockerfileDependency;
        const newVersion = dep.latest_tag || '';
        await api.dependencies.updateDockerfile(dep.id, newVersion);
        await loadDockerfileDependencies();
        toast.success(`Updated ${dep.image_name} to ${newVersion}`);
      } else if (type === 'http_server') {
        const dep = dependency as HttpServer;
        const newVersion = dep.latest_version || '';
        await api.dependencies.updateHttpServer(dep.id, newVersion);
        await loadHttpServers();
        toast.success(`Updated ${dep.name} to ${newVersion}`);
      }

      setPreviewModalOpen(false);
      setDependencyToPreview(null);
    } catch (error) {
      console.error('Failed to update dependency:', error);
      toast.error('Failed to update dependency');
      throw error; // Re-throw so the modal can handle the error state
    }
  };

  // useEffect hooks that depend on load functions
  useEffect(() => {
    if (activeTab === 'metrics') {
      loadMetrics();
    }
    if (activeTab === 'dependencies') {
      if (container.is_my_project) {
        loadAppDependencies();
      }
      loadDockerfileDependencies();
      loadHttpServers();
    }
  }, [activeTab, container.id, container.is_my_project, loadMetrics, loadAppDependencies, loadDockerfileDependencies, loadHttpServers]);

  useEffect(() => {
    if (selectedMetric) {
      loadHistoricalData();
    }
  }, [selectedMetric, timePeriod, container.id, loadHistoricalData]);

  useEffect(() => {
    if (activeTab === 'history') {
      loadUpdateHistory();
    }
  }, [activeTab, container.id, loadUpdateHistory]);

  useEffect(() => {
    if (activeTab === 'settings') {
      if (autoRestartEnabled) {
        loadRestartState();
      }
      loadDependencies();
      loadAllContainers();
    }
  }, [activeTab, container.id, autoRestartEnabled, loadRestartState, loadDependencies, loadAllContainers]);

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
  };

  const handleRollback = async (historyId: number) => {
    if (!confirm('Are you sure you want to rollback to the previous version? This will restart the container.')) {
      return;
    }

    try {
      await api.history.rollback(historyId);
      toast.success('Rollback initiated successfully');

      // Reload history to show updated status
      await loadUpdateHistory();

      // Trigger container refresh
      onClose();
    } catch (error) {
      console.error('Rollback error:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to rollback');
    }
  };

  const handleUnignoreFromHistory = async (item: UpdateHistory) => {
    if (!item.dependency_id || !item.dependency_type) {
      toast.error('Missing dependency information');
      return;
    }

    try {
      if (item.dependency_type === 'dockerfile') {
        await api.dependencies.unignoreDockerfile(item.dependency_id);
        await loadDockerfileDependencies();
        toast.success(`Unignored ${item.dependency_name || 'dependency'}`);
      } else if (item.dependency_type === 'http_server') {
        await api.dependencies.unignoreHttpServer(item.dependency_id);
        await loadHttpServers();
        toast.success(`Unignored ${item.dependency_name || 'dependency'}`);
      } else if (item.dependency_type === 'app_dependency') {
        await api.dependencies.unignoreAppDependency(item.dependency_id);
        await loadAppDependencies();
        toast.success(`Unignored ${item.dependency_name || 'dependency'}`);
      }

      // Reload history to show updated status
      await loadUpdateHistory();

      // Trigger parent refresh
      if (onUpdate) {
        onUpdate();
      }
    } catch (error) {
      console.error('Unignore error:', error);
      toast.error('Failed to unignore dependency');
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
  };

  // Log viewer helper functions
  const highlightLogLine = (line: string) => {
    const lowerLine = line.toLowerCase();

    if (lowerLine.includes('error')) {
      return 'text-red-400';
    } else if (lowerLine.includes('warn') || lowerLine.includes('warning')) {
      return 'text-yellow-400';
    } else if (lowerLine.includes('info')) {
      return 'text-blue-400';
    } else if (lowerLine.includes('debug')) {
      return 'text-tide-text-muted';
    }

    return 'text-tide-text';
  };

  const filterLogs = (logContent: string) => {
    if (!logSearchQuery.trim()) return logContent;

    const lines = logContent.split('\n');
    const query = logSearchQuery.toLowerCase();
    const filteredLines = lines.filter(line =>
      line.toLowerCase().includes(query)
    );

    return filteredLines.join('\n');
  };

  const copyLogsToClipboard = async () => {
    try {
      const logsToCopy = filterLogs(logs);
      await navigator.clipboard.writeText(logsToCopy);
      toast.success('Logs copied to clipboard');
    } catch (error) {
      console.error('Failed to copy logs:', error);
      toast.error('Failed to copy logs');
    }
  };

  const downloadLogs = () => {
    try {
      const logsToDownload = filterLogs(logs);
      const timestamp = format(new Date(), 'yyyy-MM-dd-HHmmss');
      const filename = `${container.name}-logs-${timestamp}.txt`;

      const blob = new Blob([logsToDownload], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast.success(`Logs downloaded as ${filename}`);
    } catch (error) {
      console.error('Failed to download logs:', error);
      toast.error('Failed to download logs');
    }
  };

  // Metrics CSV export function
  const exportMetricsToCSV = () => {
    if (historyData.length === 0) {
      toast.error('No metrics data to export');
      return;
    }

    try {
      // CSV headers
      const headers = [
        'Timestamp',
        'CPU %',
        'Memory Usage (bytes)',
        'Memory Limit (bytes)',
        'Memory %',
        'Network RX (bytes)',
        'Network TX (bytes)',
        'Block Read (bytes)',
        'Block Write (bytes)',
        'PIDs'
      ];

      // CSV rows
      const rows = historyData.map(point => [
        point.timestamp,
        point.cpu_percent,
        point.memory_usage,
        point.memory_limit,
        point.memory_percent,
        point.network_rx,
        point.network_tx,
        point.block_read,
        point.block_write,
        point.pids
      ]);

      // Combine headers and rows
      const csvContent = [
        headers.join(','),
        ...rows.map(row => row.join(','))
      ].join('\n');

      // Create and download file
      const timestamp = format(new Date(), 'yyyy-MM-dd-HHmmss');
      const filename = `${container.name}-metrics-${timePeriod}-${timestamp}.csv`;
      const blob = new Blob([csvContent], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast.success(`Metrics exported as ${filename}`);
    } catch (error) {
      console.error('Failed to export metrics:', error);
      toast.error('Failed to export metrics');
    }
  };

  const handleCheckForUpdates = async () => {
    setCheckingUpdate(true);
    try {
      const result = await api.containers.checkForUpdates(container.id);
      if (result.update) {
        toast.success(`Update found: ${result.update.to_tag}`);
      } else {
        toast.success('No updates available');
      }
      // Trigger parent refresh
      if (onUpdate) {
        onUpdate();
      }
    } catch (error) {
      toast.error('Failed to check for updates');
      console.error(error);
    } finally {
      setCheckingUpdate(false);
    }
  };

  // Helper function to render dependencies list based on type
  const renderDependenciesList = (type: 'production' | 'development' | 'optional') => {
    const filteredDeps = appDependencies?.dependencies.filter(dep => dep.dependency_type === type) || [];

    const severityColors = {
      critical: 'bg-red-500/20 text-red-400 border-red-500/30',
      high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
      medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
      low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
      info: 'bg-gray-500/20 text-tide-text-muted border-gray-500/30',
    };

    const ecosystemIcons: Record<string, string> = {
      npm: '📦',
      pypi: '🐍',
      composer: '🐘',
      cargo: '🦀',
      go: '🐹',
    };

    const updatesCount = filteredDeps.filter(dep => dep.update_available).length;
    const securityCount = filteredDeps.filter(dep => dep.security_advisories > 0).length;

    return (
      <>
        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 mb-4">
          <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
            <p className="text-sm text-tide-text-muted">Total</p>
            <p className="text-2xl font-bold text-tide-text mt-1">{filteredDeps.length}</p>
          </div>
          <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
            <p className="text-sm text-tide-text-muted">Updates Available</p>
            <p className="text-2xl font-bold text-accent mt-1">{updatesCount}</p>
          </div>
          <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
            <p className="text-sm text-tide-text-muted">Security Issues</p>
            <p className="text-2xl font-bold text-red-400 mt-1">{securityCount}</p>
          </div>
        </div>

        {/* Filters */}
        {filteredDeps.length > 0 && (
          <div className="flex gap-2 mb-3">
            <button
              onClick={() => setDependencyFilter('all')}
              className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                dependencyFilter === 'all'
                  ? 'bg-primary text-tide-text'
                  : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
              }`}
            >
              All ({filteredDeps.length})
            </button>
            <button
              onClick={() => setDependencyFilter('updates')}
              className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                dependencyFilter === 'updates'
                  ? 'bg-primary text-tide-text'
                  : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
              }`}
            >
              Updates ({updatesCount})
            </button>
            <button
              onClick={() => setDependencyFilter('security')}
              className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                dependencyFilter === 'security'
                  ? 'bg-primary text-tide-text'
                  : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
              }`}
            >
              Security ({securityCount})
            </button>
          </div>
        )}

        {/* Dependencies List */}
        {loadingAppDependencies ? (
          <div className="text-center py-12">
            <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
            <p className="text-tide-text-muted">Loading dependencies...</p>
          </div>
        ) : filteredDeps.length > 0 ? (
          <div className="space-y-2">
            {filteredDeps
              .filter((dep) => {
                if (dependencyFilter === 'updates' && !dep.update_available) return false;
                if (dependencyFilter === 'security' && dep.security_advisories === 0) return false;
                return true;
              })
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((dep) => (
                <div
                  key={`${dep.ecosystem}-${dep.name}`}
                  className="bg-tide-surface rounded-lg p-4 border border-tide-border flex items-center justify-between"
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{ecosystemIcons[dep.ecosystem] || '📦'}</span>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-tide-text font-medium">{dep.name}</p>
                        </div>
                        <p className="text-sm text-tide-text-muted">
                          {dep.ecosystem} • Current: {dep.current_version}
                          {dep.latest_version && dep.update_available && (
                            <span className="text-accent ml-2">→ {dep.latest_version}</span>
                          )}
                        </p>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {!dep.ignored && dep.update_available && (
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${severityColors[dep.severity as keyof typeof severityColors] || severityColors.info}`}>
                        {dep.severity === 'critical' && 'Critical Update'}
                        {dep.severity === 'high' && 'High Priority'}
                        {dep.severity === 'medium' && 'Major Update'}
                        {dep.severity === 'low' && 'Minor Update'}
                        {dep.severity === 'info' && 'Patch Update'}
                      </span>
                    )}
                    {!dep.ignored && !dep.update_available && dep.last_checked && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">
                        Up to date
                      </span>
                    )}
                    {dep.ignored && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-500/20 text-gray-400 border border-gray-500/30">
                        Up to date
                      </span>
                    )}
                    {dep.security_advisories > 0 && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30">
                        <ShieldAlert size={12} className="mr-1" />
                        {dep.security_advisories} {dep.security_advisories === 1 ? 'Advisory' : 'Advisories'}
                      </span>
                    )}
                    {dep.socket_score !== null && (
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          dep.socket_score >= 70
                            ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                            : dep.socket_score >= 40
                            ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                            : 'bg-red-500/20 text-red-400 border border-red-500/30'
                        }`}
                      >
                        Socket: {dep.socket_score}
                      </span>
                    )}
                    {!dep.ignored && dep.update_available && (
                      <>
                        <button
                          onClick={() => handlePreviewUpdate(dep, 'app')}
                          className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                          title="Preview update changes"
                        >
                          <Eye size={14} />
                          Preview
                        </button>
                        <button
                          onClick={() => handleDirectUpdate(dep, 'app')}
                          className="px-2.5 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary"
                          title="Update dependency immediately"
                        >
                          <Download size={14} />
                          Update
                        </button>
                        <button
                          onClick={() => handleIgnoreDependency(dep, 'app')}
                          className="px-2.5 py-1.5 bg-primary/20 hover:bg-primary/30 text-primary rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary/30"
                          title="Ignore this update"
                        >
                          <Ban size={14} />
                          Ignore
                        </button>
                      </>
                    )}
                    {dep.ignored && (
                      <button
                        onClick={() => handleUnignoreDependency(dep, 'app')}
                        className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                        title="Unignore this update"
                      >
                        <RotateCw size={14} />
                        Unignore
                      </button>
                    )}
                  </div>
                </div>
              ))}
          </div>
        ) : (
          <div className="text-center py-12 bg-tide-surface border border-tide-border rounded-lg">
            <Package className="mx-auto mb-4 text-gray-600" size={48} />
            <p className="text-tide-text-muted">No {type} dependencies found</p>
            <p className="text-sm text-tide-text-muted mt-1">
              No {type} dependencies detected in your project
            </p>
          </div>
        )}

        {/* Last Scan Info */}
        {appDependencies?.last_scan && (
          <div className="text-sm text-tide-text-muted text-center mt-4">
            Last scanned: {formatDistanceToNow(new Date(appDependencies.last_scan), { addSuffix: true })}
          </div>
        )}
      </>
    );
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
        {/* Background overlay */}
        <div className="fixed inset-0 transition-opacity bg-tide-surface/75" onClick={onClose} />

        {/* Modal panel */}
        <div className="inline-block overflow-hidden text-left align-bottom transition-all transform bg-tide-surface rounded-lg shadow-xl sm:my-8 sm:align-middle sm:max-w-6xl sm:w-full relative">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-tide-border">
            <div>
              <h2 className="text-2xl font-bold text-tide-text">{container.name}</h2>
              <p className="text-sm text-tide-text-muted mt-1">{container.image}:{container.current_tag}</p>
            </div>
            <button
              onClick={onClose}
              className="text-tide-text-muted hover:text-tide-text transition-colors"
            >
              <X className="w-6 h-6" />
            </button>
          </div>

          {/* Tabs */}
          <div className="border-b border-tide-border px-6">
            <div className="flex items-center justify-between">
              {/* Left tabs */}
              <div className="flex space-x-1">
                <button
                  onClick={() => setActiveTab('overview')}
                  className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                    activeTab === 'overview'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text'
                  }`}
                >
                  <Info size={16} />
                  Overview
                </button>
                <button
                  onClick={() => setActiveTab('metrics')}
                  className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                    activeTab === 'metrics'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text'
                  }`}
                >
                  <Activity size={16} />
                  Metrics
                </button>
                <button
                  onClick={() => setActiveTab('logs')}
                  className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                    activeTab === 'logs'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text'
                  }`}
                >
                  <FileText size={16} />
                  Logs
                </button>
                <button
                  onClick={() => setActiveTab('history')}
                  className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                    activeTab === 'history'
                      ? 'border-primary text-primary'
                      : 'border-transparent text-tide-text-muted hover:text-tide-text'
                  }`}
                >
                  <Clock size={16} />
                  History
                </button>
                {container.is_my_project && (
                  <button
                    onClick={() => setActiveTab('dependencies')}
                    className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                      activeTab === 'dependencies'
                        ? 'border-primary text-primary'
                        : 'border-transparent text-tide-text-muted hover:text-tide-text'
                    }`}
                  >
                    <Package size={16} />
                    Dependencies
                  </button>
                )}
              </div>

              {/* Right tab */}
              <button
                onClick={() => setActiveTab('settings')}
                className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 flex items-center gap-2 ${
                  activeTab === 'settings'
                    ? 'border-primary text-primary'
                    : 'border-transparent text-tide-text-muted hover:text-tide-text'
                }`}
              >
                <Settings size={16} />
                Settings
              </button>
            </div>
          </div>

          {/* Tab Content */}
          <div className="p-6 max-h-[70vh] overflow-y-auto">
            <>
              {activeTab === 'overview' && (
              <div className="space-y-6">
                {/* Status Card */}
                {container.update_available ? (
                  <div className="bg-tide-surface/50 rounded-lg p-4 border border-tide-border border-l-4 border-l-accent">
                    <div className="flex items-center gap-3">
                      <AlertCircle className="w-8 h-8 text-accent" />
                      <div>
                        <h3 className="text-lg font-semibold text-tide-text">Update Available</h3>
                        <p className="text-tide-text-muted text-sm mt-1">
                          A new version is available: {container.latest_tag || 'Unknown'}
                        </p>
                      </div>
                    </div>
                    <div className="mt-4 flex gap-2">
                      <button
                        onClick={handleCheckForUpdates}
                        disabled={checkingUpdate}
                        className="px-4 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <RefreshCw className={`w-4 h-4 ${checkingUpdate ? 'animate-spin' : ''}`} />
                        {checkingUpdate ? 'Checking...' : 'Check for Updates'}
                      </button>
                      <button
                        onClick={async () => {
                          const reason = prompt('Optional: Enter a reason for the restart');
                          try {
                            await api.restarts.manualRestart(container.id, reason || undefined);
                            toast.success('Container restarted successfully');
                            onUpdate?.();
                          } catch {
                            toast.error('Failed to restart container');
                          }
                        }}
                        className="px-4 py-2 bg-accent hover:bg-accent-dark text-tide-text rounded-lg transition-colors flex items-center gap-2"
                      >
                        <RefreshCw className="w-4 h-4" />
                        Restart
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="bg-tide-surface/50 rounded-lg p-4 border border-tide-border border-l-4 border-l-green-500">
                    <div className="flex items-center gap-3">
                      <CircleCheckBig className="w-8 h-8 text-green-500" />
                      <div>
                        <h3 className="text-lg font-semibold text-tide-text">Up to Date</h3>
                        <p className="text-tide-text-muted text-sm mt-1">This container is running the latest version.</p>
                      </div>
                    </div>
                    <div className="mt-4 flex gap-2">
                      <button
                        onClick={handleCheckForUpdates}
                        disabled={checkingUpdate}
                        className="px-4 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <RefreshCw className={`w-4 h-4 ${checkingUpdate ? 'animate-spin' : ''}`} />
                        {checkingUpdate ? 'Checking...' : 'Check for Updates'}
                      </button>
                      <button
                        onClick={async () => {
                          const reason = prompt('Optional: Enter a reason for the restart');
                          try {
                            await api.restarts.manualRestart(container.id, reason || undefined);
                            toast.success('Container restarted successfully');
                            onUpdate?.();
                          } catch {
                            toast.error('Failed to restart container');
                          }
                        }}
                        className="px-4 py-2 bg-accent hover:bg-accent-dark text-tide-text rounded-lg transition-colors flex items-center gap-2"
                      >
                        <RefreshCw className="w-4 h-4" />
                        Restart
                      </button>
                    </div>
                  </div>
                )}

                {/* Information Card */}
                <div className="bg-tide-surface/50 rounded-lg p-4 border border-tide-border">
                  <h3 className="text-lg font-semibold text-tide-text mb-4">Information</h3>
                  <div className="space-y-3">
                    <div className="flex justify-between">
                      <span className="text-tide-text-muted">Registry</span>
                      <span className="text-tide-text font-mono text-sm">{container.registry}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-tide-text-muted">Compose File</span>
                      <span className="text-tide-text font-mono text-sm truncate max-w-xs" title={container.compose_file}>
                        {container.compose_file}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-tide-text-muted">Service Name</span>
                      <span className="text-tide-text font-mono text-sm">{container.service_name}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-tide-text-muted">Last Checked</span>
                      <span className="text-tide-text text-sm">
                        {container.last_checked
                          ? formatDistanceToNow(new Date(container.last_checked), { addSuffix: true })
                          : 'Never'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'metrics' && (
              loadingMetrics ? (
                <div className="flex items-center justify-center py-12">
                  <RefreshCw className="w-8 h-8 text-primary animate-spin" />
                </div>
              ) : selectedMetric ? (
                <div>
                  {/* Back button and time period selector */}
                  <div className="mb-4 flex items-center justify-between">
                    <button
                      onClick={() => setSelectedMetric(null)}
                      className="text-primary hover:text-primary/80 transition-colors flex items-center gap-2"
                    >
                      <X className="w-4 h-4" />
                      Back to Metrics
                    </button>
                    <div className="flex gap-2">
                      {(['1h', '6h', '24h', '7d', '30d'] as TimePeriod[]).map((period) => (
                        <button
                          key={period}
                          onClick={() => setTimePeriod(period)}
                          className={`px-3 py-1 rounded-lg text-sm transition-colors ${
                            timePeriod === period
                              ? 'bg-primary text-tide-text'
                              : 'bg-tide-surface-light text-tide-text hover:bg-gray-500'
                          }`}
                        >
                          {period}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Chart view */}
                  <div className="bg-tide-surface/50 rounded-lg p-6">
                    <div className="flex items-center justify-between mb-6">
                      <h3 className="text-xl font-semibold text-tide-text capitalize">{selectedMetric} History</h3>
                      <div className="flex items-center gap-3">
                        {/* Compare metrics toggle (only for CPU/Memory) */}
                        {(selectedMetric === 'cpu' || selectedMetric === 'memory') && (
                          <button
                            onClick={() => setCompareMetrics(!compareMetrics)}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                              compareMetrics
                                ? 'bg-primary text-tide-text'
                                : 'bg-tide-surface-light text-tide-text hover:bg-gray-500'
                            }`}
                          >
                            <TrendingUp className="w-4 h-4" />
                            {compareMetrics ? 'Comparing' : 'Compare'}
                          </button>
                        )}

                        {/* Export to CSV button */}
                        <button
                          onClick={exportMetricsToCSV}
                          disabled={historyData.length === 0}
                          className="flex items-center gap-2 px-3 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50"
                        >
                          <FileDown className="w-4 h-4" />
                          Export CSV
                        </button>
                      </div>
                    </div>
                    {loadingHistory ? (
                      <div className="flex items-center justify-center h-64">
                        <RefreshCw className="w-8 h-8 text-primary animate-spin" />
                      </div>
                    ) : historyData.length === 0 ? (
                      <div className="flex items-center justify-center h-64 text-tide-text-muted">
                        <p>No historical data available yet. Data will be collected every 5 minutes.</p>
                      </div>
                    ) : (
                      <div className="h-80">
                        <ResponsiveContainer width="100%" height="100%">
                          {selectedMetric === 'cpu' && (
                            <LineChart data={historyData}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                              <XAxis
                                dataKey="timestamp"
                                stroke="#9CA3AF"
                                tickFormatter={(value) => format(new Date(value), 'HH:mm')}
                              />
                              <YAxis
                                yAxisId="left"
                                stroke="#9CA3AF"
                                label={{ value: 'CPU %', angle: -90, position: 'insideLeft', style: { fill: '#9CA3AF' } }}
                              />
                              {compareMetrics && (
                                <YAxis
                                  yAxisId="right"
                                  orientation="right"
                                  stroke="#9CA3AF"
                                  tickFormatter={(value) => formatBytes(value)}
                                  label={{ value: 'Memory (MB)', angle: 90, position: 'insideRight', style: { fill: '#9CA3AF' } }}
                                />
                              )}
                              <Tooltip
                                contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                                labelFormatter={(value) => format(new Date(value as string), 'PPpp')}
                              />
                              <Legend />
                              <Line
                                yAxisId="left"
                                type="monotone"
                                dataKey="cpu_percent"
                                stroke="#3B82F6"
                                name="CPU %"
                                strokeWidth={2}
                              />
                              {compareMetrics && (
                                <Line
                                  yAxisId="right"
                                  type="monotone"
                                  dataKey="memory_usage"
                                  stroke="#10B981"
                                  name="Memory Usage"
                                  strokeWidth={2}
                                />
                              )}
                            </LineChart>
                          )}
                          {selectedMetric === 'memory' && (
                            <LineChart data={historyData}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                              <XAxis
                                dataKey="timestamp"
                                stroke="#9CA3AF"
                                tickFormatter={(value) => format(new Date(value), 'HH:mm')}
                              />
                              <YAxis
                                yAxisId="left"
                                stroke="#9CA3AF"
                                tickFormatter={(value) => formatBytes(value)}
                                label={{ value: 'Memory (MB)', angle: -90, position: 'insideLeft', style: { fill: '#9CA3AF' } }}
                              />
                              {compareMetrics && (
                                <YAxis
                                  yAxisId="right"
                                  orientation="right"
                                  stroke="#9CA3AF"
                                  label={{ value: 'CPU %', angle: 90, position: 'insideRight', style: { fill: '#9CA3AF' } }}
                                />
                              )}
                              <Tooltip
                                contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                                labelFormatter={(value) => format(new Date(value as string), 'PPpp')}
                              />
                              <Legend />
                              <Line
                                yAxisId="left"
                                type="monotone"
                                dataKey="memory_usage"
                                stroke="#10B981"
                                name="Memory Usage"
                                strokeWidth={2}
                              />
                              {compareMetrics && (
                                <Line
                                  yAxisId="right"
                                  type="monotone"
                                  dataKey="cpu_percent"
                                  stroke="#3B82F6"
                                  name="CPU %"
                                  strokeWidth={2}
                                />
                              )}
                            </LineChart>
                          )}
                          {selectedMetric === 'network' && (
                            <LineChart data={historyData}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                              <XAxis
                                dataKey="timestamp"
                                stroke="#9CA3AF"
                                tickFormatter={(value) => format(new Date(value), 'HH:mm')}
                              />
                              <YAxis stroke="#9CA3AF" tickFormatter={(value) => formatBytes(value)} />
                              <Tooltip
                                contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                                labelFormatter={(value) => format(new Date(value as string), 'PPpp')}
                                formatter={(value, name?: string) => [formatBytes((value as number) || 0), name || '']}
                              />
                              <Legend />
                              <Line type="monotone" dataKey="network_rx" stroke="#8B5CF6" name="RX" />
                              <Line type="monotone" dataKey="network_tx" stroke="#EC4899" name="TX" />
                            </LineChart>
                          )}
                          {selectedMetric === 'disk' && (
                            <LineChart data={historyData}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                              <XAxis
                                dataKey="timestamp"
                                stroke="#9CA3AF"
                                tickFormatter={(value) => format(new Date(value), 'HH:mm')}
                              />
                              <YAxis stroke="#9CA3AF" tickFormatter={(value) => formatBytes(value)} />
                              <Tooltip
                                contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                                labelFormatter={(value) => format(new Date(value as string), 'PPpp')}
                                formatter={(value, name?: string) => [formatBytes((value as number) || 0), name || '']}
                              />
                              <Legend />
                              <Line type="monotone" dataKey="block_read" stroke="#F59E0B" name="Read" />
                              <Line type="monotone" dataKey="block_write" stroke="#EF4444" name="Write" />
                            </LineChart>
                          )}
                          {selectedMetric === 'pids' && (
                            <LineChart data={historyData}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                              <XAxis
                                dataKey="timestamp"
                                stroke="#9CA3AF"
                                tickFormatter={(value) => format(new Date(value), 'HH:mm')}
                              />
                              <YAxis stroke="#9CA3AF" />
                              <Tooltip
                                contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                                labelFormatter={(value) => format(new Date(value as string), 'PPpp')}
                                formatter={(value) => [(value as number) || 0, 'Processes']}
                              />
                              <Legend />
                              <Line type="monotone" dataKey="pids" stroke="#06B6D4" name="PIDs" />
                            </LineChart>
                          )}
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-4">
                  {/* CPU Usage */}
                  <div
                    onClick={() => setSelectedMetric('cpu')}
                    className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border"
                  >
                    <h3 className="text-lg font-semibold text-tide-text mb-4">CPU Usage</h3>
                    <div className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-tide-text-muted">Current</span>
                        <span className="text-tide-text font-mono text-sm">
                          {metrics ? `${metrics.cpu_percent.toFixed(2)}%` : 'N/A'}
                        </span>
                      </div>
                      <div className="w-full bg-tide-surface-light rounded-full h-2">
                        <div
                          className="bg-primary h-2 rounded-full transition-all"
                          style={{ width: `${metrics ? Math.min(metrics.cpu_percent, 100) : 0}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>

                  {/* Memory Usage */}
                  <div
                    onClick={() => setSelectedMetric('memory')}
                    className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border"
                  >
                    <h3 className="text-lg font-semibold text-tide-text mb-4">Memory Usage</h3>
                    <div className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-tide-text-muted">Current</span>
                        <span className="text-tide-text font-mono text-sm">
                          {metrics ? `${formatBytes(metrics.memory_usage)} / ${formatBytes(metrics.memory_limit)}` : 'N/A'}
                        </span>
                      </div>
                      <div className="w-full bg-tide-surface-light rounded-full h-2">
                        <div
                          className="bg-accent h-2 rounded-full transition-all"
                          style={{ width: `${metrics ? Math.min(metrics.memory_percent, 100) : 0}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>

                  {/* PIDs */}
                  <div
                    onClick={() => setSelectedMetric('pids')}
                    className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border"
                  >
                    <h3 className="text-lg font-semibold text-tide-text mb-4">Processes</h3>
                    <div className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-tide-text-muted">PIDs</span>
                        <span className="text-tide-text font-mono text-sm">
                          {metrics ? metrics.pids : 'N/A'}
                        </span>
                      </div>
                      <div className="text-tide-text-muted text-xs mt-2">
                        Active process count
                      </div>
                    </div>
                  </div>

                  {/* Network I/O */}
                  <div
                    onClick={() => setSelectedMetric('network')}
                    className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border"
                  >
                    <h3 className="text-lg font-semibold text-tide-text mb-4">Network I/O</h3>
                    <div className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-tide-text-muted">RX</span>
                        <span className="text-tide-text font-mono text-sm">
                          {metrics ? formatBytes(metrics.network_rx) : 'N/A'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-tide-text-muted">TX</span>
                        <span className="text-tide-text font-mono text-sm">
                          {metrics ? formatBytes(metrics.network_tx) : 'N/A'}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Block I/O */}
                  <div
                    onClick={() => setSelectedMetric('disk')}
                    className="bg-tide-surface/50 rounded-lg p-4 cursor-pointer hover:bg-tide-surface transition-colors border border-tide-border"
                  >
                    <h3 className="text-lg font-semibold text-tide-text mb-4">Block I/O</h3>
                    <div className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-tide-text-muted">Read</span>
                        <span className="text-tide-text font-mono text-sm">
                          {metrics ? formatBytes(metrics.block_read) : 'N/A'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-tide-text-muted">Write</span>
                        <span className="text-tide-text font-mono text-sm">
                          {metrics ? formatBytes(metrics.block_write) : 'N/A'}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )
            )}

            {activeTab === 'logs' && (
              <div className="flex flex-col h-full">
                {/* Logs Header with Controls */}
                <div className="flex flex-col gap-3 mb-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold text-tide-text">Container Logs</h3>
                    <div className="flex items-center gap-2">
                      {/* Lines selector */}
                      <div className="flex items-center gap-2">
                        <label className="text-sm text-tide-text-muted">Lines:</label>
                        <select
                          value={logLines}
                          onChange={(e) => setLogLines(Number(e.target.value))}
                          className="bg-tide-surface text-tide-text text-sm rounded-lg px-3 py-1 border border-tide-border-light focus:outline-none focus:ring-2 focus:ring-primary"
                        >
                          <option value={100}>100</option>
                          <option value={500}>500</option>
                          <option value={1000}>1000</option>
                          <option value={10000}>All</option>
                        </select>
                      </div>

                      {/* Auto-refresh toggle */}
                      <button
                        onClick={() => setAutoRefreshLogs(!autoRefreshLogs)}
                        className={`flex items-center gap-2 px-3 py-1 rounded-lg text-sm transition-colors ${
                          autoRefreshLogs
                            ? 'bg-primary text-tide-text'
                            : 'bg-tide-surface-light text-tide-text hover:bg-gray-500'
                        }`}
                      >
                        <RefreshCw className={`w-4 h-4 ${autoRefreshLogs && loadingLogs ? 'animate-spin' : ''}`} />
                        {autoRefreshLogs ? 'Live' : 'Paused'}
                      </button>

                      {/* Manual refresh button */}
                      <button
                        onClick={loadLogs}
                        disabled={loadingLogs}
                        className="px-3 py-1 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50"
                      >
                        Refresh
                      </button>
                    </div>
                  </div>

                  {/* Search and Action Buttons */}
                  <div className="flex items-center gap-2">
                    {/* Search input */}
                    <div className="flex-1 relative">
                      <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-tide-text-muted" />
                      <input
                        type="text"
                        placeholder="Search logs..."
                        value={logSearchQuery}
                        onChange={(e) => setLogSearchQuery(e.target.value)}
                        className="w-full pl-10 pr-3 py-2 bg-tide-surface border border-tide-border text-tide-text rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                      />
                    </div>

                    {/* Action buttons */}
                    <button
                      onClick={copyLogsToClipboard}
                      disabled={!logs}
                      className="flex items-center gap-2 px-3 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50"
                      title="Copy to clipboard"
                    >
                      <Copy className="w-4 h-4" />
                      Copy
                    </button>

                    <button
                      onClick={downloadLogs}
                      disabled={!logs}
                      className="flex items-center gap-2 px-3 py-2 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50"
                      title="Download as .txt file"
                    >
                      <Download className="w-4 h-4" />
                      Download
                    </button>

                    <button
                      onClick={() => setFollowMode(!followMode)}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                        followMode
                          ? 'bg-primary text-tide-text'
                          : 'bg-tide-surface-light text-tide-text hover:bg-gray-500'
                      }`}
                      title={followMode ? 'Auto-scroll enabled' : 'Auto-scroll disabled'}
                    >
                      {followMode ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
                      Follow
                    </button>
                  </div>
                </div>

                {/* Logs Content */}
                <div className="flex-1 bg-tide-surface rounded-lg p-4 overflow-auto font-mono text-xs">
                  {loadingLogs && !logs ? (
                    <div className="flex items-center justify-center h-full">
                      <RefreshCw className="w-8 h-8 text-primary animate-spin" />
                    </div>
                  ) : logs ? (
                    <div className="whitespace-pre-wrap break-words">
                      {filterLogs(logs).split('\n').map((line, index) => (
                        <div key={index} className={highlightLogLine(line)}>
                          {line}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="flex items-center justify-center h-full text-tide-text-muted">
                      No logs available
                    </div>
                  )}
                </div>

                {/* Info footer */}
                <div className="mt-2 flex items-center justify-between text-xs text-tide-text-muted">
                  <span>
                    {autoRefreshLogs && 'Auto-refreshing every 2 seconds'}
                    {!autoRefreshLogs && 'Auto-refresh paused'}
                    {logSearchQuery && ` • Filtering by: "${logSearchQuery}"`}
                  </span>
                  <span>
                    {followMode && 'Auto-scroll enabled'}
                  </span>
                </div>
              </div>
            )}

            {activeTab === 'history' && (
              <div>
                <div className="flex items-center justify-between mb-6">
                  <h3 className="text-lg font-semibold text-tide-text">Update History</h3>
                  <button
                    onClick={loadUpdateHistory}
                    disabled={loadingHistory2}
                    className="px-3 py-1 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50 flex items-center gap-2"
                  >
                    <RefreshCw className={`w-4 h-4 ${loadingHistory2 ? 'animate-spin' : ''}`} />
                    Refresh
                  </button>
                </div>

                {loadingHistory2 ? (
                  <div className="flex items-center justify-center py-12">
                    <RefreshCw className="w-8 h-8 text-primary animate-spin" />
                  </div>
                ) : history.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-tide-text-muted">
                    <History className="w-12 h-12 mb-3 opacity-50" />
                    <p>No update history available for this container</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {history.map((item) => (
                      <div
                        key={item.id}
                        className="bg-tide-surface/50 rounded-lg p-4 border border-tide-border border-l-4"
                        style={{
                          borderLeftColor:
                            item.status === 'completed' ? '#10B981' :
                            item.status === 'failed' ? '#EF4444' :
                            item.status === 'rolled_back' ? '#F59E0B' : '#6B7280'
                        }}
                      >
                        {/* Header with status */}
                        <div className="flex items-start justify-between mb-3">
                          <div className="flex items-center gap-3">
                            {item.event_type === 'dependency_ignore' && (
                              <EyeOff className="w-5 h-5 text-gray-400 flex-shrink-0" />
                            )}
                            {item.event_type === 'dependency_unignore' && (
                              <Eye className="w-5 h-5 text-teal-400 flex-shrink-0" />
                            )}
                            {item.status === 'completed' && !item.event_type?.includes('dependency') && (
                              <CheckCircle2 className="w-5 h-5 text-green-500 flex-shrink-0" />
                            )}
                            {item.status === 'failed' && !item.event_type?.includes('dependency') && (
                              <XCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                            )}
                            {item.status === 'rolled_back' && (
                              <AlertCircle className="w-5 h-5 text-yellow-500 flex-shrink-0" />
                            )}
                            <div>
                              {item.event_type === 'dependency_ignore' || item.event_type === 'dependency_unignore' ? (
                                <div className="text-tide-text font-medium">
                                  <div className="flex items-center gap-2">
                                    <span className="text-sm font-semibold">{item.dependency_name}</span>
                                    <span className="font-mono text-xs text-tide-text-muted">{item.from_tag}</span>
                                    <ArrowRight className="w-3 h-3 text-tide-text-muted" />
                                    <span className="font-mono text-xs text-primary">{item.to_tag}</span>
                                  </div>
                                  <p className="text-xs text-tide-text-muted mt-1">
                                    {item.event_type === 'dependency_ignore' ? 'Ignored' : 'Unignored'}
                                    {' • '}
                                    {item.dependency_type === 'dockerfile' && 'Dockerfile dependency'}
                                    {item.dependency_type === 'http_server' && 'HTTP server'}
                                    {item.dependency_type === 'app_dependency' && 'App dependency'}
                                  </p>
                                </div>
                              ) : item.event_type === 'dependency_update' ? (
                                <div className="text-tide-text font-medium">
                                  <div className="flex items-center gap-2">
                                    <span className="text-sm font-semibold">{item.dependency_name}</span>
                                    <span className="font-mono text-xs text-tide-text-muted">{item.from_tag}</span>
                                    <ArrowRight className="w-3 h-3 text-tide-text-muted" />
                                    <span className="font-mono text-xs text-primary">{item.to_tag}</span>
                                  </div>
                                  <p className="text-xs text-tide-text-muted mt-1">
                                    {item.dependency_type === 'dockerfile' && 'Dockerfile dependency'}
                                    {item.dependency_type === 'http_server' && 'HTTP server'}
                                    {item.dependency_type === 'app_dependency' && 'App dependency'}
                                  </p>
                                </div>
                              ) : (
                                <div className="flex items-center gap-2 text-tide-text font-medium">
                                  <span className="font-mono text-sm">{item.from_tag}</span>
                                  <ArrowRight className="w-4 h-4 text-tide-text-muted" />
                                  <span className="font-mono text-sm">{item.to_tag}</span>
                                </div>
                              )}
                              <p className="text-xs text-tide-text-muted mt-1">
                                {formatDistanceToNow(new Date(item.started_at), { addSuffix: true })}
                              </p>
                            </div>
                          </div>
                          <div className="flex flex-col items-end gap-2">
                            <div className="flex items-center gap-2">
                              <StatusBadge status={item.status} event_type={item.event_type || undefined} />
                              {item.event_type === 'dependency_ignore' && (
                                <button
                                  onClick={() => handleUnignoreFromHistory(item)}
                                  className="flex items-center gap-1.5 px-2.5 py-1 bg-teal-500/10 hover:bg-teal-500/20 text-teal-500 rounded-lg transition-colors text-xs"
                                >
                                  <RefreshCw className="w-3.5 h-3.5" />
                                  Unignore
                                </button>
                              )}
                              {item.can_rollback && (item.status === 'completed' || item.status === 'success') && !item.rolled_back_at && !item.event_type?.includes('dependency') && (
                                <button
                                  onClick={() => handleRollback(item.id)}
                                  className="flex items-center gap-1.5 px-2.5 py-1 bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-500 rounded-lg transition-colors text-xs"
                                >
                                  <Undo2 className="w-3.5 h-3.5" />
                                  Rollback
                                </button>
                              )}
                            </div>
                            {item.duration_seconds !== null && (
                              <span className="text-xs text-tide-text-muted">
                                {item.duration_seconds < 60
                                  ? `${item.duration_seconds}s`
                                  : `${Math.floor(item.duration_seconds / 60)}m ${item.duration_seconds % 60}s`}
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Details grid */}
                        <div className="grid grid-cols-2 gap-4 text-sm mt-3 pt-3 border-t border-tide-border-light">
                          {item.reason_summary && (
                            <div className="col-span-2">
                              <span className="text-tide-text-muted">Reason:</span>
                              <span className="text-tide-text ml-2">{item.reason_summary}</span>
                            </div>
                          )}
                          {item.triggered_by && (
                            <div>
                              <span className="text-tide-text-muted">Triggered by:</span>
                              <span className="text-tide-text ml-2">{item.triggered_by}</span>
                            </div>
                          )}
                          {item.update_type && (
                            <div>
                              <span className="text-tide-text-muted">Type:</span>
                              <span className="text-tide-text ml-2">{item.update_type}</span>
                            </div>
                          )}
                          {item.cves_fixed && item.cves_fixed.length > 0 && (
                            <div className="col-span-2">
                              <span className="text-tide-text-muted">CVEs Fixed:</span>
                              <div className="flex flex-wrap gap-1 mt-1">
                                {item.cves_fixed.map((cve) => (
                                  <span key={cve} className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs font-mono">
                                    {cve}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {item.error_message && (
                            <div className="col-span-2">
                              <span className="text-tide-text-muted">Error:</span>
                              <p className="text-red-400 text-xs mt-1 font-mono bg-red-500/10 p-2 rounded">
                                {item.error_message}
                              </p>
                            </div>
                          )}
                          {item.rolled_back_at && (
                            <div className="col-span-2">
                              <span className="text-tide-text-muted">Rolled back:</span>
                              <span className="text-yellow-400 ml-2">
                                {formatDistanceToNow(new Date(item.rolled_back_at), { addSuffix: true })}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'dependencies' && (
              <div>
                {/* Sub-tabs for Dependencies */}
                <div className="flex gap-2 mb-6 border-b border-tide-border">
                  <button
                    onClick={() => setDependenciesSubTab('infra')}
                    className={`px-4 py-3 font-medium transition-colors relative ${
                      dependenciesSubTab === 'infra'
                        ? 'text-primary'
                        : 'text-tide-text-muted hover:text-tide-text'
                    }`}
                  >
                    HTTP Server & Dockerfile
                    {dependenciesSubTab === 'infra' && (
                      <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"></div>
                    )}
                  </button>
                  <button
                    onClick={() => setDependenciesSubTab('dependencies')}
                    className={`px-4 py-3 font-medium transition-colors relative ${
                      dependenciesSubTab === 'dependencies'
                        ? 'text-primary'
                        : 'text-tide-text-muted hover:text-tide-text'
                    }`}
                  >
                    Dependencies
                    {dependenciesSubTab === 'dependencies' && (
                      <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"></div>
                    )}
                  </button>
                  <button
                    onClick={() => setDependenciesSubTab('dev-dependencies')}
                    className={`px-4 py-3 font-medium transition-colors relative ${
                      dependenciesSubTab === 'dev-dependencies'
                        ? 'text-primary'
                        : 'text-tide-text-muted hover:text-tide-text'
                    }`}
                  >
                    Dev Dependencies
                    {dependenciesSubTab === 'dev-dependencies' && (
                      <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"></div>
                    )}
                  </button>
                </div>

                {/* Sub-tab Content */}
                <>
                  {/* Infrastructure Tab - HTTP Server & Dockerfile */}
                  {dependenciesSubTab === 'infra' && (
                    <div className="space-y-6">
                  {/* HTTP Servers Section */}
                  <div>
                    <div className="mb-4 flex items-start justify-between">
                      <div>
                        <h3 className="text-xl font-semibold text-tide-text">HTTP Servers</h3>
                        <p className="text-sm text-tide-text-muted mt-1">
                          Detected HTTP servers running in the container with version information.
                        </p>
                      </div>
                      <button
                        onClick={async () => {
                          setLoadingHttpServers(true);
                          try {
                            await api.containers.scanHttpServers(container.id);
                            await loadHttpServers();
                            toast.success('HTTP servers rescanned successfully');
                          } catch {
                            toast.error('Failed to rescan HTTP servers');
                          } finally {
                            setLoadingHttpServers(false);
                          }
                        }}
                        disabled={loadingHttpServers}
                        className="px-3 py-1.5 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2 text-sm"
                      >
                        <RefreshCw size={14} className={loadingHttpServers ? 'animate-spin' : ''} />
                        Rescan
                      </button>
                    </div>

                    {/* HTTP Servers Content */}
                    {loadingHttpServers ? (
                      <div className="text-center py-12 bg-tide-surface border border-tide-border rounded-lg">
                        <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
                        <p className="text-tide-text-muted">Scanning for HTTP servers...</p>
                      </div>
                    ) : httpServers && httpServers.servers.length > 0 ? (
                      <>
                        {/* Stats */}
                        <div className="grid grid-cols-2 gap-4 mb-4">
                          <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
                            <p className="text-sm text-tide-text-muted">Total Servers</p>
                            <p className="text-2xl font-bold text-tide-text mt-1">{httpServers.total}</p>
                          </div>
                          <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
                            <p className="text-sm text-tide-text-muted">Updates Available</p>
                            <p className="text-2xl font-bold text-accent mt-1">{httpServers.with_updates}</p>
                          </div>
                        </div>

                        {/* Servers List */}
                        <div className="space-y-2">
                          {httpServers.servers.map((server, index) => {
                            const severityColors = {
                              critical: 'bg-red-500/20 text-red-400 border-red-500/30',
                              high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
                              medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
                              low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
                              info: 'bg-gray-500/20 text-tide-text-muted border-gray-500/30',
                            };

                            return (
                              <div
                                key={`${server.name}-${index}`}
                                className="bg-tide-surface rounded-lg p-4 border border-tide-border"
                              >
                                <div className="flex items-start justify-between">
                                  <div className="flex-1">
                                    <div className="flex items-center gap-3">
                                      <Server size={20} className="text-primary" />
                                      <div>
                                        <p className="text-tide-text font-medium capitalize">{server.name}</p>
                                        <p className="text-sm text-tide-text-muted">
                                          {server.current_version ? `v${server.current_version}` : 'Version unknown'}
                                          {server.latest_version && server.update_available && (
                                            <span className="text-accent ml-2">→ v{server.latest_version}</span>
                                          )}
                                        </p>
                                        <p className="text-xs text-tide-text-muted mt-1">
                                          Detected via {server.detection_method === 'version_command' ? 'version command' : 'process scan'}
                                        </p>
                                      </div>
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    {!server.ignored && server.update_available && (
                                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${severityColors[server.severity]}`}>
                                        {server.severity === 'critical' && 'Critical Update'}
                                        {server.severity === 'high' && 'High Priority'}
                                        {server.severity === 'medium' && 'Major Update'}
                                        {server.severity === 'low' && 'Minor Update'}
                                        {server.severity === 'info' && 'Patch Update'}
                                      </span>
                                    )}
                                    {!server.ignored && !server.update_available && server.current_version && (
                                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">
                                        Up to date
                                      </span>
                                    )}
                                    {server.ignored && (
                                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-500/20 text-gray-400 border border-gray-500/30">
                                        Up to date
                                      </span>
                                    )}
                                    {!server.ignored && server.update_available && (
                                      <>
                                        <button
                                          onClick={() => handlePreviewUpdate(server, 'http_server')}
                                          className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                                          title="Preview update changes"
                                        >
                                          <Eye size={14} />
                                          Preview
                                        </button>
                                        <button
                                          onClick={() => handleDirectUpdate(server, 'http_server')}
                                          className="px-2.5 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary"
                                          title="Update HTTP server immediately"
                                        >
                                          <Download size={14} />
                                          Update
                                        </button>
                                        <button
                                          onClick={() => handleIgnoreDependency(server, 'http_server')}
                                          className="px-2.5 py-1.5 bg-primary/20 hover:bg-primary/30 text-primary rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary/30"
                                          title="Ignore this update"
                                        >
                                          <Ban size={14} />
                                          Ignore
                                        </button>
                                      </>
                                    )}
                                    {server.ignored && (
                                      <button
                                        onClick={() => handleUnignoreDependency(server, 'http_server')}
                                        className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                                        title="Unignore this update"
                                      >
                                        <RotateCw size={14} />
                                        Unignore
                                      </button>
                                    )}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>

                        {httpServers.last_scan && (
                          <div className="text-sm text-tide-text-muted text-center mt-4">
                            Last scanned: {formatDistanceToNow(new Date(httpServers.last_scan), { addSuffix: true })}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="text-center py-12 bg-tide-surface border border-tide-border rounded-lg">
                        <Server className="mx-auto mb-4 text-gray-600" size={48} />
                        <p className="text-tide-text-muted">No HTTP servers detected</p>
                        <p className="text-sm text-tide-text-muted mt-1">
                          Container may not be running or doesn't contain common HTTP servers
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Dockerfile Dependencies Section */}
                  <div>
                  <div className="mb-4 flex items-start justify-between">
                    <div>
                      <h3 className="text-xl font-semibold text-tide-text">Dockerfile Dependencies</h3>
                      <p className="text-sm text-tide-text-muted mt-1">
                        Base and build images used in your Dockerfile. Dependencies are scanned automatically when you open this tab.
                      </p>
                    </div>
                    <button
                      onClick={async () => {
                        setLoadingDockerfileDeps(true);
                        try {
                          await api.containers.scanDockerfileDependencies(container.id);
                          await loadDockerfileDependencies();
                          toast.success('Dockerfile dependencies rescanned successfully');
                        } catch {
                          toast.error('Failed to rescan Dockerfile dependencies');
                        } finally {
                          setLoadingDockerfileDeps(false);
                        }
                      }}
                      disabled={loadingDockerfileDeps}
                      className="px-3 py-1.5 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2 text-sm"
                    >
                      <RefreshCw size={14} className={loadingDockerfileDeps ? 'animate-spin' : ''} />
                      Rescan
                    </button>
                  </div>

                  {/* Stats */}
                  {dockerfileDependencies && dockerfileDependencies.dependencies.length > 0 && (
                    <div className="grid grid-cols-2 gap-4 mb-6">
                      <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
                        <p className="text-sm text-tide-text-muted">Total Images</p>
                        <p className="text-2xl font-bold text-tide-text mt-1">{dockerfileDependencies.total}</p>
                      </div>
                      <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
                        <p className="text-sm text-tide-text-muted">Updates Available</p>
                        <p className="text-2xl font-bold text-accent mt-1">{dockerfileDependencies.with_updates}</p>
                      </div>
                    </div>
                  )}

                  {/* Dependencies List */}
                  {loadingDockerfileDeps ? (
                    <div className="text-center py-12">
                      <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
                      <p className="text-tide-text-muted">Loading Dockerfile dependencies...</p>
                    </div>
                  ) : dockerfileDependencies && dockerfileDependencies.dependencies.length > 0 ? (
                    <div className="space-y-2">
                      {[...dockerfileDependencies.dependencies]
                        .sort((a, b) => a.image_name.localeCompare(b.image_name))
                        .map((dep) => (
                        <div
                          key={dep.id}
                          className="bg-tide-surface rounded-lg p-4 border border-tide-border"
                        >
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <div className="flex items-center gap-3">
                                <ContainerIcon size={20} className="text-primary" />
                                <div>
                                  <p className="text-tide-text font-medium">{dep.image_name}</p>
                                  <p className="text-sm text-tide-text-muted">
                                    {dep.dependency_type === 'base_image' ? 'Base Image' : 'Build Image'}
                                    {dep.stage_name && ` • Stage: ${dep.stage_name}`}
                                    {' • '}Current: {dep.current_tag}
                                    {dep.latest_tag && dep.update_available && (
                                      <span className="text-accent ml-2">→ {dep.latest_tag}</span>
                                    )}
                                  </p>
                                  <p className="text-xs text-tide-text-muted mt-1">
                                    {dep.dockerfile_path}
                                    {dep.line_number && ` (line ${dep.line_number})`}
                                  </p>
                                </div>
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              {!dep.ignored && dep.update_available && (() => {
                                const severityColors = {
                                  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
                                  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
                                  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
                                  low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
                                  info: 'bg-gray-500/20 text-tide-text-muted border-gray-500/30',
                                };
                                return (
                                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${severityColors[dep.severity as keyof typeof severityColors] || severityColors.info}`}>
                                    {dep.severity === 'critical' && 'Critical Update'}
                                    {dep.severity === 'high' && 'High Priority'}
                                    {dep.severity === 'medium' && 'Major Update'}
                                    {dep.severity === 'low' && 'Minor Update'}
                                    {dep.severity === 'info' && 'Patch Update'}
                                  </span>
                                );
                              })()}
                              {!dep.ignored && !dep.update_available && dep.last_checked && (
                                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">
                                  Up to date
                                </span>
                              )}
                              {dep.ignored && (
                                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-500/20 text-gray-400 border border-gray-500/30">
                                  Up to date
                                </span>
                              )}
                              {!dep.ignored && dep.update_available && (
                                <>
                                  <button
                                    onClick={() => handlePreviewUpdate(dep, 'dockerfile')}
                                    className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                                    title="Preview update changes"
                                  >
                                    <Eye size={14} />
                                    Preview
                                  </button>
                                  <button
                                    onClick={() => handleDirectUpdate(dep, 'dockerfile')}
                                    className="px-2.5 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary"
                                    title="Update Dockerfile immediately"
                                  >
                                    <Download size={14} />
                                    Update
                                  </button>
                                  <button
                                    onClick={() => handleIgnoreDependency(dep, 'dockerfile')}
                                    className="px-2.5 py-1.5 bg-primary/20 hover:bg-primary/30 text-primary rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary/30"
                                    title="Ignore this update"
                                  >
                                    <Ban size={14} />
                                    Ignore
                                  </button>
                                </>
                              )}
                              {dep.ignored && (
                                <button
                                  onClick={() => handleUnignoreDependency(dep, 'dockerfile')}
                                  className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                                  title="Unignore this update"
                                >
                                  <RotateCw size={14} />
                                  Unignore
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-12 bg-tide-surface border border-tide-border rounded-lg">
                      <FileText className="mx-auto mb-4 text-gray-600" size={48} />
                      <p className="text-tide-text-muted">No Dockerfile found</p>
                      <p className="text-sm text-tide-text-muted mt-1">
                        Click "Scan Dockerfile" to detect base and build images if a Dockerfile exists
                      </p>
                    </div>
                  )}

                  {/* Last Scan Info */}
                  {dockerfileDependencies?.last_scan && (
                    <div className="text-sm text-tide-text-muted text-center mt-4">
                      Last scanned: {formatDistanceToNow(new Date(dockerfileDependencies.last_scan), { addSuffix: true })}
                    </div>
                  )}
                  </div>
                </div>
                  )}

                {/* Dependencies Tab - Production Dependencies */}
                {dependenciesSubTab === 'dependencies' && (
                  <div>
                    <div className="mb-4 flex items-start justify-between">
                      <div>
                        <h3 className="text-xl font-semibold text-tide-text">Production Dependencies</h3>
                        <p className="text-sm text-tide-text-muted mt-1">
                          Track production dependencies used by your application and available updates.
                        </p>
                      </div>
                      <button
                        onClick={async () => {
                          setScanningAppDeps(true);
                          try {
                            await api.containers.scanAppDependencies(container.id);
                            await loadAppDependencies();
                            toast.success('Dependencies rescanned successfully');
                          } catch {
                            toast.error('Failed to rescan dependencies');
                          } finally {
                            setScanningAppDeps(false);
                          }
                        }}
                        disabled={scanningAppDeps || loadingAppDependencies}
                        className="px-3 py-1.5 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2 text-sm"
                      >
                        <RefreshCw size={14} className={scanningAppDeps ? 'animate-spin' : ''} />
                        Rescan
                      </button>
                    </div>

                    {renderDependenciesList('production')}
                  </div>
                )}

                {/* Dev Dependencies Tab */}
                {dependenciesSubTab === 'dev-dependencies' && (
                  <div>
                    <div className="mb-4 flex items-start justify-between">
                      <div>
                        <h3 className="text-xl font-semibold text-tide-text">Development Dependencies</h3>
                        <p className="text-sm text-tide-text-muted mt-1">
                          Track development dependencies used during build and test processes.
                        </p>
                      </div>
                      <button
                        onClick={async () => {
                          setScanningAppDeps(true);
                          try {
                            await api.containers.scanAppDependencies(container.id);
                            await loadAppDependencies();
                            toast.success('Dependencies rescanned successfully');
                          } catch {
                            toast.error('Failed to rescan dependencies');
                          } finally {
                            setScanningAppDeps(false);
                          }
                        }}
                        disabled={scanningAppDeps || loadingAppDependencies}
                        className="px-3 py-1.5 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2 text-sm"
                      >
                        <RefreshCw size={14} className={scanningAppDeps ? 'animate-spin' : ''} />
                        Rescan
                      </button>
                    </div>

                    {renderDependenciesList('development')}
                  </div>
                )}

                </>
              </div>
            )}

            {activeTab === 'settings' && (
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
                          {/* Strategy */}
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

                          {/* Max Attempts */}
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

                          {/* Base Delay */}
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

                          {/* Max Delay */}
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

                          {/* Success Window */}
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

                          {/* Health Check Options */}
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

                          {/* Rollback on Health Fail */}
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

                          {/* Save Configuration Button */}
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
                <div className="bg-tide-surface/50 rounded-lg p-6">
                  <h4 className="text-base font-semibold text-tide-text mb-3">Update Policy</h4>
                  <p className="text-sm text-tide-text-muted mb-4">Choose how updates should be handled for this container.</p>
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      { value: 'patch-only', label: 'Patch Only', desc: 'Auto-apply patch updates (1.2.3 → 1.2.4)', icon: CheckCircle2 },
                      { value: 'minor-and-patch', label: 'Minor + Patch', desc: 'Auto-apply minor/patch (no breaking)', icon: TrendingUp },
                      { value: 'auto', label: 'Auto (⚠️ All)', desc: 'ALL updates (including breaking)', icon: AlertCircle },
                      { value: 'security', label: 'Security Only', desc: 'Auto-apply security updates', icon: Shield },
                      { value: 'manual', label: 'Manual', desc: 'Require manual approval', icon: Power },
                      { value: 'disabled', label: 'Disabled', desc: 'No automatic checks', icon: Ban }
                    ].map((item) => (
                      <button
                        key={item.value}
                        onClick={() => handlePolicyChange(item.value)}
                        disabled={savingSettings}
                        className={`p-4 rounded-lg border-2 transition-all text-left ${
                          policy === item.value
                            ? 'border-primary bg-primary/10'
                            : 'border-tide-border bg-tide-surface hover:border-tide-border-light'
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <item.icon className={`w-5 h-5 ${policy === item.value ? 'text-primary' : 'text-tide-text-muted'}`} />
                          <span className={`font-medium ${policy === item.value ? 'text-tide-text' : 'text-tide-text'}`}>{item.label}</span>
                        </div>
                        <p className="text-xs text-tide-text-muted">{item.desc}</p>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Version Scope */}
                <div className="bg-tide-surface/50 rounded-lg p-6">
                  <h4 className="text-base font-semibold text-tide-text mb-3">Version Scope</h4>
                  <p className="text-sm text-tide-text-muted mb-4">Control which version changes are allowed during updates.</p>
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { value: 'patch', label: 'Patch', desc: 'Only patch updates (1.2.3 → 1.2.4)' },
                      { value: 'minor', label: 'Minor', desc: 'Minor + patch (1.2.x → 1.3.x)' },
                      { value: 'major', label: 'Major', desc: 'All updates (1.x.x → 2.x.x)' }
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
                <div className="bg-tide-surface/50 rounded-lg p-6">
                  <h4 className="text-base font-semibold text-tide-text mb-3">Pre-release Versions</h4>
                  <p className="text-sm text-tide-text-muted mb-4">Control whether to include pre-release tags when checking for updates.</p>
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-tide-text">Include Pre-releases</p>
                      <p className="text-xs text-tide-text-muted mt-1">{includePrereleases ? 'Including pre-releases' : 'Stable releases only'}</p>
                    </div>
                    <button
                      onClick={handlePrereleasesToggle}
                      disabled={savingSettings}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        includePrereleases ? 'bg-primary' : 'bg-tide-surface-light'
                      }`}
                    >
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        includePrereleases ? 'translate-x-6' : 'translate-x-1'
                      }`} />
                    </button>
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
            )}
            </>
          </div>
        </div>
      </div>

      {/* Dependency Ignore Modal */}
      {ignoreModalOpen && dependencyToIgnore && (
        <DependencyIgnoreModal
          dependency={dependencyToIgnore.dependency}
          dependencyType={dependencyToIgnore.type}
          onClose={() => {
            setIgnoreModalOpen(false);
            setDependencyToIgnore(null);
          }}
          onConfirm={handleConfirmIgnore}
        />
      )}

      {/* Dependency Update Preview Modal */}
      {previewModalOpen && dependencyToPreview && (
        <DependencyUpdatePreviewModal
          dependency={dependencyToPreview.dependency}
          dependencyType={dependencyToPreview.type}
          onClose={() => {
            setPreviewModalOpen(false);
            setDependencyToPreview(null);
          }}
          onConfirmUpdate={handleConfirmUpdate}
          onPreview={handlePreviewLoad}
        />
      )}
    </div>
  );
}
