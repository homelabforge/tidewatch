import { Container } from '../types';
import { Package, Calendar, ToggleLeft, ToggleRight, Shield, ShieldAlert, AlertTriangle } from 'lucide-react';
import { format } from 'date-fns';

interface ContainerCardProps {
  container: Container;
  onClick: () => void;
  hasUpdate?: boolean;
  vulnforgeGlobalEnabled?: boolean;
}

export default function ContainerCard({ container, onClick, hasUpdate = false, vulnforgeGlobalEnabled = false }: ContainerCardProps) {
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

      {/* Update Badge - Single unified badge */}
      <div className="mb-3">
        {hasUpdate ? (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-accent/20 text-accent border border-accent/30">
            Update Available
            {container.latest_tag && ` → ${container.latest_tag}`}
          </span>
        ) : container.latest_major_tag && container.scope !== 'major' ? (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-500/20 text-orange-400 border border-orange-500/30">
            <AlertTriangle size={12} className="mr-1" />
            Major Update (Blocked by {container.scope})
          </span>
        ) : null}
      </div>

      {/* Info Grid */}
      <div className="grid grid-cols-2 gap-3 text-sm">
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
              <ToggleRight size={14} className="text-primary" />
              <span>Auto-update</span>
            </>
          ) : (
            <>
              <ToggleLeft size={14} className="text-tide-text-muted" />
              <span>Manual</span>
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
    </div>
  );
}
