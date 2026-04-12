import { useState, useEffect, useMemo, useCallback, lazy, Suspense } from 'react';
import { Container, Update, FilterOptions, SortOption, AnalyticsSummary } from '../types';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import ContainerCard from '../components/ContainerCard';
import CheckProgressBar from '../components/CheckProgressBar';
import DepScanProgressBar from '../components/DepScanProgressBar';
import DashboardStats from '../components/dashboard/DashboardStats';
import DashboardFilters from '../components/dashboard/DashboardFilters';
import { useCheckJob } from '../hooks/useCheckJob';
import { useDepScan } from '../hooks/useDepScan';
import { RefreshCw, Package, FolderSearch, ScanSearch } from 'lucide-react';
import { toast } from 'sonner';

// Lazy load the large ContainerModal component
const ContainerModal = lazy(() => import('../components/ContainerModal'));

export default function Dashboard() {
  const [containers, setContainers] = useState<Container[]>([]);
  const [updates, setUpdates] = useState<Update[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [selectedContainer, setSelectedContainer] = useState<Container | null>(null);
  const [vulnforgeEnabled, setVulnforgeEnabled] = useState(false);
  const [myProjectsEnabled, setMyProjectsEnabled] = useState(false);
  const [scanningProjects, setScanningProjects] = useState(false);
  const [filters, setFilters] = useState<FilterOptions>({
    search: '',
    status: 'all',
    autoUpdate: 'all',
    hasUpdate: 'all',
  });
  const [sort] = useState<SortOption>({ field: 'name', direction: 'asc' });

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [containersData, updatesData, analyticsData, settingsData, depSummaryData] = await Promise.all([
        api.containers.getAll(),
        api.updates.getAll(),
        api.analytics.getSummary(30),
        api.settings.getAll(),
        api.containers.getDependencySummary().catch(() => ({ summaries: {} })),
      ]);
      setContainers(containersData);
      setUpdates(updatesData);
      setAnalytics(analyticsData);
      depScan.setDepSummary(depSummaryData.summaries);

      const vulnforgeSetting = settingsData.find((s) => s.key === 'vulnforge_enabled');
      setVulnforgeEnabled(vulnforgeSetting?.value === 'true');

      const myProjectsSetting = settingsData.find((s) => s.key === 'my_projects_enabled');
      setMyProjectsEnabled(myProjectsSetting?.value === 'true');
    } catch {
      toast.error('Failed to load data');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Check job hook
  const checkJobHook = useCheckJob({
    onCompleted: loadData,
    onCanceled: loadData,
  });

  // Dep scan hook
  const depScan = useDepScan();

  const handleScan = useCallback(async () => {
    setScanning(true);
    try {
      const result = await api.containers.sync();
      if (result.warnings?.length) {
        result.warnings.forEach((w: string) => toast.warning(w));
      }
      toast.success(`Synced ${result.containers_found} containers: ${result.stats.added} added, ${result.stats.updated} updated`);
      await loadData();
    } catch {
      toast.error('Failed to sync containers');
    } finally {
      setScanning(false);
    }
  }, [loadData]);

  const handleScanMyProjects = useCallback(async () => {
    setScanningProjects(true);
    try {
      const result = await api.containers.scanMyProjects();
      if (result.success) {
        const { added, updated, skipped } = result.results;
        toast.success(`Projects: ${added} added, ${updated} updated, ${skipped} skipped`);
        await loadData();
      }
    } catch {
      toast.error('Failed to scan projects');
    } finally {
      setScanningProjects(false);
    }
  }, [loadData]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Memoize filtered and sorted containers
  const filteredContainers = useMemo(() => {
    const pendingUpdatesMap = new Map(
      updates
        .filter((u) => u.status === 'pending')
        .map((u) => [u.container_id, true])
    );

    const filtered = containers.filter((container) => {
      if (filters.search) {
        const search = filters.search.toLowerCase();
        if (
          !container.name.toLowerCase().includes(search) &&
          !container.image.toLowerCase().includes(search)
        ) {
          return false;
        }
      }

      const isAutoUpdate = container.policy === 'auto';
      if (filters.autoUpdate === 'enabled' && !isAutoUpdate) return false;
      if (filters.autoUpdate === 'disabled' && isAutoUpdate) return false;

      const hasUpdate = pendingUpdatesMap.has(container.id);
      if (filters.hasUpdate === 'yes' && !hasUpdate) return false;
      if (filters.hasUpdate === 'no' && hasUpdate) return false;

      return true;
    });

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

  const { myProjects, otherContainers } = useMemo(() => ({
    myProjects: filteredContainers.filter((c) => c.is_my_project),
    otherContainers: filteredContainers.filter((c) => !c.is_my_project),
  }), [filteredContainers]);

  const stats = useMemo(() => ({
    totalContainers: containers.length,
    runningContainers: containers.length,
    autoUpdateEnabled: containers.filter((c) => c.policy === 'auto').length,
    staleContainers: updates.filter((u) => u.status === 'pending' && u.reason_type === 'stale').length,
    pendingUpdates: updates.filter((u) => u.status === 'pending').length,
  }), [containers, updates]);

  const policyStats = useMemo(() => {
    return containers.reduce((acc, c) => {
      const policy = c.policy || 'monitor';
      acc[policy] = (acc[policy] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
  }, [containers]);

  const policyColors: Record<string, string> = {
    auto: 'bg-primary',
    monitor: 'bg-accent',
    disabled: 'bg-tide-surface-light',
  };

  return (
    <div className="min-h-screen bg-tide-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Stats */}
        <DashboardStats {...stats} />

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

          {/* CVEs Resolved Card */}
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
                  <div>
                    <div className="text-xs text-tide-text-muted">Total CVEs Fixed</div>
                    <div className="text-3xl font-bold text-green-400">{analytics.total_cves_fixed}</div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <div className="text-tide-text-muted">With CVE Fixes</div>
                      <div className="text-lg font-semibold text-green-400">{analytics.updates_with_cves}</div>
                    </div>
                    <div>
                      <div className="text-tide-text-muted">Without CVEs</div>
                      <div className="text-lg font-semibold text-tide-text-muted">
                        {analytics.successful_updates - analytics.updates_with_cves}
                      </div>
                    </div>
                  </div>
                  {analytics.successful_updates > 0 && (
                    <div className="text-xs text-tide-text-muted pt-2 border-t border-tide-border">
                      Avg per update: {(analytics.total_cves_fixed / analytics.successful_updates).toFixed(1)}
                    </div>
                  )}
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
        <DashboardFilters
          filters={filters}
          onFilterChange={setFilters}
          scanning={scanning}
          checkingUpdates={checkJobHook.checkingUpdates}
          checkJobStatus={checkJobHook.checkJob?.status ?? null}
          onScan={handleScan}
          onCheckUpdates={checkJobHook.startCheckAll}
        />

        {/* Check Progress Bar */}
        {checkJobHook.checkJob && (
          <CheckProgressBar
            job={checkJobHook.checkJob}
            onCancel={checkJobHook.cancelCheckJob}
            onDismiss={checkJobHook.dismissCheckJob}
          />
        )}

        {/* Sibling Drift Warning Banner */}
        {checkJobHook.siblingDrifts.length > 0 && (
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4 mb-4">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-sm font-medium text-yellow-400 mb-1">Sibling Drift Detected</h3>
                {checkJobHook.siblingDrifts.map((drift, i) => (
                  <p key={i} className="text-sm text-tide-text-muted">
                    <span className="font-mono text-tide-text">{drift.sibling_names.join(', ')}</span>
                    {' — '}
                    {drift.settings_divergent
                      ? 'check settings diverge across siblings'
                      : `running different tags: ${Object.entries(drift.per_container_tags).map(([n, t]) => `${n}=${t}`).join(', ')}`
                    }
                  </p>
                ))}
              </div>
              <button
                onClick={checkJobHook.dismissSiblingDrifts}
                className="text-tide-text-muted hover:text-tide-text text-xs ml-4 shrink-0"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Container Grid */}
        {loading ? (
          <div className="text-center py-12">
            <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
            <p className="text-tide-text-muted">Loading containers...</p>
          </div>
        ) : (
          <>
            {/* My Projects Section */}
            {myProjectsEnabled && (
              <div className="mb-8">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                  <h2 className="text-xl font-bold text-tide-text flex items-center gap-2">
                    <span className="text-primary">★</span> My Projects
                  </h2>
                  <div className="flex gap-2">
                    <button
                      onClick={depScan.startDepScan}
                      disabled={depScan.depScanJob?.status === 'running' || depScan.depScanJob?.status === 'queued' || myProjects.length === 0}
                      className="px-3 py-1.5 bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/30 text-purple-300 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
                    >
                      <ScanSearch size={14} className={(depScan.depScanJob?.status === 'running' || depScan.depScanJob?.status === 'queued') ? 'animate-pulse' : ''} />
                      Scan Deps
                    </button>
                    <button
                      onClick={handleScanMyProjects}
                      disabled={scanningProjects}
                      className="px-3 py-1.5 bg-tide-surface hover:bg-tide-surface-light border border-tide-border text-tide-text rounded-lg text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
                    >
                      <FolderSearch size={14} className={scanningProjects ? 'animate-pulse' : ''} />
                      {scanningProjects ? 'Scanning...' : 'Scan Projects'}
                    </button>
                  </div>
                </div>

                {/* Dependency Scan Progress Bar */}
                {depScan.depScanJob && (
                  <DepScanProgressBar
                    job={depScan.depScanJob}
                    onCancel={depScan.cancelDepScan}
                    onDismiss={depScan.dismissDepScan}
                  />
                )}

                {myProjects.length > 0 ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {myProjects.map((container) => {
                      const hasUpdate = updates.some((u) => u.container_id === container.id && u.status === 'pending');
                      return (
                        <ContainerCard
                          key={container.id}
                          container={container}
                          hasUpdate={hasUpdate}
                          vulnforgeGlobalEnabled={vulnforgeEnabled}
                          dependencySummary={depScan.depSummary[String(container.id)]}
                          onClick={() => setSelectedContainer(container)}
                        />
                      );
                    })}
                  </div>
                ) : containers.length > 0 ? (
                  <div className="text-center py-8 bg-tide-surface rounded-lg border border-tide-border border-dashed">
                    <FolderSearch className="mx-auto mb-3 text-tide-text-muted" size={32} />
                    <p className="text-tide-text-muted text-sm">
                      No projects discovered yet. Click &quot;Scan Projects&quot; to find containers in your projects directory.
                    </p>
                  </div>
                ) : null}
              </div>
            )}

            {/* Community Containers Section */}
            {otherContainers.length > 0 ? (
              <div>
                {myProjectsEnabled && (
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
            ) : null}

            {/* True zero-discovery state — no containers in DB at all */}
            {containers.length === 0 && (
              <div className="text-center py-12 bg-tide-surface rounded-lg border border-tide-border border-dashed">
                <Package className="mx-auto mb-4 text-gray-600" size={48} />
                <p className="text-tide-text font-medium mb-2">No containers discovered</p>
                <p className="text-tide-text-muted text-sm mb-6 max-w-md mx-auto">
                  TideWatch finds containers by reading docker-compose files.
                  Check that your compose directory is configured and contains
                  .yml or .yaml files. Subdirectories are searched automatically.
                </p>
                <div className="flex items-center justify-center gap-3">
                  <Link
                    to="/settings?tab=docker"
                    className="px-4 py-2 bg-tide-surface-light hover:bg-tide-border border border-tide-border text-tide-text rounded-lg font-medium transition-colors"
                  >
                    Configure Docker Settings
                  </Link>
                  <button
                    onClick={handleScan}
                    disabled={scanning}
                    className="px-4 py-2 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50"
                  >
                    {scanning ? 'Scanning...' : 'Scan for Containers'}
                  </button>
                </div>
              </div>
            )}

            {/* Filter-empty state — containers exist but are all filtered out */}
            {containers.length > 0 && filteredContainers.length === 0 && (
              <div className="text-center py-12">
                <Package className="mx-auto mb-4 text-gray-600" size={48} />
                <p className="text-tide-text-muted">No containers match current filters</p>
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
