import { useState, useEffect, useCallback } from 'react';
import { Container, AppDependenciesResponse, DockerfileDependenciesResponse, HttpServersResponse, AppDependency, DockerfileDependency, HttpServer, BatchDependencyUpdateResponse } from '../../types';
import { api } from '../../services/api';
import { toast } from 'sonner';
import DependencyIgnoreModal from '../DependencyIgnoreModal';
import DependencyUpdatePreviewModal, { type PreviewData } from '../DependencyUpdatePreviewModal';
import BatchUpdateConfirmModal from '../BatchUpdateConfirmModal';
import BatchUpdateResultsModal from '../BatchUpdateResultsModal';
import DependencyRollbackModal from '../DependencyRollbackModal';
import HttpServerSection from './dependencies/HttpServerSection';
import DockerfileDependencySection from './dependencies/DockerfileDependencySection';
import AppDependencySection from './dependencies/AppDependencySection';

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
        await api.dependencies.ignoreHttpServer((dependency as HttpServer).id as number, reason);
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
        await api.dependencies.unignoreHttpServer((dependency as HttpServer).id as number);
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
        await api.dependencies.updateHttpServer(dep.id as number, newVersion);
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
        await api.dependencies.updateHttpServer(dep.id as number, newVersion);
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

  // Rescan handlers for sub-components
  const handleRescanHttpServers = async () => {
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
  };

  const handleRescanDockerfile = async () => {
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
  };

  const handleRescanAppDeps = async () => {
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
            <HttpServerSection
              httpServers={httpServers}
              loading={loadingHttpServers}
              onRescan={handleRescanHttpServers}
              onPreviewUpdate={handlePreviewUpdate}
              onDirectUpdate={handleDirectUpdate}
              onIgnore={handleIgnoreDependency}
              onUnignore={handleUnignoreDependency}
              onRollback={handleOpenRollback}
            />

            <DockerfileDependencySection
              dockerfileDependencies={dockerfileDependencies}
              loading={loadingDockerfileDeps}
              onRescan={handleRescanDockerfile}
              onPreviewUpdate={handlePreviewUpdate}
              onDirectUpdate={handleDirectUpdate}
              onIgnore={handleIgnoreDependency}
              onUnignore={handleUnignoreDependency}
              onRollback={handleOpenRollback}
            />
          </div>
        )}

        {/* Dependencies Tab - Production Dependencies */}
        {dependenciesSubTab === 'dependencies' && (
          <AppDependencySection
            appDependencies={appDependencies}
            loading={loadingAppDependencies}
            scanning={scanningAppDeps}
            dependencyType="production"
            dependencyFilter={dependencyFilter}
            selectedDeps={selectedProductionDeps}
            batchUpdating={batchUpdating}
            showBatchActions={true}
            onFilterChange={setDependencyFilter}
            onRescan={handleRescanAppDeps}
            onPreviewUpdate={handlePreviewUpdate}
            onDirectUpdate={handleDirectUpdate}
            onIgnore={handleIgnoreDependency}
            onUnignore={handleUnignoreDependency}
            onRollback={handleOpenRollback}
            onSelectDependency={handleSelectDependency}
            onSelectAllWithUpdates={handleSelectAllWithUpdates}
            onDeselectAll={handleDeselectAll}
            onBatchUpdateClick={() => setBatchConfirmOpen(true)}
          />
        )}

        {/* Dev Dependencies Tab */}
        {dependenciesSubTab === 'dev-dependencies' && (
          <AppDependencySection
            appDependencies={appDependencies}
            loading={loadingAppDependencies}
            scanning={scanningAppDeps}
            dependencyType="development"
            dependencyFilter={dependencyFilter}
            selectedDeps={selectedDevDeps}
            batchUpdating={batchUpdating}
            showBatchActions={true}
            onFilterChange={setDependencyFilter}
            onRescan={handleRescanAppDeps}
            onPreviewUpdate={handlePreviewUpdate}
            onDirectUpdate={handleDirectUpdate}
            onIgnore={handleIgnoreDependency}
            onUnignore={handleUnignoreDependency}
            onRollback={handleOpenRollback}
            onSelectDependency={handleSelectDependency}
            onSelectAllWithUpdates={handleSelectAllWithUpdates}
            onDeselectAll={handleDeselectAll}
            onBatchUpdateClick={() => setBatchConfirmOpen(true)}
          />
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
