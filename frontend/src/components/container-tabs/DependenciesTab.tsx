import { useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Container, AppDependency, DockerfileDependency, HttpServer, BatchDependencyUpdateResponse } from '../../types';
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
import { dependencyTypeToQueryKey } from '../../hooks/useDependencyQueries';

interface DependenciesTabProps {
  container: Container;
}

type DepType = 'app' | 'dockerfile' | 'http_server';

export default function DependenciesTab({ container }: DependenciesTabProps) {
  const queryClient = useQueryClient();

  // Sub-tab state
  const [dependenciesSubTab, setDependenciesSubTab] = useState<'infra' | 'dependencies' | 'dev-dependencies'>('infra');
  const [dependencyFilter, setDependencyFilter] = useState<'all' | 'updates' | 'security'>('updates');

  // Modal state
  const [ignoreModalOpen, setIgnoreModalOpen] = useState(false);
  const [dependencyToIgnore, setDependencyToIgnore] = useState<{
    dependency: AppDependency | DockerfileDependency | HttpServer;
    type: DepType;
  } | null>(null);

  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [dependencyToPreview, setDependencyToPreview] = useState<{
    dependency: AppDependency | DockerfileDependency | HttpServer;
    type: DepType;
  } | null>(null);

  const [rollbackModalOpen, setRollbackModalOpen] = useState(false);
  const [dependencyToRollback, setDependencyToRollback] = useState<{
    dependency: AppDependency | DockerfileDependency | HttpServer;
    type: DepType;
  } | null>(null);

  // Batch update selection state
  const [selectedProductionDeps, setSelectedProductionDeps] = useState<Set<number>>(new Set());
  const [selectedDevDeps, setSelectedDevDeps] = useState<Set<number>>(new Set());
  const [batchConfirmOpen, setBatchConfirmOpen] = useState(false);
  const [batchResultsOpen, setBatchResultsOpen] = useState(false);
  const [batchResults, setBatchResults] = useState<BatchDependencyUpdateResponse | null>(null);

  // ── Result queries (reads only — no scan on mount) ──────────────────────
  // staleTime: 0 keeps Phase 0 defaults; refetchOnWindowFocus: false + retry:
  // false makes these explicit-action queries that don't silently re-fire when
  // the user comes back to the tab.
  const READ_OPTS = {
    refetchOnWindowFocus: false,
    retry: false,
  } as const;

  const appDepsQuery = useQuery({
    queryKey: ['dependencies', 'app', container.id] as const,
    queryFn: () => api.containers.getAppDependencies(container.id),
    enabled: container.is_my_project,
    ...READ_OPTS,
  });
  const dockerfileDepsQuery = useQuery({
    queryKey: ['dependencies', 'dockerfile', container.id] as const,
    queryFn: () => api.containers.getDockerfileDependencies(container.id),
    ...READ_OPTS,
  });
  const httpServersQuery = useQuery({
    queryKey: ['dependencies', 'httpServer', container.id] as const,
    queryFn: () => api.containers.getHttpServers(container.id),
    ...READ_OPTS,
  });

  const appDependencies = appDepsQuery.data ?? null;
  const dockerfileDependencies = dockerfileDepsQuery.data ?? null;
  const httpServers = httpServersQuery.data ?? null;

  // ── Invalidation helpers ────────────────────────────────────────────────
  const invalidateForType = (type: DepType) =>
    queryClient.invalidateQueries({
      queryKey: dependencyTypeToQueryKey(type, container.id),
    });
  const invalidateDepSummary = () =>
    queryClient.invalidateQueries({
      queryKey: ['containers', 'dependencySummary'],
    });
  const invalidateHistory = () =>
    queryClient.invalidateQueries({ queryKey: ['history'] });

  // ── Scan mutations (triggered only by user action) ──────────────────────
  const scanAppMutation = useMutation({
    mutationFn: () => api.containers.scanAppDependencies(container.id),
    onSuccess: () => {
      invalidateForType('app');
      invalidateDepSummary();
    },
    onError: () => toast.error('Failed to rescan dependencies'),
  });
  const scanDockerfileMutation = useMutation({
    mutationFn: () => api.containers.scanDockerfileDependencies(container.id),
    onSuccess: () => {
      invalidateForType('dockerfile');
      invalidateDepSummary();
    },
    onError: () => toast.error('Failed to rescan Dockerfile dependencies'),
  });
  const scanHttpMutation = useMutation({
    mutationFn: () => api.containers.scanHttpServers(container.id),
    onSuccess: () => {
      invalidateForType('http_server');
      invalidateDepSummary();
    },
    onError: () => toast.error('Failed to rescan HTTP servers'),
  });

  const handleRescanAppDeps = async () => {
    try {
      await scanAppMutation.mutateAsync();
      toast.success('Dependencies rescanned successfully');
    } catch {
      // toast.error already fired in onError
    }
  };
  const handleRescanDockerfile = async () => {
    try {
      await scanDockerfileMutation.mutateAsync();
      toast.success('Dockerfile dependencies rescanned successfully');
    } catch {
      // toast.error already fired in onError
    }
  };
  const handleRescanHttpServers = async () => {
    try {
      await scanHttpMutation.mutateAsync();
      toast.success('HTTP servers rescanned successfully');
    } catch {
      // toast.error already fired in onError
    }
  };

  // ── Ignore / Unignore mutations ─────────────────────────────────────────
  const ignoreMutation = useMutation({
    mutationFn: async ({
      dependency,
      type,
      reason,
    }: {
      dependency: AppDependency | DockerfileDependency | HttpServer;
      type: DepType;
      reason?: string;
    }) => {
      if (type === 'app') {
        await api.dependencies.ignoreAppDependency((dependency as AppDependency).id, reason);
      } else if (type === 'dockerfile') {
        await api.dependencies.ignoreDockerfile((dependency as DockerfileDependency).id, reason);
      } else {
        await api.dependencies.ignoreHttpServer((dependency as HttpServer).id as number, reason);
      }
      return { dependency, type };
    },
    onSuccess: ({ dependency, type }) => {
      const name =
        type === 'app'
          ? (dependency as AppDependency).name
          : type === 'dockerfile'
            ? (dependency as DockerfileDependency).image_name
            : (dependency as HttpServer).name;
      toast.success(`Ignored update for ${name}`);
      invalidateForType(type);
      invalidateDepSummary();
      invalidateHistory();
    },
    onError: () => toast.error('Failed to ignore update'),
  });

  const unignoreMutation = useMutation({
    mutationFn: async ({
      dependency,
      type,
    }: {
      dependency: AppDependency | DockerfileDependency | HttpServer;
      type: DepType;
    }) => {
      if (type === 'app') {
        await api.dependencies.unignoreAppDependency((dependency as AppDependency).id);
      } else if (type === 'dockerfile') {
        await api.dependencies.unignoreDockerfile((dependency as DockerfileDependency).id);
      } else {
        await api.dependencies.unignoreHttpServer((dependency as HttpServer).id as number);
      }
      return { dependency, type };
    },
    onSuccess: ({ dependency, type }) => {
      const name =
        type === 'app'
          ? (dependency as AppDependency).name
          : type === 'dockerfile'
            ? (dependency as DockerfileDependency).image_name
            : (dependency as HttpServer).name;
      toast.success(`Unignored update for ${name}`);
      invalidateForType(type);
      invalidateDepSummary();
      invalidateHistory();
    },
    onError: () => toast.error('Failed to unignore update'),
  });

  // ── Direct update mutation ──────────────────────────────────────────────
  const directUpdateMutation = useMutation({
    mutationFn: async ({
      dependency,
      type,
    }: {
      dependency: AppDependency | DockerfileDependency | HttpServer;
      type: DepType;
    }) => {
      if (type === 'app') {
        const dep = dependency as AppDependency;
        await api.dependencies.updateAppDependency(dep.id, dep.latest_version || '');
        return { name: dep.name, version: dep.latest_version || '', type };
      } else if (type === 'dockerfile') {
        const dep = dependency as DockerfileDependency;
        await api.dependencies.updateDockerfile(dep.id, dep.latest_tag || '');
        return { name: dep.image_name, version: dep.latest_tag || '', type };
      } else {
        const dep = dependency as HttpServer;
        await api.dependencies.updateHttpServer(dep.id as number, dep.latest_version || '');
        return { name: dep.name, version: dep.latest_version || '', type };
      }
    },
    onSuccess: ({ name, version, type }) => {
      toast.success(`Updated ${name} to ${version}`);
      invalidateForType(type);
      invalidateDepSummary();
      invalidateHistory();
    },
    onError: () => toast.error('Failed to update dependency'),
  });

  // ── Batch update mutation (app dependencies only) ───────────────────────
  const batchUpdateMutation = useMutation({
    mutationFn: (ids: number[]) =>
      api.dependencies.batchUpdateAppDependencies(ids),
    onSuccess: (results) => {
      setBatchResults(results);
      setBatchResultsOpen(true);
      if (results.summary.updated_count > 0) {
        toast.success(`Updated ${results.summary.updated_count} dependencies`);
      }
      if (results.summary.failed_count > 0) {
        toast.error(`${results.summary.failed_count} updates failed`);
      }
      invalidateForType('app');
      invalidateDepSummary();
      invalidateHistory();
    },
    onError: () => toast.error('Batch update failed'),
  });

  const batchUpdating = batchUpdateMutation.isPending;
  const scanningAppDeps = scanAppMutation.isPending;
  const loadingAppDependencies = appDepsQuery.isLoading || appDepsQuery.isFetching;
  const loadingDockerfileDeps = dockerfileDepsQuery.isLoading || dockerfileDepsQuery.isFetching;
  const loadingHttpServers = httpServersQuery.isLoading || httpServersQuery.isFetching;

  // ── Modal-triggered handlers (state only) ───────────────────────────────
  const handleIgnoreDependency = (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: DepType,
  ) => {
    setDependencyToIgnore({ dependency, type });
    setIgnoreModalOpen(true);
  };

  const handleConfirmIgnore = async (reason?: string) => {
    if (!dependencyToIgnore) return;
    await ignoreMutation.mutateAsync({
      dependency: dependencyToIgnore.dependency,
      type: dependencyToIgnore.type,
      reason,
    });
  };

  const handleUnignoreDependency = (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: DepType,
  ) => {
    unignoreMutation.mutate({ dependency, type });
  };

  const handlePreviewUpdate = (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: DepType,
  ) => {
    setDependencyToPreview({ dependency, type });
    setPreviewModalOpen(true);
  };

  const handleOpenRollback = (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: DepType,
  ) => {
    setDependencyToRollback({ dependency, type });
    setRollbackModalOpen(true);
  };

  const handleRollbackComplete = () => {
    // Rollback modal handles the API call; we just invalidate everything that
    // could have changed and surface a success toast.
    invalidateForType('app');
    invalidateForType('dockerfile');
    invalidateForType('http_server');
    invalidateDepSummary();
    invalidateHistory();
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
    } else {
      const dep = dependency as HttpServer;
      if (!dep.id) throw new Error(`HTTP server ${dep.name} is missing ID field`);
      return await api.dependencies.previewHttpServerUpdate(dep.id, dep.latest_version || '');
    }
  };

  const handleDirectUpdate = (
    dependency: AppDependency | DockerfileDependency | HttpServer,
    type: DepType,
  ) => {
    directUpdateMutation.mutate({ dependency, type });
  };

  const handleConfirmUpdate = async () => {
    if (!dependencyToPreview) return;
    await directUpdateMutation.mutateAsync(dependencyToPreview);
    setPreviewModalOpen(false);
    setDependencyToPreview(null);
  };

  // ── Batch selection helpers ─────────────────────────────────────────────
  const getCurrentSelection = useCallback(() => {
    if (dependenciesSubTab === 'dependencies') return selectedProductionDeps;
    if (dependenciesSubTab === 'dev-dependencies') return selectedDevDeps;
    return new Set<number>();
  }, [dependenciesSubTab, selectedProductionDeps, selectedDevDeps]);

  const setCurrentSelection = useCallback(
    (newSelection: Set<number>) => {
      if (dependenciesSubTab === 'dependencies') setSelectedProductionDeps(newSelection);
      if (dependenciesSubTab === 'dev-dependencies') setSelectedDevDeps(newSelection);
    },
    [dependenciesSubTab],
  );

  const getDepsWithUpdates = useCallback(
    (type: 'production' | 'development') => {
      return (appDependencies?.dependencies || []).filter(
        (dep) => dep.dependency_type === type && dep.update_available && !dep.ignored,
      );
    },
    [appDependencies],
  );

  const handleSelectDependency = useCallback(
    (depId: number) => {
      const current = getCurrentSelection();
      const newSelection = new Set(current);
      if (newSelection.has(depId)) {
        newSelection.delete(depId);
      } else {
        newSelection.add(depId);
      }
      setCurrentSelection(newSelection);
    },
    [getCurrentSelection, setCurrentSelection],
  );

  const handleSelectAllWithUpdates = useCallback(() => {
    const type = dependenciesSubTab === 'dependencies' ? 'production' : 'development';
    const depsWithUpdates = getDepsWithUpdates(type);
    setCurrentSelection(new Set(depsWithUpdates.map((d) => d.id)));
  }, [dependenciesSubTab, getDepsWithUpdates, setCurrentSelection]);

  const handleDeselectAll = useCallback(() => {
    setCurrentSelection(new Set());
  }, [setCurrentSelection]);

  const handleBatchUpdateConfirm = () => {
    setBatchConfirmOpen(false);
    batchUpdateMutation.mutate(Array.from(getCurrentSelection()));
  };

  const handleBatchResultsClose = () => {
    setBatchResultsOpen(false);
    setBatchResults(null);
    setCurrentSelection(new Set());
  };

  const getSelectedDependencies = useCallback(() => {
    const selection = getCurrentSelection();
    return (appDependencies?.dependencies || []).filter((d) => selection.has(d.id));
  }, [getCurrentSelection, appDependencies]);

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

      <>
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
