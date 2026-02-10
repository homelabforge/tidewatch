import { X, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';

export interface DepScanJobState {
  jobId: number;
  status: 'queued' | 'running' | 'done' | 'failed' | 'canceled';
  totalCount: number;
  scannedCount: number;
  updatesFound: number;
  errorsCount: number;
  currentProject: string | null;
  progressPercent: number;
}

interface DepScanProgressBarProps {
  job: DepScanJobState;
  onCancel?: () => void;
  onDismiss?: () => void;
}

export default function DepScanProgressBar({ job, onCancel, onDismiss }: DepScanProgressBarProps) {
  const isRunning = job.status === 'queued' || job.status === 'running';
  const isComplete = job.status === 'done';
  const isFailed = job.status === 'failed';
  const isCanceled = job.status === 'canceled';

  const getBarColor = (): string => {
    if (isFailed) return 'bg-red-500';
    if (isCanceled) return 'bg-yellow-500';
    return 'bg-purple-500';
  };

  const getStatusIcon = (): React.ReactNode => {
    if (isRunning) return <Loader2 className="w-5 h-5 animate-spin text-purple-400" />;
    if (isComplete) return <CheckCircle className="w-5 h-5 text-purple-400" />;
    if (isFailed) return <AlertCircle className="w-5 h-5 text-red-500" />;
    if (isCanceled) return <AlertCircle className="w-5 h-5 text-yellow-500" />;
    return <Loader2 className="w-5 h-5 text-tide-text-muted" />;
  };

  const getStatusText = (): string => {
    if (job.status === 'queued') return 'Starting dependency scan...';
    if (job.status === 'running') {
      if (job.currentProject) {
        return `Scanning ${job.currentProject}...`;
      }
      return 'Scanning project dependencies...';
    }
    if (isComplete) return 'Dependency scan complete';
    if (isFailed) return 'Dependency scan failed';
    if (isCanceled) return 'Dependency scan canceled';
    return 'Unknown status';
  };

  return (
    <div className="bg-tide-surface border border-purple-500/30 rounded-lg p-4 mb-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {getStatusIcon()}
          <span className="text-sm font-medium text-tide-text">
            {getStatusText()}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-tide-text-muted">
            {job.scannedCount}/{job.totalCount} scanned
            {job.updatesFound > 0 && (
              <span className="ml-2 text-purple-400">
                {job.updatesFound} update{job.updatesFound !== 1 ? 's' : ''} found
              </span>
            )}
            {job.errorsCount > 0 && (
              <span className="ml-2 text-red-400">
                {job.errorsCount} error{job.errorsCount !== 1 ? 's' : ''}
              </span>
            )}
          </span>
          {isRunning && onCancel && (
            <button
              onClick={onCancel}
              className="p-1 rounded hover:bg-tide-bg text-tide-text-muted hover:text-tide-text transition-colors"
              title="Cancel dependency scan"
            >
              <X className="w-4 h-4" />
            </button>
          )}
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

      <div className="h-2 bg-tide-bg rounded-full overflow-hidden">
        <div
          className={`h-full ${getBarColor()} transition-all duration-300 ease-out`}
          style={{ width: `${Math.min(100, job.progressPercent)}%` }}
        />
      </div>

      <div className="flex justify-end mt-1">
        <span className="text-xs text-tide-text-muted">
          {job.progressPercent.toFixed(0)}%
        </span>
      </div>
    </div>
  );
}
