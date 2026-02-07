import { useState, useEffect } from 'react';
import { UnifiedHistoryEvent } from '../types';
import { api } from '../services/api';
import StatusBadge from '../components/StatusBadge';
import { RefreshCw, History as HistoryIcon, RotateCcw, ArrowRight } from 'lucide-react';
import { format } from 'date-fns';
import { toast } from 'sonner';

// Helper function to format trigger reasons
const formatTriggerReason = (reason?: string): string => {
  if (!reason) return 'Unknown';

  // Handle manual restarts
  if (reason.startsWith('manual')) {
    const parts = reason.split(':');
    return parts.length > 1 ? parts[1].trim() : 'Manual Restart';
  }

  // Format common trigger reasons
  const reasonMap: Record<string, string> = {
    exit_code: 'Container Exited',
    health_check: 'Health Check Failed',
    oom_killed: 'Out of Memory',
    signal_killed_SIGKILL: 'Killed (SIGKILL)',
    signal_killed_SIGTERM: 'Terminated (SIGTERM)',
    manual: 'Manual Restart',
  };

  return reasonMap[reason] || reason.replace(/_/g, ' ');
};

export default function History() {
  const [history, setHistory] = useState<UnifiedHistoryEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadHistory();
  }, []);

  const loadHistory = async () => {
    setLoading(true);
    try {
      const data = await api.history.getAll();
      setHistory(data);
    } catch {
      toast.error('Failed to load history');
    } finally {
      setLoading(false);
    }
  };

  const handleRollback = async (id: number, dataBackupStatus?: string | null) => {
    const confirmMessage = dataBackupStatus === 'success'
      ? 'This will restore both the container image and data from the pre-update backup. Continue?'
      : 'This will revert the container image only. Database/config changes from the update will remain. Continue?';
    if (!confirm(confirmMessage)) {
      return;
    }

    try {
      await api.history.rollback(id);
      toast.success('Rollback initiated successfully');
      loadHistory();
    } catch {
      toast.error('Failed to rollback update');
    }
  };

  const handleUnignore = async (item: UnifiedHistoryEvent) => {
    console.log('Unignore clicked - Full item:', item);
    console.log('Dependency fields:', {
      id: item.dependency_id,
      type: item.dependency_type,
      container: item.container_id,
      name: item.dependency_name
    });

    if (!item.dependency_id || !item.dependency_type || !item.container_id) {
      toast.error(`Missing dependency information (ID: ${item.dependency_id}, Type: ${item.dependency_type}, Container: ${item.container_id})`);
      return;
    }

    try {
      // Call the appropriate unignore endpoint based on dependency type
      if (item.dependency_type === 'dockerfile') {
        await api.dependencies.unignoreDockerfile(item.dependency_id);
      } else if (item.dependency_type === 'http_server') {
        await api.dependencies.unignoreHttpServer(item.dependency_id);
      } else if (item.dependency_type === 'app_dependency') {
        await api.dependencies.unignoreAppDependency(item.dependency_id);
      }

      toast.success(`Unignored ${item.dependency_name || 'dependency'}`);
      loadHistory();
    } catch (error) {
      console.error('Unignore error:', error);
      toast.error('Failed to unignore dependency');
    }
  };

  return (
    <div className="min-h-screen bg-tide-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-tide-text">History</h1>
            <p className="text-tide-text-muted mt-2">View container updates and restart events</p>
          </div>
          <button
            onClick={loadHistory}
            disabled={loading}
            className="px-4 py-2 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        {/* History Table */}
        {loading ? (
          <div className="text-center py-12">
            <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
            <p className="text-tide-text-muted">Loading history...</p>
          </div>
        ) : history.length === 0 ? (
          <div className="text-center py-12">
            <HistoryIcon className="mx-auto mb-4 text-gray-600" size={48} />
            <p className="text-tide-text-muted">No history found</p>
            <p className="text-sm text-tide-text-muted mt-2">
              Container updates and restarts will appear here
            </p>
          </div>
        ) : (
          <div className="bg-tide-surface border border-tide-border rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-tide-surface border-b border-tide-border">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">
                      Container
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">
                      Event
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">
                      Started
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">
                      Duration
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">
                      Performed By
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-tide-border">
                  {history.map((item) => {
                    const duration = item.completed_at
                      ? Math.round(
                          (new Date(item.completed_at).getTime() - new Date(item.started_at).getTime()) / 1000
                        )
                      : null;

                    return (
                      <tr key={`${item.event_type}-${item.id}`} className="hover:bg-tide-surface-light transition-colors">
                        {/* Container Name */}
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm font-medium text-tide-text">{item.container_name}</div>
                        </td>

                        {/* Event Column - Conditional Rendering */}
                        <td className="px-6 py-4 whitespace-nowrap">
                          {item.event_type === 'update' ? (
                            // Update Event: Show from → to tags
                            <div className="flex items-center gap-2 text-sm text-tide-text">
                              <span className="font-mono">{item.from_tag}</span>
                              <ArrowRight size={14} className="text-tide-text-muted" />
                              <span className="font-mono text-primary">{item.to_tag}</span>
                            </div>
                          ) : item.event_type === 'dependency_update' ? (
                            // Dependency Update Event: Show dependency name and version change
                            <div className="flex items-center gap-2 text-sm text-tide-text">
                              <ArrowRight size={14} className="text-primary" />
                              <span className="font-medium">{item.dependency_name || 'Dependency'}</span>
                              <span className="font-mono text-xs">{item.from_tag}</span>
                              <ArrowRight size={12} className="text-tide-text-muted" />
                              <span className="font-mono text-xs text-primary">{item.to_tag}</span>
                            </div>
                          ) : item.event_type === 'dependency_ignore' ? (
                            // Dependency Ignore Event: Show dependency name and version change
                            <div className="flex items-center gap-2 text-sm text-tide-text">
                              <span className="font-medium">{item.dependency_name || 'Dependency'}</span>
                              <span className="font-mono text-xs">{item.from_tag}</span>
                              <ArrowRight size={12} className="text-tide-text-muted" />
                              <span className="font-mono text-xs text-primary">{item.to_tag}</span>
                            </div>
                          ) : item.event_type === 'dependency_unignore' ? (
                            // Dependency Unignore Event: Show dependency name and version change
                            <div className="flex items-center gap-2 text-sm text-tide-text">
                              <span className="font-medium">{item.dependency_name || 'Dependency'}</span>
                              <span className="font-mono text-xs">{item.from_tag}</span>
                              <ArrowRight size={12} className="text-tide-text-muted" />
                              <span className="font-mono text-xs text-primary">{item.to_tag}</span>
                            </div>
                          ) : (
                            // Restart Event: Show trigger reason
                            <div className="flex items-center gap-2 text-sm text-tide-text">
                              <RefreshCw size={14} className="text-blue-400" />
                              <span className="capitalize">
                                {formatTriggerReason(item.trigger_reason)}
                              </span>
                              {item.exit_code !== null && item.exit_code !== undefined && (
                                <span className="text-xs text-tide-text-muted">
                                  (exit {item.exit_code})
                                </span>
                              )}
                            </div>
                          )}
                        </td>

                        {/* Status */}
                        <td className="px-6 py-4 whitespace-nowrap">
                          <StatusBadge status={item.status} event_type={item.event_type} />
                        </td>

                        {/* Started */}
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm text-tide-text">
                            {format(new Date(item.started_at), 'MMM d, yyyy')}
                          </div>
                          <div className="text-xs text-tide-text-muted">
                            {format(new Date(item.started_at), 'HH:mm:ss')}
                          </div>
                        </td>

                        {/* Duration */}
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm text-tide-text">
                            {duration !== null ? `${duration}s` : 'In progress'}
                          </div>
                        </td>

                        {/* Performed By */}
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm text-tide-text">{item.performed_by || 'System'}</div>
                        </td>

                        {/* Actions */}
                        <td className="px-6 py-4 whitespace-nowrap">
                          {item.event_type === 'update' && item.rollback_available && (
                            <button
                              onClick={() => handleRollback(item.id, item.data_backup_status)}
                              className="flex items-center gap-1 px-3 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded text-xs font-medium transition-colors"
                            >
                              <RotateCcw size={12} />
                              Rollback
                            </button>
                          )}
                          {item.event_type === 'dependency_ignore' && (
                            <button
                              onClick={() => handleUnignore(item)}
                              className="flex items-center gap-1 px-3 py-1.5 bg-teal-500/20 hover:bg-teal-500/30 text-teal-400 rounded text-xs font-medium transition-colors border border-teal-500/30"
                            >
                              <RefreshCw size={12} />
                              Unignore
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Error Messages */}
            {history.some((h) => h.error_message) && (
              <div className="border-t border-tide-border p-4">
                <h3 className="text-sm font-medium text-tide-text mb-3">Recent Errors</h3>
                <div className="space-y-2">
                  {history
                    .filter((h) => h.error_message)
                    .slice(0, 5)
                    .map((item) => (
                      <div key={`error-${item.event_type}-${item.id}`} className="bg-red-500/10 border border-red-500/30 rounded-md p-3">
                        <div className="flex items-start justify-between mb-1">
                          <span className="text-sm font-medium text-tide-text">
                            {item.container_name} ({item.event_type})
                          </span>
                          <span className="text-xs text-tide-text-muted">
                            {format(new Date(item.started_at), 'MMM d, HH:mm')}
                          </span>
                        </div>
                        <p className="text-xs text-red-400">{item.error_message}</p>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
