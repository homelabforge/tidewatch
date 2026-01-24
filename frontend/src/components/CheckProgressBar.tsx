import { X, RefreshCw, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';

export interface CheckJobState {
  jobId: number;
  status: 'queued' | 'running' | 'done' | 'failed' | 'canceled';
  totalCount: number;
  checkedCount: number;
  updatesFound: number;
  errorsCount: number;
  currentContainer: string | null;
  progressPercent: number;
}

interface CheckProgressBarProps {
  job: CheckJobState;
  onCancel?: () => void;
  onDismiss?: () => void;
}

export default function CheckProgressBar({ job, onCancel, onDismiss }: CheckProgressBarProps) {
  const isRunning = job.status === 'queued' || job.status === 'running';
  const isComplete = job.status === 'done';
  const isFailed = job.status === 'failed';
  const isCanceled = job.status === 'canceled';

  // Determine bar color based on status
  const getBarColor = () => {
    if (isFailed) return 'bg-red-500';
    if (isCanceled) return 'bg-yellow-500';
    if (isComplete) return 'bg-primary';
    return 'bg-primary';
  };

  // Determine status icon
  const getStatusIcon = () => {
    if (isRunning) return <Loader2 className="w-5 h-5 animate-spin text-primary" />;
    if (isComplete) return <CheckCircle className="w-5 h-5 text-primary" />;
    if (isFailed) return <AlertCircle className="w-5 h-5 text-red-500" />;
    if (isCanceled) return <AlertCircle className="w-5 h-5 text-yellow-500" />;
    return <RefreshCw className="w-5 h-5 text-tide-text-muted" />;
  };

  // Status text
  const getStatusText = () => {
    if (job.status === 'queued') return 'Starting update check...';
    if (job.status === 'running') {
      if (job.currentContainer) {
        return `Checking ${job.currentContainer}...`;
      }
      return 'Checking containers...';
    }
    if (isComplete) return 'Update check complete';
    if (isFailed) return 'Update check failed';
    if (isCanceled) return 'Update check canceled';
    return 'Unknown status';
  };

  return (
    <div className="bg-tide-surface border border-tide-border rounded-lg p-4 mb-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {getStatusIcon()}
          <span className="text-sm font-medium text-tide-text">
            {getStatusText()}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Stats */}
          <span className="text-xs text-tide-text-muted">
            {job.checkedCount}/{job.totalCount} checked
            {job.updatesFound > 0 && (
              <span className="ml-2 text-green-400">
                {job.updatesFound} update{job.updatesFound !== 1 ? 's' : ''} found
              </span>
            )}
            {job.errorsCount > 0 && (
              <span className="ml-2 text-red-400">
                {job.errorsCount} error{job.errorsCount !== 1 ? 's' : ''}
              </span>
            )}
          </span>
          {/* Cancel button (only when running) */}
          {isRunning && onCancel && (
            <button
              onClick={onCancel}
              className="p-1 rounded hover:bg-tide-bg text-tide-text-muted hover:text-tide-text transition-colors"
              title="Cancel update check"
            >
              <X className="w-4 h-4" />
            </button>
          )}
          {/* Dismiss button (when complete/failed/canceled) */}
          {!isRunning && onDismiss && (
            <button
              onClick={onDismiss}
              className="p-1 rounded hover:bg-tide-bg text-tide-text-muted hover:text-tide-text transition-colors"
              title="Dismiss"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-2 bg-tide-bg rounded-full overflow-hidden">
        <div
          className={`h-full ${getBarColor()} transition-all duration-300 ease-out`}
          style={{ width: `${Math.min(100, job.progressPercent)}%` }}
        />
      </div>

      {/* Percentage */}
      <div className="flex justify-end mt-1">
        <span className="text-xs text-tide-text-muted">
          {job.progressPercent.toFixed(0)}%
        </span>
      </div>
    </div>
  );
}
