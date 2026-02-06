import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, CheckCircle2, XCircle, AlertCircle, ArrowRight, Undo2, EyeOff, Eye, History } from 'lucide-react';
import { Container, UpdateHistory } from '../../types';
import { formatDistanceToNow } from 'date-fns';
import { api } from '../../services/api';
import { toast } from 'sonner';
import StatusBadge from '../StatusBadge';

interface HistoryTabProps {
  container: Container;
  onClose: () => void;
  onUpdate?: () => void;
}

export default function HistoryTab({ container, onClose, onUpdate }: HistoryTabProps) {
  const [history, setHistory] = useState<UpdateHistory[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const loadUpdateHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const response = await fetch(`/api/v1/containers/${container.id}/details`);
      if (!response.ok) throw new Error('Failed to fetch history');
      const data = await response.json();
      setHistory(data.history || []);
    } catch (error) {
      console.error('Failed to load update history:', error);
      setHistory([]);
    } finally {
      setLoadingHistory(false);
    }
  }, [container.id]);

  useEffect(() => {
    loadUpdateHistory();
  }, [loadUpdateHistory]);

  const handleRollback = async (historyId: number) => {
    if (!confirm('Are you sure you want to rollback to the previous version? This will restart the container.')) {
      return;
    }

    try {
      await api.history.rollback(historyId);
      toast.success('Rollback initiated successfully');
      await loadUpdateHistory();
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
        toast.success(`Unignored ${item.dependency_name || 'dependency'}`);
      } else if (item.dependency_type === 'http_server') {
        await api.dependencies.unignoreHttpServer(item.dependency_id);
        toast.success(`Unignored ${item.dependency_name || 'dependency'}`);
      } else if (item.dependency_type === 'app_dependency') {
        await api.dependencies.unignoreAppDependency(item.dependency_id);
        toast.success(`Unignored ${item.dependency_name || 'dependency'}`);
      }

      await loadUpdateHistory();
      onUpdate?.();
    } catch (error) {
      console.error('Unignore error:', error);
      toast.error('Failed to unignore dependency');
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-tide-text">Update History</h3>
        <button
          onClick={loadUpdateHistory}
          disabled={loadingHistory}
          className="px-3 py-1 bg-tide-surface-light hover:bg-gray-500 text-tide-text rounded-lg text-sm transition-colors disabled:opacity-50 flex items-center gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${loadingHistory ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {loadingHistory ? (
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
  );
}
