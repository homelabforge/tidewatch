import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileText, Download, Ban, RotateCw, RotateCcw, ShieldAlert, Package, Server, Eye, Container as ContainerIcon } from 'lucide-react';
import { Container, AppDependenciesResponse, DockerfileDependenciesResponse, HttpServersResponse, AppDependency, DockerfileDependency, HttpServer, BatchDependencyUpdateResponse } from '../../types';
import { formatDistanceToNow } from 'date-fns';
import { api } from '../../services/api';
import { toast } from 'sonner';
import DependencyIgnoreModal from '../DependencyIgnoreModal';
import DependencyUpdatePreviewModal, { type PreviewData } from '../DependencyUpdatePreviewModal';
import BatchUpdateConfirmModal from '../BatchUpdateConfirmModal';
import BatchUpdateResultsModal from '../BatchUpdateResultsModal';
import DependencyRollbackModal from '../DependencyRollbackModal';

interface DependenciesTabProps {
  container: Container;
}

export default function DependenciesTab({ container }: DependenciesTabProps) {
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

  // Sub-tab state
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

  // Rollback modal state
  const [rollbackModalOpen, setRollbackModalOpen] = useState(false);
  const [dependencyToRollback, setDependencyToRollback] = useState<{
    dependency: AppDependency | DockerfileDependency | HttpServer;
    type: 'app' | 'dockerfile' | 'http_server';
  } | null>(null);

  // Batch update selection state
  const [selectedProductionDeps, setSelectedProductionDeps] = useState<Set<number>>(new Set());
  const [selectedDevDeps, setSelectedDevDeps] = useState<Set<number>>(new Set());

  // Batch update operation state
  const [batchUpdating, setBatchUpdating] = useState(false);
  const [batchConfirmOpen, setBatchConfirmOpen] = useState(false);
  const [batchResultsOpen, setBatchResultsOpen] = useState(false);
  const [batchResults, setBatchResults] = useState<BatchDependencyUpdateResponse | null>(null);

  // Load functions
  const loadAppDependencies = useCallback(async () => {
    setLoadingAppDependencies(true);
    try {
      try {
        await api.containers.scanAppDependencies(container.id);
      } catch {
        console.log('App dependency scan skipped');
      }
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
      try {
        await api.containers.scanDockerfileDependencies(container.id);
      } catch {
        console.log('Dockerfile scan skipped: no Dockerfile found');
      }
      const data = await api.containers.getDockerfileDependencies(container.id);
      setDockerfileDependencies(data);
    } catch (error) {
      console.error('Error loading Dockerfile dependencies:', error);
      setDockerfileDependencies(null);
    } finally {
      setLoadingDockerfileDeps(false);
    }
  }, [container.id]);

  const loadHttpServers = useCallback(async () => {
    setLoadingHttpServers(true);
    try {
      try {
        await api.containers.scanHttpServers(container.id);
      } catch {
        console.log('HTTP server scan skipped');
      }
      const data = await api.containers.getHttpServers(container.id);
      setHttpServers(data);
    } catch (error) {
      console.error('Error loading HTTP servers:', error);
      setHttpServers(null);
    } finally {
      setLoadingHttpServers(false);
    }
  }, [container.id]);

  useEffect(() => {
    if (container.is_my_project) {
      loadAppDependencies();
    }
    loadDockerfileDependencies();
    loadHttpServers();
  }, [container.id, container.is_my_project, loadAppDependencies, loadDockerfileDependencies, loadHttpServers]);

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

  const handleOpenRollback = (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: 'app' | 'dockerfile' | 'http_server'
  ) => {
    setDependencyToRollback({ dependency, type });
    setRollbackModalOpen(true);
  };

  const handleRollbackComplete = () => {
    loadDockerfileDependencies();
    loadHttpServers();
    loadAppDependencies();
    toast.success('Dependency rolled back successfully');
  };

  const handlePreviewLoad = async (): Promise<PreviewData> => {
    if (!dependencyToPreview) throw new Error('No dependency to preview');

    const { dependency, type } = dependencyToPreview;

    if (type === 'app') {
      const dep = dependency as AppDependency;
      if (!dep.id) throw new Error(`Dependency ${dep.name} is missing ID field`);
      return await api.dependencies.previewAppDependencyUpdate(dep.id, dep.latest_version || '');
    } else if (type === 'dockerfile') {
      const dep = dependency as DockerfileDependency;
      if (!dep.id) throw new Error(`Dependency ${dep.image_name} is missing ID field`);
      return await api.dependencies.previewDockerfileUpdate(dep.id, dep.latest_tag || '');
    } else if (type === 'http_server') {
      const dep = dependency as HttpServer;
      if (!dep.id) throw new Error(`HTTP server ${dep.name} is missing ID field`);
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
      throw error;
    }
  };

  // Batch selection helpers
  const getCurrentSelection = useCallback(() => {
    if (dependenciesSubTab === 'dependencies') return selectedProductionDeps;
    if (dependenciesSubTab === 'dev-dependencies') return selectedDevDeps;
    return new Set<number>();
  }, [dependenciesSubTab, selectedProductionDeps, selectedDevDeps]);

  const setCurrentSelection = useCallback((newSelection: Set<number>) => {
    if (dependenciesSubTab === 'dependencies') setSelectedProductionDeps(newSelection);
    if (dependenciesSubTab === 'dev-dependencies') setSelectedDevDeps(newSelection);
  }, [dependenciesSubTab]);

  const getDepsWithUpdates = useCallback((type: 'production' | 'development') => {
    return (appDependencies?.dependencies || [])
      .filter(dep => dep.dependency_type === type && dep.update_available && !dep.ignored);
  }, [appDependencies]);

  const handleSelectDependency = useCallback((depId: number) => {
    const current = getCurrentSelection();
    const newSelection = new Set(current);
    if (newSelection.has(depId)) {
      newSelection.delete(depId);
    } else {
      newSelection.add(depId);
    }
    setCurrentSelection(newSelection);
  }, [getCurrentSelection, setCurrentSelection]);

  const handleSelectAllWithUpdates = useCallback(() => {
    const type = dependenciesSubTab === 'dependencies' ? 'production' : 'development';
    const depsWithUpdates = getDepsWithUpdates(type);
    const newSelection = new Set(depsWithUpdates.map(d => d.id));
    setCurrentSelection(newSelection);
  }, [dependenciesSubTab, getDepsWithUpdates, setCurrentSelection]);

  const handleDeselectAll = useCallback(() => {
    setCurrentSelection(new Set());
  }, [setCurrentSelection]);

  const handleBatchUpdateConfirm = async () => {
    setBatchConfirmOpen(false);
    setBatchUpdating(true);

    try {
      const selection = Array.from(getCurrentSelection());
      const results = await api.dependencies.batchUpdateAppDependencies(selection);
      setBatchResults(results);
      setBatchResultsOpen(true);

      if (results.summary.updated_count > 0) {
        toast.success(`Updated ${results.summary.updated_count} dependencies`);
      }
      if (results.summary.failed_count > 0) {
        toast.error(`${results.summary.failed_count} updates failed`);
      }
    } catch (error) {
      console.error('Batch update failed:', error);
      toast.error('Batch update failed');
    } finally {
      setBatchUpdating(false);
    }
  };

  const handleBatchResultsClose = () => {
    setBatchResultsOpen(false);
    setBatchResults(null);
    setCurrentSelection(new Set());
    loadAppDependencies();
  };

  const getSelectedDependencies = useCallback(() => {
    const selection = getCurrentSelection();
    return (appDependencies?.dependencies || []).filter(d => selection.has(d.id));
  }, [getCurrentSelection, appDependencies]);

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
      npm: '\u{1F4E6}',
      pypi: '\u{1F40D}',
      composer: '\u{1F418}',
      cargo: '\u{1F980}',
      go: '\u{1F439}',
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

        {/* Batch Actions Bar */}
        {(dependenciesSubTab === 'dependencies' || dependenciesSubTab === 'dev-dependencies') && updatesCount > 0 && (
          <div className="flex items-center justify-between bg-tide-surface-light rounded-lg p-3 mb-3 border border-tide-border">
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                checked={getCurrentSelection().size === updatesCount && updatesCount > 0}
                ref={(el) => {
                  if (el) {
                    el.indeterminate = getCurrentSelection().size > 0 && getCurrentSelection().size < updatesCount;
                  }
                }}
                onChange={(e) => {
                  if (e.target.checked) {
                    handleSelectAllWithUpdates();
                  } else {
                    handleDeselectAll();
                  }
                }}
                className="w-4 h-4 rounded border-tide-border accent-primary"
              />
              <span className="text-sm text-tide-text">
                {getCurrentSelection().size > 0
                  ? `${getCurrentSelection().size} selected`
                  : `Select all with updates (${updatesCount})`
                }
              </span>
            </div>

            {getCurrentSelection().size > 0 && (
              <button
                onClick={() => setBatchConfirmOpen(true)}
                disabled={batchUpdating}
                className="px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium transition-colors flex items-center gap-2 disabled:opacity-50"
              >
                {batchUpdating ? (
                  <>
                    <RefreshCw className="animate-spin" size={16} />
                    Updating...
                  </>
                ) : (
                  <>
                    <Download size={16} />
                    Update Selected ({getCurrentSelection().size})
                  </>
                )}
              </button>
            )}
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
                  {/* Checkbox for items with updates */}
                  {!dep.ignored && dep.update_available && (dependenciesSubTab === 'dependencies' || dependenciesSubTab === 'dev-dependencies') && (
                    <div className="pr-3">
                      <input
                        type="checkbox"
                        checked={getCurrentSelection().has(dep.id)}
                        onChange={() => handleSelectDependency(dep.id)}
                        className="w-4 h-4 rounded border-tide-border accent-primary"
                      />
                    </div>
                  )}
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{ecosystemIcons[dep.ecosystem] || '\u{1F4E6}'}</span>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-tide-text font-medium">{dep.name}</p>
                        </div>
                        <p className="text-sm text-tide-text-muted">
                          {dep.ecosystem} • Current: {dep.current_version}
                          {dep.latest_version && dep.update_available && (
                            <span className="text-accent ml-2">&rarr; {dep.latest_version}</span>
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
                    <button
                      onClick={() => handleOpenRollback(dep, 'app')}
                      className="px-2.5 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-orange-500/30"
                      title="Rollback to a previous version"
                    >
                      <RotateCcw size={14} />
                      Rollback
                    </button>
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
                                      <span className="text-accent ml-2">&rarr; v{server.latest_version}</span>
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
                              <button
                                onClick={() => handleOpenRollback(server, 'http_server')}
                                className="px-2.5 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-orange-500/30"
                                title="Rollback to a previous version"
                              >
                                <RotateCcw size={14} />
                                Rollback
                              </button>
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
                                  <span className="text-accent ml-2">&rarr; {dep.latest_tag}</span>
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
                            const dSeverityColors = {
                              critical: 'bg-red-500/20 text-red-400 border-red-500/30',
                              high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
                              medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
                              low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
                              info: 'bg-gray-500/20 text-tide-text-muted border-gray-500/30',
                            };
                            return (
                              <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${dSeverityColors[dep.severity as keyof typeof dSeverityColors] || dSeverityColors.info}`}>
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
                          <button
                            onClick={() => handleOpenRollback(dep, 'dockerfile')}
                            className="px-2.5 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-orange-500/30"
                            title="Rollback to a previous version"
                          >
                            <RotateCcw size={14} />
                            Rollback
                          </button>
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

      {/* Modals */}
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

      {batchConfirmOpen && (
        <BatchUpdateConfirmModal
          dependencies={getSelectedDependencies()}
          onClose={() => setBatchConfirmOpen(false)}
          onConfirm={handleBatchUpdateConfirm}
          isUpdating={batchUpdating}
        />
      )}

      {batchResultsOpen && batchResults && (
        <BatchUpdateResultsModal
          results={batchResults}
          onClose={handleBatchResultsClose}
        />
      )}

      {rollbackModalOpen && dependencyToRollback && (
        <DependencyRollbackModal
          dependency={dependencyToRollback.dependency}
          dependencyType={dependencyToRollback.type}
          onClose={() => {
            setRollbackModalOpen(false);
            setDependencyToRollback(null);
          }}
          onRollbackComplete={handleRollbackComplete}
        />
      )}
    </div>
  );
}
