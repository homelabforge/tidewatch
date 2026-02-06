import { useState, useEffect, useCallback, useRef } from 'react';
import { Database, RefreshCw, HardDrive, Shield, Upload, Plus, Download, Trash2, Info, RotateCcw, X } from 'lucide-react';
import { toast } from 'sonner';
import { formatDistanceToNow } from 'date-fns';
import { api } from '../../services/api';
import type { BackupListResponse, BackupFile } from '../../types';

interface BackupTabProps {
  loadSettings: () => Promise<void>;
}

export default function BackupTab({ loadSettings }: BackupTabProps) {
  const [backups, setBackups] = useState<BackupListResponse | null>(null);
  const [loadingBackups, setLoadingBackups] = useState(false);
  const [creatingBackup, setCreatingBackup] = useState(false);
  const [uploadingBackup, setUploadingBackup] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [restoreModalOpen, setRestoreModalOpen] = useState(false);
  const [selectedBackup, setSelectedBackup] = useState<BackupFile | null>(null);

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
  };

  const loadBackups = useCallback(async () => {
    try {
      setLoadingBackups(true);
      const backupData = await api.backup.list();
      setBackups(backupData);
    } catch (error) {
      console.error('Failed to load backups:', error);
      toast.error('Failed to load backups');
    } finally {
      setLoadingBackups(false);
    }
  }, []);

  useEffect(() => {
    loadBackups();
  }, [loadBackups]);

  const handleCreateBackup = async () => {
    try {
      setCreatingBackup(true);
      const result = await api.backup.create();
      toast.success(result.message);
      await loadBackups();
    } catch (error) {
      console.error('Failed to create backup:', error);
      toast.error('Failed to create backup');
    } finally {
      setCreatingBackup(false);
    }
  };

  const handleUploadBackup = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      setUploadingBackup(true);
      await api.backup.upload(file);
      toast.success('Backup uploaded successfully');
      await loadBackups();
    } catch (error) {
      console.error('Failed to upload backup:', error);
      toast.error('Failed to upload backup');
    } finally {
      setUploadingBackup(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleDownloadBackup = (filename: string) => {
    const url = api.backup.download(filename);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    toast.success('Backup download started');
  };

  const openRestoreModal = (backup: BackupFile) => {
    setSelectedBackup(backup);
    setRestoreModalOpen(true);
  };

  const openDeleteModal = (backup: BackupFile) => {
    if (backup.is_safety) {
      toast.error('Safety backups cannot be deleted');
      return;
    }
    setSelectedBackup(backup);
    setDeleteModalOpen(true);
  };

  const confirmRestore = async () => {
    if (!selectedBackup) return;

    try {
      const result = await api.backup.restore(selectedBackup.filename);
      toast.success(result.message);
      await loadSettings();
      await loadBackups();
      setRestoreModalOpen(false);
      setSelectedBackup(null);
    } catch (error) {
      console.error('Failed to restore backup:', error);
      toast.error('Failed to restore backup');
    }
  };

  const confirmDelete = async () => {
    if (!selectedBackup) return;

    try {
      const result = await api.backup.delete(selectedBackup.filename);
      toast.success(result.message);
      await loadBackups();
      setDeleteModalOpen(false);
      setSelectedBackup(null);
    } catch (error) {
      console.error('Failed to delete backup:', error);
      toast.error('Failed to delete backup');
    }
  };

  return (
    <>
      <div className="space-y-6">
        {loadingBackups ? (
          <div className="flex items-center justify-center py-12">
            <RefreshCw className="w-8 h-8 animate-spin text-primary" />
          </div>
        ) : backups ? (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Database Card */}
              <div className="bg-tide-surface rounded-lg p-6">
                <div className="flex items-center gap-3 mb-4">
                  <Database className="w-6 h-6 text-primary" />
                  <h2 className="text-xl font-semibold text-tide-text">Database</h2>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between items-start">
                    <span className="text-tide-text-muted">Path:</span>
                    <span className="font-mono text-tide-text text-right ml-4 break-all">{backups.stats.database_path}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-tide-text-muted">Size:</span>
                    <span className="font-mono text-tide-text">{(backups.stats.database_size / 1024 / 1024).toFixed(2)} MB</span>
                  </div>
                  <div className="flex justify-between items-start">
                    <span className="text-tide-text-muted">Last Modified:</span>
                    <span className="font-mono text-tide-text text-right ml-4">{new Date(backups.stats.database_modified).toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-tide-text-muted">Status:</span>
                    <span className={`font-mono ${backups.stats.database_exists ? 'text-green-400' : 'text-red-400'}`}>
                      {backups.stats.database_exists ? 'Exists' : 'Missing'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Backups Card */}
              <div className="bg-tide-surface rounded-lg p-6">
                <div className="flex items-center gap-3 mb-4">
                  <HardDrive className="w-6 h-6 text-primary" />
                  <h2 className="text-xl font-semibold text-tide-text">Backups</h2>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-tide-text-muted">Total Backups:</span>
                    <span className="font-mono text-tide-text">{backups.stats.total_backups}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-tide-text-muted">Total Size:</span>
                    <span className="font-mono text-tide-text">{(backups.stats.total_size / 1024 / 1024).toFixed(2)} MB</span>
                  </div>
                  <div className="flex justify-between items-start">
                    <span className="text-tide-text-muted">Directory:</span>
                    <span className="font-mono text-tide-text text-right ml-4 break-all">{backups.stats.backup_directory}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Backup Management Card */}
            <div className="bg-tide-surface rounded-lg p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-semibold text-tide-text">Backup Management</h2>
                <div className="flex gap-2">
                  <label className={`px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors cursor-pointer border border-tide-border ${
                    uploadingBackup ? 'opacity-50 cursor-not-allowed' : ''
                  }`}>
                    {uploadingBackup ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Upload className="w-5 h-5" />}
                    {uploadingBackup ? 'Uploading...' : 'Upload'}
                    <input
                      ref={fileInputRef}
                      accept=".json"
                      className="hidden"
                      type="file"
                      onChange={handleUploadBackup}
                      disabled={uploadingBackup}
                    />
                  </label>
                  <button
                    onClick={handleCreateBackup}
                    disabled={creatingBackup}
                    className="px-4 py-2 bg-primary hover:bg-primary/80 text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50"
                  >
                    {creatingBackup ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Plus className="w-5 h-5" />}
                    {creatingBackup ? 'Creating...' : 'Create Backup'}
                  </button>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-tide-surface/50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">Filename</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">Size</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-tide-text-muted uppercase tracking-wider">Created</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-tide-text-muted uppercase tracking-wider">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {backups.backups.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="px-4 py-8 text-center text-tide-text-muted">
                          No backups found. Create your first backup to get started.
                        </td>
                      </tr>
                    ) : (
                      backups.backups.map((backup) => (
                        <tr key={backup.filename} className="hover:bg-tide-surface/30 cursor-pointer transition-colors">
                          <td className="px-4 py-4 text-sm">
                            <div className="flex items-center gap-2">
                              {backup.is_safety && (
                                <span title="Safety Backup" className="flex-shrink-0">
                                  <Shield className="w-4 h-4 text-blue-400" />
                                </span>
                              )}
                              <div className="flex flex-col">
                                <span className="font-mono text-tide-text">{backup.filename}</span>
                                {backup.is_safety && (
                                  <span className="text-xs text-blue-400 mt-0.5">Protected Safety Backup</span>
                                )}
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-4 text-sm">
                            <div className="flex flex-col">
                              <span className="font-mono text-tide-text">{formatBytes(backup.size_bytes)}</span>
                              <span className="text-xs text-tide-text-muted mt-0.5">{backup.size_mb.toFixed(2)} MB</span>
                            </div>
                          </td>
                          <td className="px-4 py-4 text-sm">
                            <div className="flex flex-col">
                              <span className="text-tide-text">{formatDistanceToNow(new Date(backup.created), { addSuffix: true })}</span>
                              <span className="text-xs text-tide-text-muted mt-0.5">{new Date(backup.created).toLocaleString()}</span>
                            </div>
                          </td>
                          <td className="px-4 py-4 text-sm text-right">
                            <div className="flex items-center justify-end gap-2">
                              <button
                                onClick={() => handleDownloadBackup(backup.filename)}
                                className="p-2 text-primary hover:bg-primary/10 rounded transition-colors"
                                title="Download backup"
                              >
                                <Download className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => openRestoreModal(backup)}
                                className="p-2 text-orange-500 hover:bg-orange-500/10 rounded transition-colors"
                                title="Restore from backup"
                              >
                                <RotateCcw className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => openDeleteModal(backup)}
                                disabled={backup.is_safety}
                                className="p-2 text-red-500 hover:bg-red-500/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                title={backup.is_safety ? 'Safety backups cannot be deleted' : 'Delete backup'}
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Info Cards Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Configuration Tips */}
              <div className="bg-tide-surface/50 border border-tide-border rounded-lg p-4">
                <h3 className="text-sm font-semibold text-tide-text mb-3 flex items-center gap-2">
                  <Info className="w-4 h-4 text-blue-400" />
                  Configuration Tips
                </h3>
                <ul className="text-xs text-tide-text-muted space-y-1.5">
                  <li>• Create backups before major configuration changes</li>
                  <li>• Backups include all settings and container metadata</li>
                  <li>• Download backups to external storage for disaster recovery</li>
                  <li>• Restoring creates a safety backup of current settings first</li>
                  <li>• Regular backups help prevent data loss from misconfigurations</li>
                </ul>
              </div>

              {/* About Backups */}
              <div className="bg-tide-surface/50 border border-tide-border rounded-lg p-4">
                <h3 className="text-sm font-semibold text-tide-text mb-3 flex items-center gap-2">
                  <Info className="w-4 h-4 text-blue-400" />
                  About Backups
                </h3>
                <ul className="text-xs text-tide-text-muted space-y-1.5">
                  <li>• Backups are stored in <code className="bg-tide-surface/50 px-1 rounded text-tide-text">/data/backups</code> directory</li>
                  <li>• Backups include all TideWatch settings (credentials, configuration, policies)</li>
                  <li>• Restoring creates an automatic <span className="text-blue-400">safety backup</span> of current settings</li>
                  <li>• Safety backups are protected and cannot be deleted</li>
                  <li>• Container and update history data is not included in backups</li>
                  <li>• Encrypted values (API keys, tokens) remain encrypted in backups</li>
                </ul>
              </div>
            </div>
          </>
        ) : (
          <div className="bg-tide-surface rounded-lg p-12 text-center">
            <p className="text-tide-text-muted">Failed to load backup information</p>
            <button
              onClick={loadBackups}
              className="mt-4 px-4 py-2 bg-primary hover:bg-primary/80 text-tide-text rounded-lg text-sm"
            >
              Retry
            </button>
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {deleteModalOpen && selectedBackup && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-tide-surface rounded-lg max-w-md w-full p-6 border border-tide-border">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-tide-text">Delete Backup</h3>
              <button
                onClick={() => {
                  setDeleteModalOpen(false);
                  setSelectedBackup(null);
                }}
                className="text-tide-text-muted hover:text-tide-text transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
                <p className="text-red-400 text-sm font-medium mb-2">Warning: This action cannot be undone</p>
                <p className="text-tide-text text-sm">
                  Are you sure you want to delete this backup? Once deleted, it cannot be recovered.
                </p>
              </div>

              <div className="space-y-2 bg-tide-surface/50 rounded-lg p-4">
                <div className="flex justify-between text-sm">
                  <span className="text-tide-text-muted">Filename:</span>
                  <span className="text-tide-text font-mono">{selectedBackup.filename}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-tide-text-muted">Size:</span>
                  <span className="text-tide-text">{formatBytes(selectedBackup.size_bytes)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-tide-text-muted">Created:</span>
                  <span className="text-tide-text">{formatDistanceToNow(new Date(selectedBackup.created), { addSuffix: true })}</span>
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => {
                    setDeleteModalOpen(false);
                    setSelectedBackup(null);
                  }}
                  className="flex-1 px-4 py-2 bg-tide-surface-light hover:bg-tide-border-light text-tide-text rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDelete}
                  className="flex-1 px-4 py-2 bg-red-500 hover:bg-red-600 text-tide-text rounded-lg transition-colors"
                >
                  Delete Backup
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Restore Confirmation Modal */}
      {restoreModalOpen && selectedBackup && backups && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-tide-surface rounded-lg max-w-md w-full p-6 border border-tide-border">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-tide-text">Restore Backup</h3>
              <button
                onClick={() => {
                  setRestoreModalOpen(false);
                  setSelectedBackup(null);
                }}
                className="text-tide-text-muted hover:text-tide-text transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div className="bg-orange-500/10 border border-orange-500/20 rounded-lg p-4">
                <p className="text-orange-400 text-sm font-medium mb-2">Before Restoring</p>
                <p className="text-tide-text text-sm">
                  A safety backup of your current settings will be created automatically before restoring.
                  This ensures you can rollback if needed.
                </p>
              </div>

              <div className="space-y-3">
                <div className="bg-tide-surface/50 rounded-lg p-4">
                  <p className="text-xs text-tide-text-muted uppercase tracking-wide mb-2">Backup to Restore</p>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Filename:</span>
                      <span className="text-tide-text font-mono text-xs">{selectedBackup.filename}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Backup Size:</span>
                      <span className="text-tide-text">{formatBytes(selectedBackup.size_bytes)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Created:</span>
                      <span className="text-tide-text">{formatDistanceToNow(new Date(selectedBackup.created), { addSuffix: true })}</span>
                    </div>
                  </div>
                </div>

                <div className="bg-tide-surface/50 rounded-lg p-4">
                  <p className="text-xs text-tide-text-muted uppercase tracking-wide mb-2">Current Database</p>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Current Size:</span>
                      <span className="text-tide-text">{formatBytes(backups.stats.database_size)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-tide-text-muted">Last Modified:</span>
                      <span className="text-tide-text">
                        {formatDistanceToNow(new Date(backups.stats.database_modified), { addSuffix: true })}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => {
                    setRestoreModalOpen(false);
                    setSelectedBackup(null);
                  }}
                  className="flex-1 px-4 py-2 bg-tide-surface-light hover:bg-tide-border-light text-tide-text rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmRestore}
                  className="flex-1 px-4 py-2 bg-orange-500 hover:bg-orange-600 text-tide-text rounded-lg transition-colors"
                >
                  Restore Backup
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
