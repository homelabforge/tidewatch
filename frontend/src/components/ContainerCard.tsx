import { Container } from '../types';
import { Package, Calendar, Shield, ShieldAlert, AlertTriangle, RotateCw, Zap, Eye, PowerOff } from 'lucide-react';
import { format } from 'date-fns';

interface ContainerCardProps {
  container: Container;
  onClick: () => void;
  hasUpdate?: boolean;
  vulnforgeGlobalEnabled?: boolean;
}

// Helper to determine update severity based on version difference
function getUpdateSeverity(currentTag: string, latestTag: string): 'patch' | 'minor' | 'major' {
  // Try to parse semantic versions
  const currentMatch = currentTag.match(/^v?(\d+)\.(\d+)\.(\d+)/);
  const latestMatch = latestTag.match(/^v?(\d+)\.(\d+)\.(\d+)/);

  if (currentMatch && latestMatch) {
    const [, curMajor, curMinor] = currentMatch;
    const [, latMajor, latMinor] = latestMatch;

    if (curMajor !== latMajor) return 'major';
    if (curMinor !== latMinor) return 'minor';
    return 'patch';
  }

  // Default to minor for non-semver
  return 'minor';
}

export default function ContainerCard({ container, onClick, hasUpdate = false, vulnforgeGlobalEnabled = false }: ContainerCardProps) {
  // Determine update badge properties
  let updateBadgeColor = '';
  let updateBadgeText = '';

  if (hasUpdate && container.latest_tag) {
    const updateSeverity = getUpdateSeverity(container.current_tag, container.latest_tag);
    updateBadgeText = `Update Available → ${container.latest_tag}`;

    if (updateSeverity === 'patch') {
      updateBadgeColor = 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    } else if (updateSeverity === 'minor') {
      updateBadgeColor = 'bg-blue-500/20 text-blue-400 border-blue-500/30';
    } else {
      updateBadgeColor = 'bg-orange-500/20 text-orange-400 border-orange-500/30';
    }
  } else if (container.latest_major_tag && container.scope !== 'major') {
    updateBadgeText = `Major Update (Blocked by ${container.scope})`;
    updateBadgeColor = 'bg-orange-500/20 text-orange-400 border-orange-500/30';
  }

  return (
    <div
      onClick={onClick}
      className="bg-tide-surface border border-tide-border rounded-lg p-4 hover:border-primary/50 transition-all cursor-pointer group"
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0">
          <h3 className="text-lg font-semibold text-tide-text truncate group-hover:text-primary transition-colors">
            {container.name}
          </h3>
          <p className="text-sm text-tide-text-muted truncate mt-1">
            {container.image}:{container.current_tag}
          </p>
        </div>
        {/* Status Badge removed - runtime status not available */}
      </div>

      {/* Info Grid */}
      <div className="grid grid-cols-2 gap-3 text-sm mb-3">
        <div className="flex items-center gap-2 text-tide-text">
          <Package size={14} className="text-tide-text-muted" />
          <span className="truncate">{container.image.split('/').pop()}</span>
        </div>
        <div className="flex items-center gap-2 text-tide-text">
          <Calendar size={14} className="text-tide-text-muted" />
          <span className="truncate">
            {container.updated_at ? format(new Date(container.updated_at), 'MMM d, yyyy') : 'N/A'}
          </span>
        </div>
        <div className="flex items-center gap-2 text-tide-text">
          {container.policy === 'auto' ? (
            <>
              <Zap size={14} className="text-teal-400" />
              <span className="text-teal-400">Auto</span>
            </>
          ) : container.policy === 'disabled' ? (
            <>
              <PowerOff size={14} className="text-red-400" />
              <span className="text-red-400">Off</span>
            </>
          ) : (
            <>
              <Eye size={14} className="text-tide-text-muted" />
              <span>Monitor</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2 text-tide-text">
          <span className="text-tide-text-muted">Scope:</span>
          <span className="capitalize">{container.scope || 'patch'}</span>
        </div>
        {/* Vulnerability Count */}
        {vulnforgeGlobalEnabled && container.vulnforge_enabled && (
          <div className="col-span-2 flex items-center gap-2">
            {container.current_vuln_count === 0 ? (
              <>
                <Shield size={14} className="text-green-400" />
                <span className="text-green-400">No known vulnerabilities</span>
              </>
            ) : container.current_vuln_count <= 5 ? (
              <>
                <ShieldAlert size={14} className="text-yellow-400" />
                <span className="text-yellow-400">{container.current_vuln_count} vulnerabilities</span>
              </>
            ) : container.current_vuln_count <= 10 ? (
              <>
                <ShieldAlert size={14} className="text-orange-400" />
                <span className="text-orange-400">{container.current_vuln_count} vulnerabilities</span>
              </>
            ) : (
              <>
                <ShieldAlert size={14} className="text-red-400" />
                <span className="text-red-400">{container.current_vuln_count} vulnerabilities</span>
              </>
            )}
          </div>
        )}
      </div>

      {/* Badge System - Two Rows at Bottom */}
      <div className="space-y-2 pt-2 border-t border-tide-border/50">
        {/* Row 1: Static badges (Auto-Restart, Policy badges, etc.) */}
        <div className="flex flex-wrap gap-2 min-h-[24px]">
          {container.auto_restart_enabled && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30">
              <RotateCw size={10} className="mr-1" />
              Auto-Restart
            </span>
          )}
        </div>

        {/* Row 2: Dynamic badges (Update Available, etc.) */}
        <div className="flex flex-wrap gap-2 min-h-[24px]">
          {updateBadgeText && (
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${updateBadgeColor}`}>
              {!hasUpdate && <AlertTriangle size={12} className="mr-1" />}
              {updateBadgeText}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
