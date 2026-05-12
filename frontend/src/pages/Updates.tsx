import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Update, Container } from '../types';
import { api, ApiError } from '../services/api';
import UpdateCard from '../components/UpdateCard';
import CheckProgressBar from '../components/CheckProgressBar';
import { useCheckJob } from '../hooks/useCheckJob';
import { RefreshCw, CircleCheckBig, CircleX, CircleAlert, Archive } from 'lucide-react';
import { toast } from 'sonner';

export default function Updates() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<string>('needs_attention');
  const [applyingUpdateIds, setApplyingUpdateIds] = useState<Set<number>>(new Set());
  const [approvingUpdateIds, setApprovingUpdateIds] = useState<Set<number>>(new Set());
  const [rejectingUpdateIds, setRejectingUpdateIds] = useState<Set<number>>(new Set());

  const updatesQuery = useQuery({
    queryKey: ['updates', 'all'] as const,
    queryFn: () => api.updates.getAll(),
  });

  const containersQuery = useQuery({
    queryKey: ['containers', 'all'] as const,
    queryFn: () => api.containers.getAll(),
  });

  const updates: Update[] = updatesQuery.data ?? [];
  const containers: Map<number, Container> = (() => {
    const map = new Map<number, Container>();
    for (const c of containersQuery.data ?? []) map.set(c.id, c);
    return map;
  })();
  const loading = updatesQuery.isLoading || containersQuery.isLoading;

  const updatesError = updatesQuery.error;
  useEffect(() => {
    if (updatesError) toast.error('Failed to load updates');
  }, [updatesError]);

  const invalidateUpdates = () =>
    queryClient.invalidateQueries({ queryKey: ['updates', 'all'] });
  const invalidateContainers = () =>
    queryClient.invalidateQueries({ queryKey: ['containers', 'all'] });
  const invalidateHistory = () =>
    queryClient.invalidateQueries({ queryKey: ['history'] });

  const onCheckJobDone = () => {
    invalidateUpdates();
    invalidateContainers();
  };

  const { checkJob, siblingDrifts, startCheckAll, cancelCheckJob, dismissCheckJob, dismissSiblingDrifts } = useCheckJob({
    onCompleted: onCheckJobDone,
    onCanceled: onCheckJobDone,
  });

  // Shared concurrent-modification toast — preserves the today's pre-existing
  // "refresh and try again" wording when the backend returns a write conflict.
  const surfaceConflict = (message: string, fallback: string) => {
    if (message.includes('concurrent modification') || message.includes('Database conflict')) {
      toast.error('This update was modified by another action. Please refresh and try again.');
    } else {
      toast.error(message || fallback);
    }
  };

  const approveMutation = useMutation({
    mutationFn: (id: number) => api.updates.approve(id),
    onSuccess: () => {
      toast.success('Update approved');
      invalidateUpdates();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.isSelfManaged) {
        toast.error('Self-managed infrastructure', {
          description: error.manualInstructions ?? 'Apply manually via dcp.',
          duration: 20000,
        });
        return;
      }
      const message = error instanceof Error ? error.message : 'Failed to approve update';
      surfaceConflict(message, 'Failed to approve update');
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) =>
      api.updates.reject(id, reason),
    onSuccess: () => {
      toast.success('Update rejected');
      invalidateUpdates();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : 'Failed to reject update';
      surfaceConflict(message, 'Failed to reject update');
    },
  });

  const applyMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.updates.apply(id);

      // Backend returns success on apply trigger, but the update record may
      // not yet reflect terminal state. Poll until terminal (or timeout) so
      // the post-apply UI shows the right status.
      let attempts = 0;
      const maxAttempts = 30;
      while (attempts < maxAttempts) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        try {
          const refreshed = await api.updates.get(id);
          if (
            refreshed.status === 'applied' ||
            refreshed.status === 'rejected' ||
            refreshed.status === 'failed' ||
            refreshed.status === 'rolled_back'
          ) {
            break;
          }
        } catch {
          // Update might be deleted, break polling
          break;
        }
        attempts++;
      }
    },
    onSuccess: () => {
      toast.success('Update applied successfully');
      invalidateUpdates();
      invalidateContainers();
      invalidateHistory();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.isSelfManaged) {
        toast.error('Self-managed infrastructure', {
          description: error.manualInstructions ?? 'Apply manually via dcp.',
          duration: 20000,
        });
        return;
      }
      const message = error instanceof Error ? error.message : 'Failed to apply update';
      if (
        message.includes('concurrent modification') ||
        message.includes('Database conflict') ||
        message.includes('status changed during application')
      ) {
        toast.error('This update was modified during application. Please check its current status.');
      } else {
        toast.error(message);
      }
    },
  });

  const snoozeMutation = useMutation({
    mutationFn: (id: number) => api.updates.snooze(id),
    onSuccess: (result) => {
      toast.success(result.message);
      invalidateUpdates();
    },
    onError: () => toast.error('Failed to snooze notification'),
  });

  const removeContainerMutation = useMutation({
    mutationFn: (id: number) => api.updates.removeContainer(id),
    onSuccess: (result) => {
      toast.success(result.message);
      invalidateUpdates();
      invalidateContainers();
    },
    onError: () => toast.error('Failed to remove container'),
  });

  const cancelRetryMutation = useMutation({
    mutationFn: (id: number) => api.updates.cancelRetry(id),
    onSuccess: () => {
      toast.success('Retry cancelled, update reset to pending');
      invalidateUpdates();
    },
    onError: () => toast.error('Failed to cancel retry'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.updates.delete(id),
    onSuccess: (result) => {
      toast.success(result.message);
      invalidateUpdates();
    },
    onError: () => toast.error('Failed to delete update'),
  });

  const handleApprove = (id: number) => {
    if (approvingUpdateIds.has(id)) return;
    setApprovingUpdateIds((prev) => new Set(prev).add(id));
    approveMutation.mutate(id, {
      onSettled: () =>
        setApprovingUpdateIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        }),
    });
  };

  const handleReject = (id: number) => {
    if (rejectingUpdateIds.has(id)) return;
    const reason = prompt('Reason for rejection (optional):');
    setRejectingUpdateIds((prev) => new Set(prev).add(id));
    rejectMutation.mutate(
      { id, reason: reason || undefined },
      {
        onSettled: () =>
          setRejectingUpdateIds((prev) => {
            const next = new Set(prev);
            next.delete(id);
            return next;
          }),
      },
    );
  };

  const handleApply = (id: number) => {
    if (applyingUpdateIds.has(id)) return;
    if (!confirm('Are you sure you want to apply this update?')) return;
    setApplyingUpdateIds((prev) => new Set(prev).add(id));
    applyMutation.mutate(id, {
      onSettled: () =>
        setApplyingUpdateIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        }),
    });
  };

  const handleSnooze = (id: number) => snoozeMutation.mutate(id);

  const handleRemoveContainer = (id: number) => {
    if (!confirm('Are you sure you want to permanently remove this container from the database? This action cannot be undone.')) return;
    removeContainerMutation.mutate(id);
  };

  const handleCancelRetry = (id: number) => cancelRetryMutation.mutate(id);

  const handleDelete = (id: number) => {
    if (!confirm('Are you sure you want to delete this update? This action cannot be undone.')) return;
    deleteMutation.mutate(id);
  };

  const handleCheckAll = startCheckAll;
  const handleCancelCheckJob = cancelCheckJob;
  const handleDismissCheckJob = dismissCheckJob;

  const getFilteredUpdates = () => {
    if (filter === 'needs_attention') return updates.filter((u) =>
      (u.status === 'pending' && u.reason_type !== 'stale') ||
      u.status === 'approved' ||
      u.status === 'pending_retry'
    );
    if (filter === 'stale') return updates.filter((u) => u.status === 'pending' && u.reason_type === 'stale');
    return updates.filter((u) => u.status.toLowerCase() === filter);
  };

  const filteredUpdates = getFilteredUpdates();
  const pendingCount = updates.filter((u) => u.status === 'pending' && u.reason_type !== 'stale').length;
  const approvedCount = updates.filter((u) => u.status === 'approved').length;
  const rejectedCount = updates.filter((u) => u.status === 'rejected').length;
  const retryingCount = updates.filter((u) => u.status === 'pending_retry').length;
  const staleCount = updates.filter((u) => u.status === 'pending' && u.reason_type === 'stale').length;
  const appliedCount = updates.filter((u) => u.status === 'applied').length;
  const needsAttentionCount = pendingCount + approvedCount + retryingCount;

  return (
    <div className="min-h-screen bg-tide-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-tide-text">Updates</h1>
            <p className="text-tide-text-muted mt-2">Review and manage container updates</p>
          </div>
          <button
            onClick={handleCheckAll}
            disabled={checkJob?.status === 'running' || checkJob?.status === 'queued'}
            className="px-4 py-2 bg-accent hover:bg-accent-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            <RefreshCw size={16} className={(checkJob?.status === 'running' || checkJob?.status === 'queued') ? 'animate-spin' : ''} />
            Check Updates
          </button>
        </div>

        {/* Check Progress Bar */}
        {checkJob && (
          <CheckProgressBar
            job={checkJob}
            onCancel={handleCancelCheckJob}
            onDismiss={handleDismissCheckJob}
          />
        )}

        {/* Sibling Drift Warning Banner */}
        {siblingDrifts.length > 0 && (
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4 mb-4">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-sm font-medium text-yellow-400 mb-1">Sibling Drift Detected</h3>
                {siblingDrifts.map((drift, i) => (
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
                onClick={dismissSiblingDrifts}
                className="text-tide-text-muted hover:text-tide-text text-xs ml-4 shrink-0"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Pending</p>
                <p className="text-3xl font-bold text-yellow-400 mt-2">{pendingCount}</p>
              </div>
              <CircleAlert className="text-yellow-400" size={32} />
            </div>
          </div>

          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Approved</p>
                <p className="text-3xl font-bold text-blue-400 mt-2">{approvedCount}</p>
              </div>
              <CircleCheckBig className="text-blue-400" size={32} />
            </div>
          </div>

          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Rejected</p>
                <p className="text-3xl font-bold text-tide-text-muted mt-2">{rejectedCount}</p>
              </div>
              <CircleX className="text-tide-text-muted" size={32} />
            </div>
          </div>

          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Stale</p>
                <p className="text-3xl font-bold text-orange-400 mt-2">{staleCount}</p>
              </div>
              <Archive className="text-orange-400" size={32} />
            </div>
          </div>

          <div className="bg-tide-surface rounded-lg p-6 border border-tide-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-tide-text-muted">Applied</p>
                <p className="text-3xl font-bold text-green-400 mt-2">{appliedCount}</p>
              </div>
              <CircleCheckBig className="text-green-400" size={32} />
            </div>
          </div>
        </div>

        {/* Filter Tabs */}
        <div className="flex gap-2 mb-6 overflow-x-auto">
          <button
            onClick={() => setFilter('needs_attention')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors whitespace-nowrap flex items-center gap-1.5 ${
              filter === 'needs_attention'
                ? 'bg-primary text-tide-text'
                : 'bg-tide-surface text-tide-text-muted hover:bg-tide-surface'
            }`}
          >
            <CircleAlert size={14} />
            Needs Attention ({needsAttentionCount})
          </button>
          <button
            onClick={() => setFilter('rejected')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
              filter === 'rejected'
                ? 'bg-primary text-tide-text'
                : 'bg-tide-surface text-tide-text-muted hover:bg-tide-surface'
            }`}
          >
            Rejected ({rejectedCount})
          </button>
          <button
            onClick={() => setFilter('stale')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors whitespace-nowrap flex items-center gap-1.5 ${
              filter === 'stale'
                ? 'bg-orange-600 text-tide-text'
                : 'bg-tide-surface text-tide-text-muted hover:bg-tide-surface'
            }`}
          >
            <Archive size={14} />
            Stale ({staleCount})
          </button>
          <button
            onClick={() => setFilter('applied')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
              filter === 'applied'
                ? 'bg-primary text-tide-text'
                : 'bg-tide-surface text-tide-text-muted hover:bg-tide-surface'
            }`}
          >
            Applied ({appliedCount})
          </button>
        </div>

        {/* Updates List */}
        {loading ? (
          <div className="text-center py-12">
            <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
            <p className="text-tide-text-muted">Loading updates...</p>
          </div>
        ) : filteredUpdates.length === 0 ? (
          <div className="text-center py-12">
            {filter === 'needs_attention' ? (
              <>
                <CircleCheckBig className="mx-auto mb-4 text-green-500/50" size={48} />
                <p className="text-tide-text-muted">All containers are up to date</p>
                <button
                  onClick={handleCheckAll}
                  className="mt-4 px-4 py-2 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors"
                >
                  Check for Updates
                </button>
              </>
            ) : (
              <>
                <CircleAlert className="mx-auto mb-4 text-gray-600" size={48} />
                <p className="text-tide-text-muted">No {filter} updates</p>
              </>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {filteredUpdates.map((update) => (
              <UpdateCard
                key={update.id}
                update={update}
                container={containers.get(update.container_id)}
                onApprove={handleApprove}
                onReject={handleReject}
                onApply={handleApply}
                onSnooze={handleSnooze}
                onRemoveContainer={handleRemoveContainer}
                onCancelRetry={handleCancelRetry}
                onDelete={handleDelete}
                isApplying={applyingUpdateIds.has(update.id)}
                isApproving={approvingUpdateIds.has(update.id)}
                isRejecting={rejectingUpdateIds.has(update.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
