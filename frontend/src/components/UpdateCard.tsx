import { useState, useMemo } from 'react';
import { Update, Container } from '../types';
import StatusBadge from './StatusBadge';
import { ArrowRight, Shield, AlertTriangle, ExternalLink, Check, X, Trash2, Clock, Archive, ChevronDown, ChevronRight, FileText, Loader2 } from 'lucide-react';
import { format } from 'date-fns';
import ReactMarkdown from 'react-markdown';

/**
 * Clean up changelog text by removing PR metadata and keeping just the descriptions.
 * Handles common patterns from GitHub release notes:
 * - "description (cherry-pick #123 to branch) by @user in https://..."
 * - "description by @user in https://..."
 * - "description (#123)"
 */
function cleanChangelog(text: string): string {
  return text
    .split('\n')
    .map(line => {
      // Skip empty lines or lines that are just URLs
      if (!line.trim() || line.trim().match(/^https?:\/\//)) {
        return line;
      }

      // Remove patterns like "(cherry-pick #123 to version-2025.10)"
      let cleaned = line.replace(/\s*\(cherry-pick\s+#\d+\s+to\s+[^)]+\)/gi, '');

      // Remove "by @user in https://..." pattern
      cleaned = cleaned.replace(/\s+by\s+@[\w\-[\]]+\s+in\s+https?:\/\/\S+/gi, '');

      // Remove trailing PR references like "(#123)" at end of line
      cleaned = cleaned.replace(/\s*\(#\d+\)$/g, '');

      // Remove standalone GitHub URLs at end of line
      cleaned = cleaned.replace(/\s+https?:\/\/github\.com\/\S+$/gi, '');

      // Clean up any double spaces
      cleaned = cleaned.replace(/\s{2,}/g, ' ').trim();

      return cleaned;
    })
    .join('\n');
}

interface UpdateCardProps {
  update: Update;
  container?: Container;
  onApprove?: (id: number) => void;
  onReject?: (id: number) => void;
  onApply?: (id: number) => void;
  onSnooze?: (id: number) => void;
  onRemoveContainer?: (id: number) => void;
  onCancelRetry?: (id: number) => void;
  onDelete?: (id: number) => void;
  isApplying?: boolean;
  isApproving?: boolean;
  isRejecting?: boolean;
}

export default function UpdateCard({ update, container, onApprove, onReject, onApply, onSnooze, onRemoveContainer, onCancelRetry, onDelete, isApplying = false, isApproving = false, isRejecting = false }: UpdateCardProps) {
  const [showChangelog, setShowChangelog] = useState(false);
  const isStale = update.reason_type === 'stale';

  // Clean the changelog text to remove PR metadata
  const cleanedChangelog = useMemo(() => {
    return update.changelog ? cleanChangelog(update.changelog) : null;
  }, [update.changelog]);

  const getRecommendationColor = (rec: string | null) => {
    if (!rec) return 'text-tide-text-muted';
    const lower = rec.toLowerCase();
    if (lower.includes('highly')) return 'text-green-400';
    if (lower.includes('optional')) return 'text-blue-400';
    if (lower.includes('review')) return 'text-yellow-400';
    return 'text-tide-text-muted';
  };

  const getReasonIcon = (type: string) => {
    if (type === 'security') return <Shield size={16} className="text-red-400" />;
    if (type === 'stale') return <Archive size={16} className="text-orange-400" />;
    return <AlertTriangle size={16} className="text-yellow-400" />;
  };

  const isAnyOperationInProgress = isApplying || isApproving || isRejecting;

  return (
    <div className={`relative bg-tide-surface border ${isStale ? 'border-orange-600' : 'border-tide-border'} rounded-lg p-5`}>
      {/* Loading Overlay */}
      {isAnyOperationInProgress && (
        <div className="absolute inset-0 bg-tide-surface/60 backdrop-blur-sm flex items-center justify-center z-10 rounded-lg">
          <Loader2 className="w-16 h-16 text-primary animate-spin" />
        </div>
      )}

      {/* Card Content */}
      <div className={isAnyOperationInProgress ? 'blur-sm' : ''}>
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-tide-text mb-1">{update.container_name}</h3>
          {isStale ? (
            <div className="flex items-center gap-2 text-sm text-orange-400">
              <span className="font-mono">{update.from_tag}</span>
              <span>• Inactive Container</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-sm text-tide-text-muted">
              <span className="font-mono">{update.from_tag}</span>
              <ArrowRight size={14} />
              <span className="font-mono text-primary">{update.to_tag}</span>
            </div>
          )}
        </div>
        <StatusBadge status={update.status} />
      </div>

      {/* Scope Violation Warning */}
      {container?.latest_major_tag &&
       container.latest_major_tag !== update.to_tag &&
       container.scope !== 'major' && (
        <div className="mb-3 bg-orange-500/10 border border-orange-500/30 rounded-md p-3">
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} className="text-orange-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-medium text-orange-400">
                Newer Major Version Available
              </p>
              <p className="text-xs text-tide-text-muted mt-1">
                Version {container.latest_major_tag} is available but blocked by your current
                scope setting ({container.scope}). Change scope to "major" to see this update.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Reason */}
      <div className="flex items-start gap-2 mb-3">
        {getReasonIcon(update.reason_type)}
        <div className="flex-1">
          <p className="text-sm font-medium text-tide-text capitalize">{update.reason_type} Update</p>
          {update.reason_summary && (
            <p className="text-sm text-tide-text-muted mt-1">
              {/* Check if reason_summary contains a URL and make it clickable */}
              {update.reason_summary.match(/https?:\/\/\S+/) ? (
                <>
                  {update.reason_summary.replace(/https?:\/\/\S+/, '').replace(/^See\s*/i, '').trim() || 'View '}
                  <a
                    href={update.reason_summary.match(/https?:\/\/\S+/)?.[0]}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline inline-flex items-center gap-1"
                  >
                    Release Notes <ExternalLink size={12} />
                  </a>
                </>
              ) : (
                update.reason_summary
              )}
            </p>
          )}
          {/* Show View Release Notes link if changelog_url exists and not already in reason_summary */}
          {update.changelog_url && !update.reason_summary?.match(/https?:\/\/\S+/) && (
            <a
              href={update.changelog_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline mt-1"
            >
              View Release Notes <ExternalLink size={12} />
            </a>
          )}
        </div>
      </div>

      {/* Recommendation */}
      {update.recommendation && (
        <div className="mb-3">
          <span className={`text-sm font-medium ${getRecommendationColor(update.recommendation)}`}>
            {update.recommendation}
          </span>
        </div>
      )}

      {/* Security Info */}
      {(update.cves_fixed.length > 0 || update.vuln_delta !== 0) && (
        <div className="bg-tide-surface/50 rounded-md p-3 mb-3 space-y-2">
          {update.cves_fixed.length > 0 && (
            <div className="flex items-center gap-2 text-sm">
              <Shield size={14} className="text-green-400" />
              <span className="text-tide-text">
                Fixes {update.cves_fixed.length} CVE{update.cves_fixed.length > 1 ? 's' : ''}
              </span>
            </div>
          )}
          {update.vuln_delta !== 0 && (
            <div className="flex items-center gap-2 text-sm">
              <span className={update.vuln_delta < 0 ? 'text-green-400' : 'text-red-400'}>
                {update.vuln_delta < 0 ? '↓' : '↑'} {Math.abs(update.vuln_delta)} vulnerabilities
              </span>
            </div>
          )}
        </div>
      )}

      {/* Changelog Section */}
      {(update.changelog || update.changelog_url) && (
        <div className="mb-3">
          {update.changelog ? (
            <div className="border border-tide-border rounded-md overflow-hidden">
              <button
                onClick={() => setShowChangelog(!showChangelog)}
                className="w-full flex items-center gap-2 px-3 py-2 bg-tide-surface-light/50 hover:bg-tide-surface-light text-sm text-tide-text transition-colors"
              >
                {showChangelog ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                <FileText size={14} className="text-primary" />
                <span className="font-medium">Release Notes</span>
              </button>
              {showChangelog && (
                <div className="p-3 bg-tide-bg/50 max-h-80 overflow-y-auto">
                  <div className="prose prose-sm prose-invert max-w-none
                    prose-headings:text-tide-text prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-2
                    prose-h1:text-lg prose-h2:text-base prose-h3:text-sm
                    prose-p:text-tide-text-muted prose-p:my-2
                    prose-a:text-primary prose-a:no-underline hover:prose-a:underline
                    prose-strong:text-tide-text
                    prose-ul:my-2 prose-ul:pl-4 prose-li:text-tide-text-muted prose-li:my-0.5
                    prose-ol:my-2 prose-ol:pl-4
                    prose-code:text-primary prose-code:bg-tide-surface prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs
                    prose-pre:bg-tide-surface prose-pre:p-2 prose-pre:rounded prose-pre:overflow-x-auto
                  ">
                    <ReactMarkdown>{cleanedChangelog}</ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          ) : update.changelog_url && (
            <a
              href={update.changelog_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-sm text-primary hover:text-primary-dark"
            >
              View Changelog <ExternalLink size={12} />
            </a>
          )}
        </div>
      )}

      {/* Metadata */}
      <div className="text-xs text-tide-text-muted mb-4 space-y-1">
        {update.published_date && (
          <div>Published: {format(new Date(update.published_date), 'MMM d, yyyy')}</div>
        )}
        {update.image_size_delta !== 0 && (
          <div>
            Size: {update.image_size_delta > 0 ? '+' : ''}
            {(update.image_size_delta / 1024 / 1024).toFixed(1)} MB
          </div>
        )}
      </div>

        {/* Actions */}
        {update.status === 'pending' && isStale && (onSnooze || onRemoveContainer || onReject) && (
          <div className="flex gap-2">
            {onSnooze && (
              <button
                onClick={() => onSnooze(update.id)}
                disabled={isAnyOperationInProgress}
                className="flex-1 px-3 py-2 bg-tide-surface-light hover:bg-tide-border text-tide-text rounded-md text-sm font-medium flex items-center justify-center gap-2 transition-colors border border-tide-border disabled:opacity-50 disabled:cursor-not-allowed"
                title="Dismiss for 30 days"
              >
                <Clock size={14} />
                Snooze
              </button>
            )}
            {onRemoveContainer && (
              <button
                onClick={() => onRemoveContainer(update.id)}
                disabled={isAnyOperationInProgress}
                className="flex-1 px-3 py-2 bg-red-600/80 hover:bg-red-600 text-tide-text rounded-md text-sm font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Remove container from database"
              >
                <Trash2 size={14} />
                Remove
              </button>
            )}
            {onReject && (
              <button
                onClick={() => onReject(update.id)}
                disabled={isAnyOperationInProgress}
                className="flex-1 px-3 py-2 bg-tide-surface-light hover:bg-tide-border text-tide-text rounded-md text-sm font-medium flex items-center justify-center gap-2 transition-colors border border-tide-border disabled:opacity-50 disabled:cursor-not-allowed"
                title="Keep container in database"
              >
                <Check size={14} />
                Keep
              </button>
            )}
          </div>
        )}

        {update.status === 'pending' && !isStale && (onApprove || onReject) && (
          <div className="flex gap-2">
            {onApprove && (
              <button
                onClick={() => onApprove(update.id)}
                disabled={isAnyOperationInProgress}
                className="flex-1 px-3 py-2 bg-primary hover:bg-primary-dark text-tide-text rounded-md text-sm font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Check size={14} />
                Approve
              </button>
            )}
            {onReject && (
              <button
                onClick={() => onReject(update.id)}
                disabled={isAnyOperationInProgress}
                className="flex-1 px-3 py-2 bg-tide-surface-light hover:bg-tide-border text-tide-text rounded-md text-sm font-medium flex items-center justify-center gap-2 transition-colors border border-tide-border disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <X size={14} />
                Reject
              </button>
            )}
          </div>
        )}

        {update.status === 'approved' && onApply && (
          <button
            onClick={() => onApply(update.id)}
            disabled={isAnyOperationInProgress}
            className="w-full px-3 py-2 bg-accent hover:bg-accent-dark text-tide-text rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Apply Update
          </button>
        )}

        {/* Pending Retry Actions */}
        {update.status === 'pending_retry' && (onCancelRetry || onReject || onDelete) && (
          <div className="flex gap-2">
            {onCancelRetry && (
              <button
                onClick={() => onCancelRetry(update.id)}
                disabled={isAnyOperationInProgress}
                className="flex-1 px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/50 text-blue-400 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Cancel Retry
              </button>
            )}
            {onReject && (
              <button
                onClick={() => onReject(update.id)}
                disabled={isAnyOperationInProgress}
                className="flex-1 px-3 py-2 bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/50 text-yellow-400 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Reject
              </button>
            )}
            {onDelete && (
              <button
                onClick={() => onDelete(update.id)}
                disabled={isAnyOperationInProgress}
                className="px-3 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/50 text-red-400 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        )}

        {/* Error Info */}
        {update.last_error && (
          <div className="mt-3 p-3 bg-red-500/10 border border-red-500/30 rounded-md">
            <p className="text-xs text-red-400">{update.last_error}</p>
            {update.retry_count > 0 && (
              <p className="text-xs text-tide-text-muted mt-1">
                Retry {update.retry_count}/{update.max_retries}
                {update.next_retry_at && ` • Next retry: ${format(new Date(update.next_retry_at), 'PPp')}`}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
