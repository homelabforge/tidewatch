import { useState } from 'react';
import { X, Ban } from 'lucide-react';
import { AppDependency, DockerfileDependency, HttpServer } from '../types';

interface DependencyIgnoreModalProps {
  dependency: AppDependency | DockerfileDependency | HttpServer;
  dependencyType: 'app' | 'dockerfile' | 'http_server';
  onClose: () => void;
  onConfirm: (reason?: string) => Promise<void>;
}

export default function DependencyIgnoreModal({
  dependency,
  // dependencyType is passed for type safety but not currently used
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  dependencyType,
  onClose,
  onConfirm,
}: DependencyIgnoreModalProps) {
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      await onConfirm(reason || undefined);
      onClose();
    } catch (error) {
      console.error('Failed to ignore dependency:', error);
    } finally {
      setSubmitting(false);
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

  const getLatestVersion = () => {
    if ('latest_tag' in dependency) {
      return dependency.latest_tag;
    }
    return dependency.latest_version;
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
              <div className="p-2 bg-yellow-500/20 rounded-lg">
                <Ban className="w-5 h-5 text-yellow-400" />
              </div>
              <h2 className="text-xl font-bold text-tide-text">Ignore Update</h2>
            </div>
            <button
              onClick={onClose}
              className="text-tide-text-muted hover:text-tide-text transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Content */}
          <div className="p-6">
            <p className="text-tide-text mb-4">
              Ignore update for <span className="font-semibold">{getDependencyName()}</span> from{' '}
              <span className="font-mono text-sm">{getCurrentVersion()}</span> to{' '}
              <span className="font-mono text-sm text-accent">{getLatestVersion()}</span>?
            </p>

            <div className="bg-tide-surface-light border border-tide-border rounded-lg p-4 mb-4">
              <p className="text-sm text-tide-text-muted">
                Note: If a newer version is released later, the ignore will be automatically cleared
                and you'll be notified about the new update.
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-tide-text mb-2">
                Reason (optional)
              </label>
              <textarea
                className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text placeholder-tide-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-all"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g., Known breaking change, waiting for stable release..."
                rows={3}
              />
            </div>
          </div>

          {/* Footer */}
          <div className="flex gap-3 justify-end p-6 border-t border-tide-border bg-tide-surface-light">
            <button
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2 text-sm font-medium text-tide-text bg-tide-surface border border-tide-border rounded-lg hover:bg-tide-surface-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirm}
              disabled={submitting}
              className="px-4 py-2 text-sm font-medium text-white bg-primary border border-primary rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {submitting ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Ignoring...
                </>
              ) : (
                <>
                  <Ban className="w-4 h-4" />
                  Ignore Update
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
