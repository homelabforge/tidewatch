import React from 'react';
import { RefreshCw, FileText, Download, Ban, RotateCw, RotateCcw, Eye, Container as ContainerIcon } from 'lucide-react';
import { DockerfileDependency, DockerfileDependenciesResponse } from '../../../types';
import { formatDistanceToNow } from 'date-fns';

interface DockerfileDependencySectionProps {
  dockerfileDependencies: DockerfileDependenciesResponse | null;
  loading: boolean;
  onRescan: () => Promise<void>;
  onPreviewUpdate: (dep: DockerfileDependency, type: 'dockerfile') => void;
  onDirectUpdate: (dep: DockerfileDependency, type: 'dockerfile') => void;
  onIgnore: (dep: DockerfileDependency, type: 'dockerfile') => void;
  onUnignore: (dep: DockerfileDependency, type: 'dockerfile') => void;
  onRollback: (dep: DockerfileDependency, type: 'dockerfile') => void;
}

const severityColors = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  info: 'bg-gray-500/20 text-tide-text-muted border-gray-500/30',
};

export default function DockerfileDependencySection({
  dockerfileDependencies,
  loading,
  onRescan,
  onPreviewUpdate,
  onDirectUpdate,
  onIgnore,
  onUnignore,
  onRollback,
}: DockerfileDependencySectionProps): React.ReactNode {
  return (
    <div>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="text-xl font-semibold text-tide-text">Dockerfile Dependencies</h3>
          <p className="text-sm text-tide-text-muted mt-1">
            Base and build images used in your Dockerfile. Dependencies are scanned automatically when you open this tab.
          </p>
        </div>
        <button
          onClick={onRescan}
          disabled={loading}
          className="px-3 py-1.5 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2 text-sm"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Rescan
        </button>
      </div>

      {/* Stats */}
      {dockerfileDependencies && (dockerfileDependencies.dependencies?.length ?? 0) > 0 && (
        <div className="grid grid-cols-2 gap-4 mb-6">
          <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
            <p className="text-sm text-tide-text-muted">Total Images</p>
            <p className="text-2xl font-bold text-tide-text mt-1">{dockerfileDependencies.total}</p>
          </div>
          <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
            <p className="text-sm text-tide-text-muted">Updates Available</p>
            <p className="text-2xl font-bold text-accent mt-1">{dockerfileDependencies.with_updates}</p>
          </div>
        </div>
      )}

      {/* Dependencies List */}
      {loading ? (
        <div className="text-center py-12">
          <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
          <p className="text-tide-text-muted">Loading Dockerfile dependencies...</p>
        </div>
      ) : dockerfileDependencies && (dockerfileDependencies.dependencies?.length ?? 0) > 0 ? (
        <div className="space-y-2">
          {[...(dockerfileDependencies.dependencies ?? [])]
            .sort((a, b) => a.image_name.localeCompare(b.image_name))
            .map((dep) => (
            <div
              key={dep.id}
              className="bg-tide-surface rounded-lg p-4 border border-tide-border"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <ContainerIcon size={20} className="text-primary" />
                    <div>
                      <p className="text-tide-text font-medium">{dep.image_name}</p>
                      <p className="text-sm text-tide-text-muted">
                        {dep.dependency_type === 'base_image' ? 'Base Image' : 'Build Image'}
                        {dep.stage_name && ` \u2022 Stage: ${dep.stage_name}`}
                        {' \u2022 '}Current: {dep.current_tag}
                        {dep.latest_tag && dep.update_available && (
                          <span className="text-accent ml-2">&rarr; {dep.latest_tag}</span>
                        )}
                      </p>
                      <p className="text-xs text-tide-text-muted mt-1">
                        {dep.dockerfile_path}
                        {dep.line_number && ` (line ${dep.line_number})`}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {!dep.ignored && dep.update_available && (() => {
                    return (
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${severityColors[dep.severity as keyof typeof severityColors] || severityColors.info}`}>
                        {dep.severity === 'critical' && 'Critical Update'}
                        {dep.severity === 'high' && 'High Priority'}
                        {dep.severity === 'medium' && 'Major Update'}
                        {dep.severity === 'low' && 'Minor Update'}
                        {dep.severity === 'info' && 'Patch Update'}
                      </span>
                    );
                  })()}
                  {!dep.ignored && !dep.update_available && dep.last_checked && (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">
                      Up to date
                    </span>
                  )}
                  {dep.ignored && (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-500/20 text-gray-400 border border-gray-500/30">
                      Up to date
                    </span>
                  )}
                  {!dep.ignored && dep.update_available && (
                    <>
                      <button
                        onClick={() => onPreviewUpdate(dep, 'dockerfile')}
                        className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                        title="Preview update changes"
                      >
                        <Eye size={14} />
                        Preview
                      </button>
                      <button
                        onClick={() => onDirectUpdate(dep, 'dockerfile')}
                        className="px-2.5 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary"
                        title="Update Dockerfile immediately"
                      >
                        <Download size={14} />
                        Update
                      </button>
                      <button
                        onClick={() => onIgnore(dep, 'dockerfile')}
                        className="px-2.5 py-1.5 bg-primary/20 hover:bg-primary/30 text-primary rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary/30"
                        title="Ignore this update"
                      >
                        <Ban size={14} />
                        Ignore
                      </button>
                    </>
                  )}
                  {dep.ignored && (
                    <button
                      onClick={() => onUnignore(dep, 'dockerfile')}
                      className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                      title="Unignore this update"
                    >
                      <RotateCw size={14} />
                      Unignore
                    </button>
                  )}
                  <button
                    onClick={() => onRollback(dep, 'dockerfile')}
                    className="px-2.5 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-orange-500/30"
                    title="Rollback to a previous version"
                  >
                    <RotateCcw size={14} />
                    Rollback
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 bg-tide-surface border border-tide-border rounded-lg">
          <FileText className="mx-auto mb-4 text-gray-600" size={48} />
          <p className="text-tide-text-muted">No Dockerfile found</p>
          <p className="text-sm text-tide-text-muted mt-1">
            Click "Scan Dockerfile" to detect base and build images if a Dockerfile exists
          </p>
        </div>
      )}

      {/* Last Scan Info */}
      {dockerfileDependencies?.last_scan && (
        <div className="text-sm text-tide-text-muted text-center mt-4">
          Last scanned: {formatDistanceToNow(new Date(dockerfileDependencies.last_scan), { addSuffix: true })}
        </div>
      )}
    </div>
  );
}
