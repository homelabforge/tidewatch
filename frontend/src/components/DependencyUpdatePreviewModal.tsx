import { useState, useEffect } from 'react';
import { X, Eye, Download, ArrowRight, FileText, AlertCircle, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import { AppDependency, DockerfileDependency, HttpServer } from '../types';

interface PreviewData {
  current_line: string;
  new_line: string;
  file_path: string;
  line_number?: number;
  current_version: string;
  new_version: string;
  changelog?: string;
  changelog_url?: string;
}

interface DependencyUpdatePreviewModalProps {
  dependency: AppDependency | DockerfileDependency | HttpServer;
  dependencyType: 'app' | 'dockerfile' | 'http_server';
  onClose: () => void;
  onConfirmUpdate: () => Promise<void>;
  onPreview: () => Promise<PreviewData>;
}

export default function DependencyUpdatePreviewModal({
  dependency,
  // dependencyType is passed for type safety but not currently used
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  dependencyType,
  onClose,
  onConfirmUpdate,
  onPreview,
}: DependencyUpdatePreviewModalProps) {
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changelogExpanded, setChangelogExpanded] = useState(false);

  const loadPreview = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await onPreview();
      setPreview(data);
    } catch (err) {
      console.error('Failed to load preview:', err);
      setError(err instanceof Error ? err.message : 'Failed to load preview');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleUpdate = async () => {
    setUpdating(true);
    try {
      await onConfirmUpdate();
      onClose();
    } catch (err) {
      console.error('Failed to update dependency:', err);
      setError(err instanceof Error ? err.message : 'Failed to update dependency');
    } finally {
      setUpdating(false);
    }
  };

  const getDependencyName = () => {
    if ('image_name' in dependency) {
      return dependency.image_name;
    }
    return dependency.name;
  };

  const isMajorUpdate = () => {
    if (!preview) return false;

    try {
      // Extract major version from version strings
      const currentMajor = parseInt(preview.current_version.split('.')[0].replace(/[^0-9]/g, ''));
      const newMajor = parseInt(preview.new_version.split('.')[0].replace(/[^0-9]/g, ''));

      return newMajor > currentMajor;
    } catch {
      return false;
    }
  };

  return (
    <div className="fixed inset-0 z-[60] overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
        {/* Background overlay */}
        <div className="fixed inset-0 transition-opacity bg-tide-surface/75 backdrop-blur-sm" onClick={onClose} />

        {/* Modal panel */}
        <div className="inline-block overflow-hidden text-left align-bottom transition-all transform bg-tide-surface rounded-lg shadow-xl sm:my-8 sm:align-middle sm:max-w-3xl sm:w-full relative border border-tide-border">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-tide-border">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-primary/20 rounded-lg">
                <Eye className="w-5 h-5 text-primary" />
              </div>
              <h2 className="text-xl font-bold text-tide-text">Preview Update</h2>
            </div>
            <button
              onClick={onClose}
              className="text-tide-text-muted hover:text-tide-text transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Content */}
          <div className="p-6">
            {/* Dependency Info */}
            <div className="mb-6">
              <p className="text-sm text-tide-text-muted mb-2">Dependency</p>
              <p className="text-lg font-semibold text-tide-text">{getDependencyName()}</p>
            </div>

            {/* Version Change */}
            <div className="mb-6">
              <p className="text-sm text-tide-text-muted mb-2">Version Change</p>
              <div className="flex items-center gap-3">
                <span className="font-mono text-lg text-primary">
                  {preview?.current_version || (loading ? '...' : 'N/A')}
                </span>
                <ArrowRight className="text-orange-500" size={20} />
                <span className="font-mono text-lg text-orange-500 font-semibold">
                  {preview?.new_version || (loading ? '...' : 'N/A')}
                </span>
              </div>
            </div>

            {/* Loading State */}
            {loading && (
              <div className="text-center py-12">
                <div className="inline-block w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mb-4" />
                <p className="text-tide-text-muted">Loading preview...</p>
              </div>
            )}

            {/* Error State */}
            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-red-400 mb-1">Preview Failed</p>
                    <p className="text-sm text-red-400/80">
                      {error.includes('Not Found') || error.includes('404')
                        ? 'This dependency type does not support file updates yet. Only Dockerfile dependencies and HTTP servers can be updated through the UI currently.'
                        : error}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Preview Content */}
            {!loading && !error && preview && (
              <div className="space-y-4">
                {/* File Info */}
                <div className="bg-tide-surface-light border border-tide-border rounded-lg p-4">
                  <div className="flex items-center gap-2 text-sm text-tide-text-muted mb-2">
                    <FileText size={16} />
                    <span className="font-medium">File to be updated</span>
                  </div>
                  <div className="space-y-1">
                    <div className="font-mono text-sm text-tide-text break-all">
                      {preview.file_path}
                    </div>
                    {preview.line_number && (
                      <div className="text-sm text-tide-text-muted">
                        Line {preview.line_number}
                      </div>
                    )}
                  </div>
                </div>

                {/* Changelog Section */}
                <div className="bg-tide-surface-light border border-tide-border rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <FileText size={16} className="text-primary" />
                      <span className="font-medium text-tide-text">What's Changed</span>
                    </div>
                  </div>
                  {preview.changelog ? (
                    <div>
                      <button
                        onClick={() => setChangelogExpanded(!changelogExpanded)}
                        className="w-full flex items-center justify-between py-2 text-left hover:opacity-80 transition-opacity"
                      >
                        <span className="text-sm text-tide-text-muted">View Release Notes</span>
                        <div className="flex items-center gap-2">
                          {preview.changelog_url && (
                            <a
                              href={preview.changelog_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-primary hover:text-primary/80 transition-colors"
                            >
                              <ExternalLink size={16} />
                            </a>
                          )}
                          {changelogExpanded ? (
                            <ChevronUp size={16} className="text-tide-text-muted" />
                          ) : (
                            <ChevronDown size={16} className="text-tide-text-muted" />
                          )}
                        </div>
                      </button>
                      {changelogExpanded && (
                        <div className="mt-2 p-3 bg-tide-surface rounded border border-tide-border max-h-96 overflow-y-auto">
                          <pre className="text-sm text-tide-text-muted whitespace-pre-wrap font-mono">
                            {preview.changelog}
                          </pre>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-sm text-tide-text-muted">
                      No changelog available for this update. Check the project's documentation or release notes for details.
                    </p>
                  )}
                </div>

                {/* Major Version Warning */}
                {isMajorUpdate() && (
                  <div className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-4">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="w-5 h-5 text-orange-400 flex-shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm font-semibold text-orange-400 mb-1">Major Version Update</p>
                        <p className="text-sm text-orange-400/90">
                          This is a major version update which may contain breaking changes. Please review the changelog and ensure your application is compatible before proceeding.
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Info Note */}
                <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
                  <p className="text-sm text-blue-400">
                    A backup will be created before updating. You can restore from the backup if needed.
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex gap-3 justify-end p-6 border-t border-tide-border bg-tide-surface-light">
            <button
              onClick={onClose}
              disabled={updating}
              className="px-4 py-2 text-sm font-medium text-tide-text bg-tide-surface border border-tide-border rounded-lg hover:bg-tide-surface-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={handleUpdate}
              disabled={updating || loading || !!error}
              className="px-4 py-2 text-sm font-medium text-white bg-primary border border-primary rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {updating ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Updating...
                </>
              ) : (
                <>
                  <Download className="w-4 h-4" />
                  Apply Update
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
