import { RefreshCw, Download, Ban, RotateCw, RotateCcw, ShieldAlert, Package, Eye } from 'lucide-react';
import { AppDependency, AppDependenciesResponse } from '../../../types';
import { formatDistanceToNow } from 'date-fns';

interface AppDependencySectionProps {
  appDependencies: AppDependenciesResponse | null;
  loading: boolean;
  scanning: boolean;
  dependencyType: 'production' | 'development';
  dependencyFilter: 'all' | 'updates' | 'security';
  selectedDeps: Set<number>;
  batchUpdating: boolean;
  showBatchActions: boolean;
  onFilterChange: (filter: 'all' | 'updates' | 'security') => void;
  onRescan: () => Promise<void>;
  onPreviewUpdate: (dep: AppDependency, type: 'app') => void;
  onDirectUpdate: (dep: AppDependency, type: 'app') => void;
  onIgnore: (dep: AppDependency, type: 'app') => void;
  onUnignore: (dep: AppDependency, type: 'app') => void;
  onRollback: (dep: AppDependency, type: 'app') => void;
  onSelectDependency: (depId: number) => void;
  onSelectAllWithUpdates: () => void;
  onDeselectAll: () => void;
  onBatchUpdateClick: () => void;
}

const severityColors = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  info: 'bg-gray-500/20 text-tide-text-muted border-gray-500/30',
};

const ecosystemIcons: Record<string, string> = {
  npm: '\u{1F4E6}',
  pypi: '\u{1F40D}',
  composer: '\u{1F418}',
  cargo: '\u{1F980}',
  go: '\u{1F439}',
};

export default function AppDependencySection({
  appDependencies,
  loading,
  scanning,
  dependencyType,
  dependencyFilter,
  selectedDeps,
  batchUpdating,
  showBatchActions,
  onFilterChange,
  onRescan,
  onPreviewUpdate,
  onDirectUpdate,
  onIgnore,
  onUnignore,
  onRollback,
  onSelectDependency,
  onSelectAllWithUpdates,
  onDeselectAll,
  onBatchUpdateClick,
}: AppDependencySectionProps) {
  const filteredDeps = (appDependencies?.dependencies ?? []).filter(dep => dep.dependency_type === dependencyType);
  const updatesCount = filteredDeps.filter(dep => dep.update_available).length;
  const securityCount = filteredDeps.filter(dep => dep.security_advisories > 0).length;

  const title = dependencyType === 'production' ? 'Production Dependencies' : 'Development Dependencies';
  const description = dependencyType === 'production'
    ? 'Track production dependencies used by your application and available updates.'
    : 'Track development dependencies used during build and test processes.';

  return (
    <div>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="text-xl font-semibold text-tide-text">{title}</h3>
          <p className="text-sm text-tide-text-muted mt-1">{description}</p>
        </div>
        <button
          onClick={onRescan}
          disabled={scanning || loading}
          className="px-3 py-1.5 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2 text-sm"
        >
          <RefreshCw size={14} className={scanning ? 'animate-spin' : ''} />
          Rescan
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-4">
        <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
          <p className="text-sm text-tide-text-muted">Total</p>
          <p className="text-2xl font-bold text-tide-text mt-1">{filteredDeps.length}</p>
        </div>
        <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
          <p className="text-sm text-tide-text-muted">Updates Available</p>
          <p className="text-2xl font-bold text-accent mt-1">{updatesCount}</p>
        </div>
        <div className="bg-tide-surface rounded-lg p-4 border border-tide-border">
          <p className="text-sm text-tide-text-muted">Security Issues</p>
          <p className="text-2xl font-bold text-red-400 mt-1">{securityCount}</p>
        </div>
      </div>

      {/* Filters */}
      {filteredDeps.length > 0 && (
        <div className="flex gap-2 mb-3">
          <button
            onClick={() => onFilterChange('all')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              dependencyFilter === 'all'
                ? 'bg-primary text-tide-text'
                : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
            }`}
          >
            All ({filteredDeps.length})
          </button>
          <button
            onClick={() => onFilterChange('updates')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              dependencyFilter === 'updates'
                ? 'bg-primary text-tide-text'
                : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
            }`}
          >
            Updates ({updatesCount})
          </button>
          <button
            onClick={() => onFilterChange('security')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              dependencyFilter === 'security'
                ? 'bg-primary text-tide-text'
                : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
            }`}
          >
            Security ({securityCount})
          </button>
        </div>
      )}

      {/* Batch Actions Bar */}
      {showBatchActions && updatesCount > 0 && (
        <div className="flex items-center justify-between bg-tide-surface-light rounded-lg p-3 mb-3 border border-tide-border">
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={selectedDeps.size === updatesCount && updatesCount > 0}
              ref={(el) => {
                if (el) {
                  el.indeterminate = selectedDeps.size > 0 && selectedDeps.size < updatesCount;
                }
              }}
              onChange={(e) => {
                if (e.target.checked) {
                  onSelectAllWithUpdates();
                } else {
                  onDeselectAll();
                }
              }}
              className="w-4 h-4 rounded border-tide-border accent-primary"
            />
            <span className="text-sm text-tide-text">
              {selectedDeps.size > 0
                ? `${selectedDeps.size} selected`
                : `Select all with updates (${updatesCount})`
              }
            </span>
          </div>

          {selectedDeps.size > 0 && (
            <button
              onClick={onBatchUpdateClick}
              disabled={batchUpdating}
              className="px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium transition-colors flex items-center gap-2 disabled:opacity-50"
            >
              {batchUpdating ? (
                <>
                  <RefreshCw className="animate-spin" size={16} />
                  Updating...
                </>
              ) : (
                <>
                  <Download size={16} />
                  Update Selected ({selectedDeps.size})
                </>
              )}
            </button>
          )}
        </div>
      )}

      {/* Dependencies List */}
      {loading ? (
        <div className="text-center py-12">
          <RefreshCw className="animate-spin mx-auto mb-4 text-primary" size={48} />
          <p className="text-tide-text-muted">Loading dependencies...</p>
        </div>
      ) : filteredDeps.length > 0 ? (
        <div className="space-y-2">
          {filteredDeps
            .filter((dep) => {
              if (dependencyFilter === 'updates' && !dep.update_available) return false;
              if (dependencyFilter === 'security' && dep.security_advisories === 0) return false;
              return true;
            })
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((dep) => (
              <div
                key={`${dep.ecosystem}-${dep.name}`}
                className="bg-tide-surface rounded-lg p-4 border border-tide-border flex items-center justify-between"
              >
                {/* Checkbox for items with updates */}
                {!dep.ignored && dep.update_available && showBatchActions && (
                  <div className="pr-3">
                    <input
                      type="checkbox"
                      checked={selectedDeps.has(dep.id)}
                      onChange={() => onSelectDependency(dep.id)}
                      className="w-4 h-4 rounded border-tide-border accent-primary"
                    />
                  </div>
                )}
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{ecosystemIcons[dep.ecosystem] || '\u{1F4E6}'}</span>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <p className="text-tide-text font-medium">{dep.name}</p>
                      </div>
                      <p className="text-sm text-tide-text-muted">
                        {dep.ecosystem} &bull; Current: {dep.current_version}
                        {dep.latest_version && dep.update_available && (
                          <span className="text-accent ml-2">&rarr; {dep.latest_version}</span>
                        )}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {!dep.ignored && dep.update_available && (
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${severityColors[dep.severity as keyof typeof severityColors] || severityColors.info}`}>
                      {dep.severity === 'critical' && 'Critical Update'}
                      {dep.severity === 'high' && 'High Priority'}
                      {dep.severity === 'medium' && 'Major Update'}
                      {dep.severity === 'low' && 'Minor Update'}
                      {dep.severity === 'info' && 'Patch Update'}
                    </span>
                  )}
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
                  {dep.security_advisories > 0 && (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30">
                      <ShieldAlert size={12} className="mr-1" />
                      {dep.security_advisories} {dep.security_advisories === 1 ? 'Advisory' : 'Advisories'}
                    </span>
                  )}
                  {dep.socket_score != null && (
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        dep.socket_score >= 70
                          ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                          : dep.socket_score >= 40
                          ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                          : 'bg-red-500/20 text-red-400 border border-red-500/30'
                      }`}
                    >
                      Socket: {dep.socket_score}
                    </span>
                  )}
                  {!dep.ignored && dep.update_available && (
                    <>
                      <button
                        onClick={() => onPreviewUpdate(dep, 'app')}
                        className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                        title="Preview update changes"
                      >
                        <Eye size={14} />
                        Preview
                      </button>
                      <button
                        onClick={() => onDirectUpdate(dep, 'app')}
                        className="px-2.5 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-primary"
                        title="Update dependency immediately"
                      >
                        <Download size={14} />
                        Update
                      </button>
                      <button
                        onClick={() => onIgnore(dep, 'app')}
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
                      onClick={() => onUnignore(dep, 'app')}
                      className="px-2.5 py-1.5 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-tide-border"
                      title="Unignore this update"
                    >
                      <RotateCw size={14} />
                      Unignore
                    </button>
                  )}
                  <button
                    onClick={() => onRollback(dep, 'app')}
                    className="px-2.5 py-1.5 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded-lg font-medium transition-colors flex items-center gap-1.5 text-xs border border-orange-500/30"
                    title="Rollback to a previous version"
                  >
                    <RotateCcw size={14} />
                    Rollback
                  </button>
                </div>
              </div>
            ))}
        </div>
      ) : (
        <div className="text-center py-12 bg-tide-surface border border-tide-border rounded-lg">
          <Package className="mx-auto mb-4 text-gray-600" size={48} />
          <p className="text-tide-text-muted">No {dependencyType} dependencies found</p>
          <p className="text-sm text-tide-text-muted mt-1">
            No {dependencyType} dependencies detected in your project
          </p>
        </div>
      )}

      {/* Last Scan Info */}
      {appDependencies?.last_scan && (
        <div className="text-sm text-tide-text-muted text-center mt-4">
          Last scanned: {formatDistanceToNow(new Date(appDependencies.last_scan), { addSuffix: true })}
        </div>
      )}
    </div>
  );
}
