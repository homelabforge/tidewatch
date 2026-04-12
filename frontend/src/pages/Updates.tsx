import { useState, useEffect, useCallback } from 'react';
import { Update, Container } from '../types';
import { api } from '../services/api';
import UpdateCard from '../components/UpdateCard';
import CheckProgressBar from '../components/CheckProgressBar';
import { useCheckJob } from '../hooks/useCheckJob';
import { RefreshCw, CircleCheckBig, CircleX, CircleAlert, Archive } from 'lucide-react';
import { toast } from 'sonner';

export default function Updates() {
  const [updates, setUpdates] = useState<Update[]>([]);
  const [containers, setContainers] = useState<Map<number, Container>>(new Map());
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('needs_attention');
  const [applyingUpdateIds, setApplyingUpdateIds] = useState<Set<number>>(new Set());
  const [approvingUpdateIds, setApprovingUpdateIds] = useState<Set<number>>(new Set());
  const [rejectingUpdateIds, setRejectingUpdateIds] = useState<Set<number>>(new Set());

  const loadUpdates = useCallback(async () => {
    setLoading(true);
    try {
      const [allData, containersData] = await Promise.all([
        api.updates.getAll(),
        api.containers.getAll()
      ]);

      setUpdates(allData);

      const containerMap = new Map(
        containersData.map(c => [c.id, c])
      );
      setContainers(containerMap);
    } catch {
      toast.error('Failed to load updates');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUpdates();
  }, [loadUpdates]);

  const { checkJob, siblingDrifts, startCheckAll, cancelCheckJob, dismissCheckJob, dismissSiblingDrifts } = useCheckJob({
    onCompleted: loadUpdates,
    onCanceled: loadUpdates,
  });

  const handleApprove = async (id: number) => {
    // Prevent duplicate clicks
    if (approvingUpdateIds.has(id)) {
      return;
    }

    setApprovingUpdateIds(prev => new Set(prev).add(id));
    try {
      await api.updates.approve(id);
      toast.success('Update approved');
      loadUpdates();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to approve update';

      // Check for concurrent modification errors
      if (message.includes('concurrent modification') || message.includes('Database conflict')) {
        toast.error('This update was modified by another action. Please refresh and try again.');
      } else {
        toast.error(message);
      }
    } finally {
      setApprovingUpdateIds(prev => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const handleReject = async (id: number) => {
    // Prevent duplicate clicks
    if (rejectingUpdateIds.has(id)) {
      return;
    }

    const reason = prompt('Reason for rejection (optional):');

    setRejectingUpdateIds(prev => new Set(prev).add(id));
    try {
      await api.updates.reject(id, reason || undefined);
      toast.success('Update rejected');
      loadUpdates();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to reject update';

      // Check for concurrent modification errors
      if (message.includes('concurrent modification') || message.includes('Database conflict')) {
        toast.error('This update was modified by another action. Please refresh and try again.');
      } else {
        toast.error(message);
      }
    } finally {
      setRejectingUpdateIds(prev => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const handleApply = async (id: number) => {
    // Prevent duplicate clicks
    if (applyingUpdateIds.has(id)) {
      return;
    }

    if (!confirm('Are you sure you want to apply this update?')) return;

    setApplyingUpdateIds(prev => new Set(prev).add(id));
    try {
      await api.updates.apply(id);

      // Poll to ensure the update has fully completed
      // The backend returns success, but we need to wait for the update record to reflect completion
      let attempts = 0;
      const maxAttempts = 30; // 30 seconds max polling

      while (attempts < maxAttempts) {
        await new Promise(resolve => setTimeout(resolve, 1000)); // Wait 1 second

        try {
          const refreshedUpdate = await api.updates.get(id);

          // Check if update is in a terminal state
          if (refreshedUpdate.status === 'applied' ||
              refreshedUpdate.status === 'rejected' ||
              refreshedUpdate.status === 'failed' ||
              refreshedUpdate.status === 'rolled_back') {
            break;
          }
        } catch {
          // Update might be deleted, break polling
          break;
        }

        attempts++;
      }

      toast.success('Update applied successfully');
      loadUpdates();
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to apply update';

      // Enhanced error handling for race conditions
      if (errorMessage.includes('concurrent modification') ||
          errorMessage.includes('Database conflict') ||
          errorMessage.includes('status changed during application')) {
        toast.error('This update was modified during application. Please check its current status.');
      } else {
        toast.error(errorMessage);
      }
    } finally {
      setApplyingUpdateIds(prev => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const handleSnooze = async (id: number) => {
    try {
      const result = await api.updates.snooze(id);
      toast.success(result.message);
      loadUpdates();
    } catch {
      toast.error('Failed to snooze notification');
    }
  };

  const handleRemoveContainer = async (id: number) => {
    if (!confirm('Are you sure you want to permanently remove this container from the database? This action cannot be undone.')) return;

    try {
      const result = await api.updates.removeContainer(id);
      toast.success(result.message);
      loadUpdates();
    } catch {
      toast.error('Failed to remove container');
    }
  };

  const handleCancelRetry = async (id: number) => {
    try {
      await api.updates.cancelRetry(id);
      toast.success('Retry cancelled, update reset to pending');
      loadUpdates();
    } catch {
      toast.error('Failed to cancel retry');
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this update? This action cannot be undone.')) return;

    try {
      const result = await api.updates.delete(id);
      toast.success(result.message);
      loadUpdates();
    } catch {
      toast.error('Failed to delete update');
    }
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
