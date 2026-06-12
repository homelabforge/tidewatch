import { LoaderCircle } from 'lucide-react';
import type { ApplyProgress } from '../hooks/useApplyProgress';

const PHASE_LABELS: Record<string, string> = {
  starting: 'Starting…',
  backup: 'Backing up compose…',
  'data-backup': 'Backing up data…',
  'compose-updated': 'Updating compose…',
  pulling: 'Pulling image…',
  pulled: 'Image pulled',
  deploying: 'Deploying…',
  'health-check': 'Health check…',
};

interface ApplyProgressBarProps {
  progress: ApplyProgress;
}

/**
 * Inline, per-card progress for an in-flight apply. Driven by the SSE
 * update-progress phases surfaced through useApplyProgress.
 */
export default function ApplyProgressBar({ progress }: ApplyProgressBarProps) {
  const pct = Math.min(100, Math.max(0, progress.progress * 100));
  const label = progress.message || PHASE_LABELS[progress.phase] || 'Applying…';

  return (
    <div className="rounded-md border border-primary/30 bg-primary/5 p-3">
      <div className="mb-2 flex items-center gap-2">
        <LoaderCircle className="h-4 w-4 animate-spin text-primary" />
        <span className="text-sm font-medium text-tide-text">{label}</span>
        <span className="ml-auto text-xs text-tide-text-muted">{pct.toFixed(0)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-tide-bg">
        <div
          className="h-full bg-primary transition-all duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
