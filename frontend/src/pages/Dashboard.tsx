import { useState, useEffect, useMemo, useCallback, lazy, Suspense } from 'react';
import { Container, Update, FilterOptions, SortOption, AnalyticsSummary } from '../types';
import { api } from '../services/api';
import ContainerCard from '../components/ContainerCard';
import CheckProgressBar, { CheckJobState } from '../components/CheckProgressBar';
import { useEventStream, CheckJobProgressEvent } from '../hooks/useEventStream';
import { Search, RefreshCw, Package, Archive } from 'lucide-react';
import { toast } from 'sonner';

// Lazy load the large ContainerModal component
const ContainerModal = lazy(() => import('../components/ContainerModal'));

export default function Dashboard() {
  const [containers, setContainers] = useState<Container[]>([]);
  const [updates, setUpdates] = useState<Update[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [checkingUpdates, setCheckingUpdates] = useState(false);
  const [selectedContainer, setSelectedContainer] = useState<Container | null>(null);
  const [vulnforgeEnabled, setVulnforgeEnabled] = useState(false);
  const [filters, setFilters] = useState<FilterOptions>({
    search: '',
    status: 'all',
    autoUpdate: 'all',
    hasUpdate: 'all',
  });
  const [sort] = useState<SortOption>({ field: 'name', direction: 'asc' });

  // Track check job state for progress bar
  const [checkJob, setCheckJob] = useState<CheckJobState | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [containersData, updatesData, analyticsData, settingsData] = await Promise.all([
        api.containers.getAll(),
        api.updates.getAll(),
        api.analytics.getSummary(30),
        api.settings.getAll(),
      ]);
      setContainers(containersData);
      setUpdates(updatesData);
      setAnalytics(analyticsData);

      // Check if VulnForge is enabled globally
      const vulnforgeSetting = settingsData.find((s) => s.key === 'vulnforge_enabled');
      setVulnforgeEnabled(vulnforgeSetting?.value === 'true');
    } catch {
      toast.error('Failed to load data');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleScan = useCallback(async () => {
    setScanning(true);
    try {
      const result = await api.containers.sync();
      toast.success(`Synced ${result.containers_found} containers: ${result.stats.added} added, ${result.stats.updated} updated`);
      await loadData();
    } catch {
      toast.error('Failed to sync containers');
    } finally {
      setScanning(false);
    }
  }, [loadData]);

  const handleCheckAllUpdates = useCallback(async () => {
    setCheckingUpdates(true);
    try {
      const result = await api.updates.checkAll();
      if (result.already_running) {
        toast.info('Update check already in progress');
        // Fetch current job status
        const jobStatus = await api.updates.getCheckJob(result.job_id);
        setCheckJob({
          jobId: jobStatus.id,
          status: jobStatus.status,
          totalCount: jobStatus.total_count,
          checkedCount: jobStatus.checked_count,
          updatesFound: jobStatus.updates_found,
          errorsCount: jobStatus.errors_count,
          currentContainer: jobStatus.current_container,
          progressPercent: jobStatus.progress_percent,
        });
      } else {
        // New job started - initialize state
        setCheckJob({
          jobId: result.job_id,
          status: 'queued',
          totalCount: 0,
          checkedCount: 0,
          updatesFound: 0,
          errorsCount: 0,
          currentContainer: null,
          progressPercent: 0,
        });
        toast.info('Update check started');
      }
      setCheckingUpdates(false);
    } catch {
      toast.error('Failed to start update check');
      setCheckingUpdates(false);
    }
  }, []);

  // SSE event handlers for check job progress
  const handleCheckJobProgress = useCallback((data: CheckJobProgressEvent) => {
    setCheckJob({
      jobId: data.job_id,
      status: data.status as CheckJobState['status'],
      totalCount: data.total_count,
      checkedCount: data.checked_count,
      updatesFound: data.updates_found,
      errorsCount: data.errors_count || 0,
      currentContainer: data.current_container || null,
      progressPercent: data.progress_percent || 0,
    });
  }, []);

  const handleCheckJobCompleted = useCallback((data: CheckJobProgressEvent) => {
    setCheckJob({
      jobId: data.job_id,
      status: 'done',
      totalCount: data.total_count,
      checkedCount: data.checked_count,
      updatesFound: data.updates_found,
      errorsCount: data.errors_count || 0,
      currentContainer: null,
      progressPercent: 100,
    });
    // Reload data after check completes
    loadData();
  }, [loadData]);

  const handleCheckJobFailed = useCallback(() => {
    setCheckJob(prev => prev ? {
      ...prev,
      status: 'failed',
    } : null);
  }, []);

  const handleCheckJobCanceled = useCallback(() => {
    setCheckJob(prev => prev ? {
      ...prev,
      status: 'canceled',
    } : null);
    // Reload data to show any updates found before cancellation
    loadData();
  }, [loadData]);

  const handleCancelCheckJob = useCallback(async () => {
    if (!checkJob) return;
    try {
      await api.updates.cancelCheckJob(checkJob.jobId);
      toast.info('Cancellation requested');
    } catch {
      toast.error('Failed to cancel check');
    }
  }, [checkJob]);

  const handleDismissCheckJob = useCallback(() => {
    setCheckJob(null);
  }, []);

  // Subscribe to SSE events
  useEventStream({
    onCheckJobStarted: handleCheckJobProgress,
    onCheckJobProgress: handleCheckJobProgress,
    onCheckJobCompleted: handleCheckJobCompleted,
    onCheckJobFailed: handleCheckJobFailed,
    onCheckJobCanceled: handleCheckJobCanceled,
    enableToasts: false, // We handle toasts ourselves
  });

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Memoize filtered and sorted containers to avoid recalculation on every render
  const filteredContainers = useMemo(() => {
    // Create a Map for O(1) update lookups instead of O(n) for each container
    const pendingUpdatesMap = new Map(
      updates
        .filter((u) => u.status === 'pending')
        .map((u) => [u.container_id, true])
    );

    const filtered = containers.filter((container) => {
      // Search filter
      if (filters.search) {
        const search = filters.search.toLowerCase();
        if (
          !container.name.toLowerCase().includes(search) &&
          !container.image.toLowerCase().includes(search)
        ) {
          return false;
        }
      }

      // Status filter - skip for now as we don't have runtime status
      // Runtime status would need to be fetched from Docker

      // Auto-update filter
      const isAutoUpdate = container.policy === 'auto';
      if (filters.autoUpdate === 'enabled' && !isAutoUpdate) return false;
      if (filters.autoUpdate === 'disabled' && isAutoUpdate) return false;

      // Has update filter - use Map for O(1) lookup instead of O(n) .some()
      const hasUpdate = pendingUpdatesMap.has(container.id);
      if (filters.hasUpdate === 'yes' && !hasUpdate) return false;
      if (filters.hasUpdate === 'no' && hasUpdate) return false;

      return true;
    });

    // Sort
    filtered.sort((a, b) => {
      const aVal = a[sort.field as keyof Container];
      const bVal = b[sort.field as keyof Container];

      const aCompare: string | number = typeof aVal === 'string' ? aVal.toLowerCase() : String(aVal || '');
      const bCompare: string | number = typeof bVal === 'string' ? bVal.toLowerCase() : String(bVal || '');

      if (aCompare < bCompare) return sort.direction === 'asc' ? -1 : 1;
      if (aCompare > bCompare) return sort.direction === 'asc' ? 1 : -1;
      return 0;
    });

    return filtered;
  }, [containers, filters, updates, sort]);

  // Split containers into My Projects and Community Containers
  const { myProjects, otherContainers } = useMemo(() => ({
    myProjects: filteredContainers.filter((c) => c.is_my_project),
    otherContainers: filteredContainers.filter((c) => !c.is_my_project),
  }), [filteredContainers]);

  // Memoize statistics to avoid recalculation
  const stats = useMemo(() => ({
    totalContainers: containers.length,
    runningContainers: containers.length, // All containers in DB are considered "tracked"
    autoUpdateEnabled: containers.filter((c) => c.policy === 'auto').length,
    staleContainers: updates.filter((u) => u.status === 'pending' && u.reason_type === 'stale').length,
    pendingUpdates: updates.filter((u) => u.status === 'pending').length,
  }), [containers, updates]);

  // Memoize policy distribution calculation
  const policyStats = useMemo(() => {
    return containers.reduce((acc, c) => {
      const policy = c.policy || 'manual';
      acc[policy] = (acc[policy] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
  }, [containers]);

  const policyColors: Record<string, string> = {
    auto: 'bg-primary',
    manual: 'bg-accent',
    security: 'bg-yellow-500',
    disabled: 'bg-tide-surface-light',
  };

  return (
    <div className="min-h-screen bg-tide-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Total Containers</p>
                <p className="text-3xl font-bold text-tide-text mt-2">{stats.totalContainers}</p>
              </div>
              <Package className="text-primary" size={32} />
            </div>
          </div>

          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Running</p>
                <p className="text-3xl font-bold text-green-400 mt-2">{stats.runningContainers}</p>
              </div>
              <div className="w-3 h-3 bg-green-400 rounded-full animate-pulse"></div>
            </div>
          </div>

          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Auto-Update Enabled</p>
                <p className="text-3xl font-bold text-primary mt-2">{stats.autoUpdateEnabled}</p>
              </div>
              <RefreshCw className="text-primary" size={32} />
            </div>
          </div>

          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Stale Containers</p>
                <p className="text-3xl font-bold text-orange-400 mt-2">{stats.staleContainers}</p>
              </div>
              <Archive className="text-orange-400" size={32} />
            </div>
          </div>

          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Pending Updates</p>
                <p className="text-3xl font-bold text-accent mt-2">{stats.pendingUpdates}</p>
              </div>
              {stats.pendingUpdates > 0 && (
                <div className="w-3 h-3 bg-accent rounded-full animate-pulse"></div>
              )}
            </div>
          </div>
        </div>

        {/* Analytics Overview */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          {/* Update Frequency Card */}
          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-tide-text">Update Frequency</h3>
              <span className="text-xs text-tide-text-muted">Last 30 days</span>
            </div>
            {!analytics || analytics.total_updates === 0 ? (
              <div className="text-sm text-tide-text-muted">
                No analytics available yet. Run a few updates to populate trends.
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <div className="text-xs text-tide-text-muted">Total Updates</div>
                  <div className="text-3xl font-bold text-primary">{analytics.total_updates}</div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <div className="text-tide-text-muted">Successful</div>
                    <div className="text-lg font-semibold text-green-400">{analytics.successful_updates}</div>
                  </div>
                  <div>
                    <div className="text-tide-text-muted">Failed</div>
                    <div className="text-lg font-semibold text-red-400">{analytics.failed_updates}</div>
                  </div>
                </div>
                {analytics.avg_update_duration_seconds > 0 && (
                  <div className="text-xs text-tide-text-muted pt-2 border-t border-tide-border">
                    Avg duration: {Math.round(analytics.avg_update_duration_seconds)}s
                  </div>
                )}
              </div>
            )}
          </div>

          {/* CVEs Resolved Card - Only show when VulnForge is enabled */}
          {vulnforgeEnabled && (
            <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-tide-text">CVEs Resolved</h3>
                <span className="text-xs text-tide-text-muted">Last 30 days</span>
              </div>
              {!analytics || analytics.total_cves_fixed === 0 ? (
                <div className="text-sm text-tide-text-muted">
                  No CVEs resolved yet. Updates with security fixes will appear here.
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-baseline justify-between">
                    <span className="text-3xl font-bold text-green-400">{analytics.total_cves_fixed}</span>
                    <span className="text-xs text-tide-text-muted">CVEs fixed</span>
                  </div>
                  <div className="text-xs text-tide-text-muted">
                    {analytics.successful_updates > 0 && (
                      <div className="flex items-center justify-between">
                        <span>Avg per update:</span>
                        <span className="font-semibold text-tide-text">
                          {(analytics.total_cves_fixed / analytics.successful_updates).toFixed(1)}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Policy Distribution Card */}
          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-tide-text">Policy Distribution</h3>
              <span className="text-xs text-tide-text-muted">Current</span>
            </div>
            {stats.totalContainers === 0 ? (
              <div className="text-sm text-tide-text-muted">No containers found</div>
            ) : (
              <div className="space-y-2">
                {Object.entries(policyStats).map(([policy, count]) => {
                  const percentage = Math.round((count / stats.totalContainers) * 100);
                  return (
                    <div key={policy} className="space-y-1">
                      <div className="flex items-center justify-between text-xs text-tide-text-muted">
                        <span className="capitalize">{policy}</span>
                        <span>{count} ({percentage}%)</span>
                      </div>
                      <div className="h-2 bg-tide-surface rounded-full overflow-hidden">
                        <div
                          className={`h-full ${policyColors[policy] || 'bg-tide-border-light'}`}
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Actions Bar */}
        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-tide-text-muted" size={20} />
            <input
              type="text"
              placeholder="Search containers..."
              value={filters.search}
              onChange={(e) => setFilters({ ...filters, search: e.target.value })}
              className="w-full pl-10 pr-4 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <div className="flex gap-2">
            <select
              value={filters.status}
              onChange={(e) => setFilters({ ...filters, status: e.target.value })}
              className="px-4 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="all">All Status</option>
              <option value="running">Running</option>
              <option value="stopped">Stopped</option>
              <option value="exited">Exited</option>
            </select>

            <select
              value={filters.autoUpdate}
              onChange={(e) => setFilters({ ...filters, autoUpdate: e.target.value })}
              className="px-4 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="all">All Auto-Update</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </select>

            <select
              value={filters.hasUpdate}
              onChange={(e) => setFilters({ ...filters, hasUpdate: e.target.value })}
              className="px-4 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="all">All Updates</option>
              <option value="yes">Has Updates</option>
              <option value="no">No Updates</option>
            </select>

            <button
              onClick={handleScan}
              disabled={scanning || checkingUpdates}
              className="px-4 py-2 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              <RefreshCw size={16} className={scanning ? 'animate-spin' : ''} />
              {scanning ? 'Scanning...' : 'Scan'}
            </button>

            <button
              onClick={handleCheckAllUpdates}
              disabled={scanning || checkJob?.status === 'running' || checkJob?.status === 'queued'}
              className="px-4 py-2 bg-accent hover:bg-accent-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              <RefreshCw size={16} className={(checkJob?.status === 'running' || checkJob?.status === 'queued') ? 'animate-spin' : ''} />
              Check Updates
            </button>
          </div>
        </div>

        {/* Check Progress Bar */}
        {checkJob && (
          <CheckProgressBar
            job={checkJob}
            onCancel={handleCancelCheckJob}
            onDismiss={handleDismissCheckJob}
          />
        )}

        {/* Container Grid */}
        {loading ? (
          <div className="text-center py-12">
            <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
            <p className="text-tide-text-muted">Loading containers...</p>
          </div>
        ) : filteredContainers.length === 0 ? (
          <div className="text-center py-12">
            <Package className="mx-auto mb-4 text-gray-600" size={48} />
            <p className="text-tide-text-muted">No containers found</p>
            <button
              onClick={handleScan}
              className="mt-4 px-4 py-2 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors"
            >
              Scan for Containers
            </button>
          </div>
        ) : (
          <>
            {/* My Projects Section */}
            {myProjects.length > 0 && (
              <div className="mb-8">
                <h2 className="text-xl font-bold text-tide-text mb-4 flex items-center gap-2">
                  <span className="text-primary">★</span> My Projects
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {myProjects.map((container) => {
                    const hasUpdate = updates.some((u) => u.container_id === container.id && u.status === 'pending');
                    return (
                      <ContainerCard
                        key={container.id}
                        container={container}
                        hasUpdate={hasUpdate}
                        vulnforgeGlobalEnabled={vulnforgeEnabled}
                        onClick={() => setSelectedContainer(container)}
                      />
                    );
                  })}
                </div>
              </div>
            )}

            {/* Community Containers Section */}
            {otherContainers.length > 0 && (
              <div>
                {myProjects.length > 0 && (
                  <h2 className="text-xl font-bold text-tide-text mb-4">Community Containers</h2>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {otherContainers.map((container) => {
                    const hasUpdate = updates.some((u) => u.container_id === container.id && u.status === 'pending');
                    return (
                      <ContainerCard
                        key={container.id}
                        container={container}
                        hasUpdate={hasUpdate}
                        vulnforgeGlobalEnabled={vulnforgeEnabled}
                        onClick={() => setSelectedContainer(container)}
                      />
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Container Modal - lazy loaded */}
      {selectedContainer && (
        <Suspense fallback={<div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center"><div className="animate-spin h-8 w-8 border-4 border-cyan-400 border-t-transparent rounded-full"></div></div>}>
          <ContainerModal
            container={selectedContainer}
            onClose={() => setSelectedContainer(null)}
            onUpdate={loadData}
          />
        </Suspense>
      )}
    </div>
  );
}
