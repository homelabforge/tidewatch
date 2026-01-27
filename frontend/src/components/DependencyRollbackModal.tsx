import { useState, useEffect } from 'react';
import { X, RotateCcw, AlertCircle, Clock, User } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import type { AppDependency, DockerfileDependency, HttpServer, RollbackHistoryItem, RollbackHistoryResponse } from '../types';
import { api } from '../services/api';

interface DependencyRollbackModalProps {
  dependency: AppDependency | DockerfileDependency | HttpServer;
  dependencyType: 'app' | 'dockerfile' | 'http_server';
  onClose: () => void;
  onRollbackComplete: () => void;
}

export default function DependencyRollbackModal({
  dependency,
  dependencyType,
  onClose,
  onRollbackComplete,
}: DependencyRollbackModalProps) {
  const [history, setHistory] = useState<RollbackHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [rolling, setRolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<RollbackHistoryItem | null>(null);

  const loadHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      let data: RollbackHistoryResponse;
      if (dependencyType === 'dockerfile') {
        data = await api.dependencies.getDockerfileRollbackHistory(dependency.id);
      } else if (dependencyType === 'http_server') {
        data = await api.dependencies.getHttpServerRollbackHistory(dependency.id);
      } else {
        data = await api.dependencies.getAppDependencyRollbackHistory(dependency.id);
      }
      setHistory(data);
    } catch (err) {
      console.error('Failed to load rollback history:', err);
      setError(err instanceof Error ? err.message : 'Failed to load rollback history');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRollback = async () => {
    if (!selectedVersion) return;

    setRolling(true);
    setError(null);
    try {
      if (dependencyType === 'dockerfile') {
        await api.dependencies.rollbackDockerfile(dependency.id, selectedVersion.from_version);
      } else if (dependencyType === 'http_server') {
        await api.dependencies.rollbackHttpServer(dependency.id, selectedVersion.from_version);
      } else {
        await api.dependencies.rollbackAppDependency(dependency.id, selectedVersion.from_version);
      }
      onRollbackComplete();
      onClose();
    } catch (err) {
      console.error('Failed to rollback dependency:', err);
      setError(err instanceof Error ? err.message : 'Failed to rollback dependency');
    } finally {
      setRolling(false);
    }
  };

  const getDependencyName = () => {
    if ('image_name' in dependency) {
      return dependency.image_name;
    }
    return dependency.name;
  };

  const getCurrentVersion = () => {
    if ('current_tag' in dependency) {
      return dependency.current_tag;
    }
    return dependency.current_version;
  };

  return (
    <div className="fixed inset-0 z-[60] overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
        {/* Background overlay */}
        <div className="fixed inset-0 transition-opacity bg-tide-surface/75 backdrop-blur-sm" onClick={onClose} />

        {/* Modal panel */}
        <div className="inline-block overflow-hidden text-left align-bottom transition-all transform bg-tide-surface rounded-lg shadow-xl sm:my-8 sm:align-middle sm:max-w-lg sm:w-full relative border border-tide-border">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-tide-border">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-orange-500/20 rounded-lg">
                <RotateCcw className="w-5 h-5 text-orange-400" />
              </div>
              <h2 className="text-xl font-bold text-tide-text">Rollback Dependency</h2>
            </div>
            <button
              onClick={onClose}
              disabled={rolling}
              className="text-tide-text-muted hover:text-tide-text transition-colors disabled:opacity-50"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Content */}
          <div className="p-6">
            {/* Dependency Info */}
            <div className="mb-4">
              <p className="text-sm text-tide-text-muted mb-1">Dependency</p>
              <p className="text-lg font-semibold text-tide-text">{getDependencyName()}</p>
              <p className="text-sm text-tide-text-muted mt-1">
                Current version: <span className="font-mono text-primary">{getCurrentVersion()}</span>
              </p>
            </div>

            {/* Loading State */}
            {loading && (
              <div className="text-center py-12">
                <div className="inline-block w-8 h-8 border-4 border-orange-400 border-t-transparent rounded-full animate-spin mb-4" />
                <p className="text-tide-text-muted">Loading rollback history...</p>
              </div>
            )}

            {/* Error State */}
            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-red-400 mb-1">Error</p>
                    <p className="text-sm text-red-400/80">{error}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Empty State */}
            {!loading && !error && history && history.rollback_options.length === 0 && (
              <div className="text-center py-8">
                <RotateCcw className="w-12 h-12 text-tide-text-muted mx-auto mb-4 opacity-50" />
                <p className="text-tide-text-muted">No rollback options available</p>
                <p className="text-sm text-tide-text-muted mt-1">
                  This dependency has no previous versions to roll back to.
                </p>
              </div>
            )}

            {/* Rollback Options */}
            {!loading && !error && history && history.rollback_options.length > 0 && (
              <div className="space-y-3">
                <p className="text-sm text-tide-text-muted mb-2">Select a version to roll back to:</p>
                <div className="max-h-64 overflow-y-auto border border-tide-border rounded-lg divide-y divide-tide-border">
                  {history.rollback_options.map((option) => (
                    <button
                      key={option.history_id}
                      onClick={() => setSelectedVersion(option)}
                      className={`w-full p-3 text-left hover:bg-tide-surface-light transition-colors ${
                        selectedVersion?.history_id === option.history_id
                          ? 'bg-orange-500/10 border-l-2 border-orange-400'
                          : ''
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono font-medium text-tide-text">
                          {option.from_version}
                        </span>
                        {selectedVersion?.history_id === option.history_id && (
                          <span className="text-xs bg-orange-500/20 text-orange-400 px-2 py-0.5 rounded">
                            Selected
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-4 mt-1 text-xs text-tide-text-muted">
                        <span className="flex items-center gap-1">
                          <Clock size={12} />
                          {formatDistanceToNow(new Date(option.updated_at), { addSuffix: true })}
                        </span>
                        <span className="flex items-center gap-1">
                          <User size={12} />
                          {option.triggered_by}
                        </span>
                      </div>
                      <div className="text-xs text-tide-text-muted mt-1">
                        Updated to <span className="font-mono">{option.to_version}</span>
                      </div>
                    </button>
                  ))}
                </div>

                {/* Warning */}
                {selectedVersion && (
                  <div className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-4 mt-4">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="w-5 h-5 text-orange-400 flex-shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm font-medium text-orange-400 mb-1">Confirm Rollback</p>
                        <p className="text-sm text-orange-400/90">
                          This will change the version from{' '}
                          <span className="font-mono font-medium">{getCurrentVersion()}</span> to{' '}
                          <span className="font-mono font-medium">{selectedVersion.from_version}</span>.
                          The file will be updated, but you'll need to rebuild/redeploy the project for changes to take effect.
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex gap-3 justify-end p-6 border-t border-tide-border bg-tide-surface-light">
            <button
              onClick={onClose}
              disabled={rolling}
              className="px-4 py-2 text-sm font-medium text-tide-text bg-tide-surface border border-tide-border rounded-lg hover:bg-tide-surface-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={handleRollback}
              disabled={rolling || loading || !selectedVersion}
              className="px-4 py-2 text-sm font-medium text-white bg-orange-500 border border-orange-500 rounded-lg hover:bg-orange-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {rolling ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Rolling Back...
                </>
              ) : (
                <>
                  <RotateCcw className="w-4 h-4" />
                  Rollback
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
