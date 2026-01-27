import { X, Download, AlertTriangle } from 'lucide-react';
import type { AppDependency } from '../types';

interface BatchUpdateConfirmModalProps {
  dependencies: AppDependency[];
  onClose: () => void;
  onConfirm: () => void;
  isUpdating: boolean;
}

export default function BatchUpdateConfirmModal({
  dependencies,
  onClose,
  onConfirm,
  isUpdating,
}: BatchUpdateConfirmModalProps) {
  const hasSecurityIssues = dependencies.some((dep) => dep.security_advisories > 0);
  const totalSecurityIssues = dependencies.reduce(
    (sum, dep) => sum + dep.security_advisories,
    0
  );

  return (
    <div className="fixed inset-0 z-[60] overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
        {/* Background overlay */}
        <div
          className="fixed inset-0 transition-opacity bg-tide-surface/75 backdrop-blur-sm"
          onClick={onClose}
        />

        {/* Modal panel */}
        <div className="inline-block overflow-hidden text-left align-bottom transition-all transform bg-tide-surface rounded-lg shadow-xl sm:my-8 sm:align-middle sm:max-w-lg sm:w-full relative border border-tide-border">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-tide-border">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-primary/20 rounded-lg">
                <Download className="w-5 h-5 text-primary" />
              </div>
              <h2 className="text-xl font-bold text-tide-text">
                Update {dependencies.length} Dependencies
              </h2>
            </div>
            <button
              onClick={onClose}
              disabled={isUpdating}
              className="text-tide-text-muted hover:text-tide-text transition-colors disabled:opacity-50"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Content */}
          <div className="p-6">
            {hasSecurityIssues && (
              <div className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-4 mb-4 flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-orange-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-orange-400">
                    Security Advisories
                  </p>
                  <p className="text-sm text-tide-text-muted mt-1">
                    {totalSecurityIssues} security{' '}
                    {totalSecurityIssues === 1 ? 'advisory' : 'advisories'} will be
                    addressed by these updates.
                  </p>
                </div>
              </div>
            )}

            <p className="text-tide-text-muted mb-4">
              The following dependencies will be updated in their manifest files:
            </p>

            <div className="max-h-64 overflow-y-auto border border-tide-border rounded-lg divide-y divide-tide-border">
              {dependencies.map((dep) => (
                <div
                  key={dep.id}
                  className="p-3 flex items-center justify-between hover:bg-tide-surface-light"
                >
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-tide-text truncate">{dep.name}</p>
                    <p className="text-sm text-tide-text-muted">
                      <span className="font-mono">{dep.current_version}</span>
                      <span className="mx-2">→</span>
                      <span className="font-mono text-accent">{dep.latest_version}</span>
                    </p>
                  </div>
                  {dep.security_advisories > 0 && (
                    <span className="ml-2 px-2 py-0.5 text-xs font-medium bg-red-500/20 text-red-400 rounded">
                      {dep.security_advisories} CVE{dep.security_advisories > 1 ? 's' : ''}
                    </span>
                  )}
                </div>
              ))}
            </div>

            <div className="bg-tide-surface-light border border-tide-border rounded-lg p-4 mt-4">
              <p className="text-sm text-tide-text-muted">
                Backups will be created for each modified file. You can view update
                history in the History tab.
              </p>
            </div>
          </div>

          {/* Footer */}
          <div className="flex gap-3 justify-end p-6 border-t border-tide-border bg-tide-surface-light">
            <button
              onClick={onClose}
              disabled={isUpdating}
              className="px-4 py-2 text-sm font-medium text-tide-text bg-tide-surface border border-tide-border rounded-lg hover:bg-tide-surface-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              disabled={isUpdating}
              className="px-4 py-2 text-sm font-medium text-white bg-primary border border-primary rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isUpdating ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Updating...
                </>
              ) : (
                <>
                  <Download className="w-4 h-4" />
                  Update All
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
