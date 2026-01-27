import { useState } from 'react';
import { X, CheckCircle, XCircle, ChevronDown, ChevronRight } from 'lucide-react';
import type { BatchDependencyUpdateResponse } from '../types';

interface BatchUpdateResultsModalProps {
  results: BatchDependencyUpdateResponse;
  onClose: () => void;
}

export default function BatchUpdateResultsModal({
  results,
  onClose,
}: BatchUpdateResultsModalProps) {
  const [expandedErrors, setExpandedErrors] = useState<Set<number>>(new Set());

  const toggleError = (id: number) => {
    const newExpanded = new Set(expandedErrors);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedErrors(newExpanded);
  };

  const allSucceeded = results.failed.length === 0;
  const allFailed = results.updated.length === 0;

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
              <div
                className={`p-2 rounded-lg ${
                  allSucceeded
                    ? 'bg-green-500/20'
                    : allFailed
                      ? 'bg-red-500/20'
                      : 'bg-yellow-500/20'
                }`}
              >
                {allSucceeded ? (
                  <CheckCircle className="w-5 h-5 text-green-400" />
                ) : allFailed ? (
                  <XCircle className="w-5 h-5 text-red-400" />
                ) : (
                  <CheckCircle className="w-5 h-5 text-yellow-400" />
                )}
              </div>
              <h2 className="text-xl font-bold text-tide-text">
                {allSucceeded
                  ? 'All Updates Successful'
                  : allFailed
                    ? 'Updates Failed'
                    : 'Partial Success'}
              </h2>
            </div>
            <button
              onClick={onClose}
              className="text-tide-text-muted hover:text-tide-text transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Summary */}
          <div className="p-6 border-b border-tide-border">
            <div className="grid grid-cols-3 gap-4">
              <div className="text-center">
                <p className="text-2xl font-bold text-tide-text">
                  {results.summary.total}
                </p>
                <p className="text-sm text-tide-text-muted">Total</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-green-400">
                  {results.summary.updated_count}
                </p>
                <p className="text-sm text-tide-text-muted">Succeeded</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-red-400">
                  {results.summary.failed_count}
                </p>
                <p className="text-sm text-tide-text-muted">Failed</p>
              </div>
            </div>
          </div>

          {/* Results list */}
          <div className="max-h-80 overflow-y-auto">
            {/* Successful updates */}
            {results.updated.length > 0 && (
              <div className="p-4">
                <h3 className="text-sm font-medium text-green-400 mb-2">
                  Successful Updates
                </h3>
                <div className="space-y-2">
                  {results.updated.map((item) => (
                    <div
                      key={item.id}
                      className="flex items-center gap-3 p-2 bg-green-500/10 border border-green-500/20 rounded-lg"
                    >
                      <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-tide-text truncate">
                          {item.name}
                        </p>
                        <p className="text-xs text-tide-text-muted">
                          <span className="font-mono">{item.from_version}</span>
                          <span className="mx-1">→</span>
                          <span className="font-mono text-green-400">
                            {item.to_version}
                          </span>
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Failed updates */}
            {results.failed.length > 0 && (
              <div className="p-4 border-t border-tide-border">
                <h3 className="text-sm font-medium text-red-400 mb-2">
                  Failed Updates
                </h3>
                <div className="space-y-2">
                  {results.failed.map((item) => (
                    <div
                      key={item.id}
                      className="bg-red-500/10 border border-red-500/20 rounded-lg overflow-hidden"
                    >
                      <button
                        onClick={() => toggleError(item.id)}
                        className="w-full flex items-center gap-3 p-2 text-left hover:bg-red-500/5 transition-colors"
                      >
                        <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-tide-text truncate">
                            {item.name}
                          </p>
                          <p className="text-xs text-tide-text-muted">
                            <span className="font-mono">{item.from_version}</span>
                            {item.to_version && (
                              <>
                                <span className="mx-1">→</span>
                                <span className="font-mono">{item.to_version}</span>
                              </>
                            )}
                          </p>
                        </div>
                        {item.error && (
                          expandedErrors.has(item.id) ? (
                            <ChevronDown className="w-4 h-4 text-tide-text-muted flex-shrink-0" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-tide-text-muted flex-shrink-0" />
                          )
                        )}
                      </button>
                      {item.error && expandedErrors.has(item.id) && (
                        <div className="px-3 pb-3 pt-1 border-t border-red-500/20">
                          <p className="text-xs text-red-400 font-mono break-all">
                            {item.error}
                          </p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex justify-end p-6 border-t border-tide-border bg-tide-surface-light">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-white bg-primary border border-primary rounded-lg hover:bg-primary/90 transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
