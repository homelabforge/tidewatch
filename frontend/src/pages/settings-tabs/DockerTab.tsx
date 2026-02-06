import { useState } from 'react';
import { Server, RefreshCw, CircleCheck, Cpu, Star, FolderOpen, Scan, FileText, ChevronDown, ChevronRight, Settings as SettingsIcon } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '../../services/api';
import type { SettingCategory } from '../../types';
import { HelpTooltip } from '../../components/HelpTooltip';

interface DockerTabProps {
  settings: Record<string, unknown>;
  saving: boolean;
  updateSetting: (key: string, value: unknown, updateState?: boolean) => Promise<void>;
  handleTextChange: (key: string, value: string) => void;
  categories: SettingCategory[];
}

export default function DockerTab({ settings, saving, updateSetting, handleTextChange, categories }: DockerTabProps) {
  const [testingDockerHub, setTestingDockerHub] = useState(false);
  const [testingGHCR, setTestingGHCR] = useState(false);
  const [scanningProjects, setScanningProjects] = useState(false);
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());

  const toggleCategory = (category: string) => {
    setCollapsedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  const getCategoryIcon = (category: string) => {
    const icons: Record<string, typeof SettingsIcon> = {
      docker: Server,
      registry: Server,
    };
    return icons[category] || SettingsIcon;
  };

  const getCategoryTitle = (category: string) => {
    const titles: Record<string, string> = {
      docker: 'Docker Settings',
      registry: 'Registry Authentication',
    };
    return titles[category] || category.charAt(0).toUpperCase() + category.slice(1);
  };

  const handleTestConnection = async (type: 'dockerhub' | 'ghcr') => {
    const setTestingState = type === 'dockerhub' ? setTestingDockerHub : setTestingGHCR;
    const testFunction = type === 'dockerhub' ? api.settings.testDockerHub : api.settings.testGHCR;

    try {
      setTestingState(true);
      const result = await testFunction();

      if (result.success) {
        toast.success(result.message, {
          description: result.details ? Object.entries(result.details).map(([k, v]) => `${k}: ${v}`).join(', ') : undefined,
        });
      } else {
        toast.error(result.message, {
          description: result.details ? Object.entries(result.details).map(([k, v]) => `${k}: ${v}`).join(', ') : undefined,
        });
      }
    } catch (error) {
      console.error(`Failed to test ${type} connection:`, error);
      toast.error(`Failed to test ${type} connection`);
    } finally {
      setTestingState(false);
    }
  };

  const handleScanMyProjects = async () => {
    try {
      setScanningProjects(true);
      const response = await api.containers.scanMyProjects();

      if (response.success) {
        const { added, updated, skipped, errors } = response.results;
        toast.success('Project scan completed', {
          description: `Added: ${added}, Updated: ${updated}, Skipped: ${skipped}${errors ? `, Errors: ${errors.length}` : ''}`,
        });
      } else {
        toast.error('Failed to scan projects');
      }
    } catch (error) {
      console.error('Failed to scan my projects:', error);
      toast.error('Failed to scan my projects');
    } finally {
      setScanningProjects(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Category-based view if categories available */}
      {categories.length > 0 && (
        <div className="space-y-4">
          {categories
            .filter((cat) => cat.category === 'docker' || cat.category === 'registry')
            .map((category) => {
              const Icon = getCategoryIcon(category.category);
              const isCollapsed = collapsedCategories.has(category.category);

              return (
                <div key={category.category} className="bg-tide-surface/50 rounded-lg border border-tide-border">
                  {/* Category Header */}
                  <button
                    onClick={() => toggleCategory(category.category)}
                    className="w-full flex items-center justify-between p-4 hover:bg-tide-surface/70 transition-colors rounded-lg"
                  >
                    <div className="flex items-center gap-3">
                      <Icon className="w-5 h-5 text-teal-400" />
                      <div className="text-left">
                        <h3 className="text-sm font-semibold text-tide-text">{getCategoryTitle(category.category)}</h3>
                        <p className="text-xs text-tide-text-muted mt-0.5">
                          {category.settings.length} {category.settings.length === 1 ? 'setting' : 'settings'}
                        </p>
                      </div>
                    </div>
                    {isCollapsed ? (
                      <ChevronRight className="w-5 h-5 text-tide-text-muted" />
                    ) : (
                      <ChevronDown className="w-5 h-5 text-tide-text-muted" />
                    )}
                  </button>

                  {/* Category Content */}
                  {!isCollapsed && (
                    <div className="p-4 pt-0 space-y-4">
                      {category.settings.map((setting) => (
                        <div key={setting.key} className="bg-tide-surface/50 rounded-lg p-4">
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1">
                              <label className="block text-sm font-medium text-tide-text">
                                {setting.key.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                                {setting.encrypted && <span className="text-xs text-tide-text-muted bg-tide-surface px-1.5 py-0.5 rounded ml-2">Encrypted</span>}
                              </label>
                              {setting.description && (
                                <p className="text-xs text-tide-text-muted mt-1">{setting.description}</p>
                              )}
                            </div>
                            <div className="flex-shrink-0">
                              {/* Boolean Toggle */}
                              {typeof settings[setting.key] === 'boolean' && (
                                <button
                                  type="button"
                                  onClick={() => updateSetting(setting.key, !settings[setting.key])}
                                  disabled={saving}
                                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                                    settings[setting.key] ? 'bg-teal-500' : 'bg-red-500'
                                  }`}
                                >
                                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                    settings[setting.key] ? 'translate-x-6' : 'translate-x-1'
                                  }`}></span>
                                </button>
                              )}
                              {/* Text/Number Input */}
                              {typeof settings[setting.key] !== 'boolean' && (
                                <input
                                  type={setting.encrypted ? 'password' : typeof settings[setting.key] === 'number' ? 'number' : 'text'}
                                  value={String(settings[setting.key] || '')}
                                  onChange={(e) => {
                                    const value = typeof settings[setting.key] === 'number'
                                      ? parseInt(e.target.value) || 0
                                      : e.target.value;
                                    handleTextChange(setting.key, String(value));
                                  }}
                                  disabled={saving}
                                  className="w-48 bg-tide-surface text-tide-text text-sm rounded px-3 py-1.5 border border-tide-border-light focus:border-teal-500 focus:outline-none"
                                />
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      )}

      {/* Docker Settings Cards */}
      {categories.length === 0 && (
        <div className="columns-1 xl:columns-2 gap-6" style={{ columnGap: '1.5rem' }}>
          {/* Registry Authentication Card */}
          <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <Cpu className="w-6 h-6 text-teal-500" />
                <div>
                  <h2 className="text-xl font-semibold text-tide-text">Registry Authentication</h2>
                  <p className="text-sm text-tide-text-muted mt-0.5">Configure registry credentials</p>
                </div>
              </div>
              <HelpTooltip content="Registry credentials are optional but recommended to avoid rate limits. Docker Hub tokens can be created at hub.docker.com/settings/security. GitHub PATs need read:packages scope for GHCR access. Credentials are stored encrypted in the database." />
            </div>

            <div className="space-y-6">
              {/* Docker Hub Section */}
              <div>
                <h3 className="text-sm font-semibold text-tide-text mb-3">Docker Hub</h3>
                <div className="space-y-3">
                  <div>
                    <label className="block text-sm font-medium text-tide-text mb-2">
                      Username
                    </label>
                    <input
                      type="text"
                      value={String(settings.dockerhub_username || '')}
                      onChange={(e) => handleTextChange('dockerhub_username', e.target.value)}
                      disabled={saving}
                      className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                    />
                  </div>

                  <div className="flex items-center gap-2">
                    <div className="flex-1">
                      <label className="block text-sm font-medium text-tide-text mb-2 flex items-center gap-2">
                        Token
                        <span className="text-xs text-tide-text-muted bg-tide-surface px-1.5 py-0.5 rounded">Encrypted</span>
                      </label>
                      <input
                        type="password"
                        value={String(settings.dockerhub_token || '')}
                        onChange={(e) => handleTextChange('dockerhub_token', e.target.value)}
                        disabled={saving}
                        className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => handleTestConnection('dockerhub')}
                      disabled={testingDockerHub || saving}
                      className="mt-7 px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50 border border-tide-border"
                    >
                      {testingDockerHub ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CircleCheck className="w-4 h-4" />}
                      {testingDockerHub ? 'Testing...' : 'Test Connection'}
                    </button>
                  </div>
                </div>
              </div>

              {/* GitHub Container Registry Section */}
              <div>
                <h3 className="text-sm font-semibold text-tide-text mb-3">GitHub (GHCR)</h3>
                <div className="space-y-3">
                  <div>
                    <label className="block text-sm font-medium text-tide-text mb-2">
                      Username
                    </label>
                    <input
                      type="text"
                      value={String(settings.ghcr_username || '')}
                      onChange={(e) => handleTextChange('ghcr_username', e.target.value)}
                      disabled={saving}
                      className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                    />
                  </div>

                  <div className="flex items-center gap-2">
                    <div className="flex-1">
                      <label className="block text-sm font-medium text-tide-text mb-2 flex items-center gap-2">
                        Token
                        <span className="text-xs text-tide-text-muted bg-tide-surface px-1.5 py-0.5 rounded">Encrypted</span>
                      </label>
                      <input
                        type="password"
                        value={String(settings.ghcr_token || '')}
                        onChange={(e) => handleTextChange('ghcr_token', e.target.value)}
                        disabled={saving}
                        className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => handleTestConnection('ghcr')}
                      disabled={testingGHCR || saving}
                      className="mt-7 px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50 border border-tide-border"
                    >
                      {testingGHCR ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CircleCheck className="w-4 h-4" />}
                      {testingGHCR ? 'Testing...' : 'Test Connection'}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Docker Configuration Card */}
          <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <Server className="w-6 h-6 text-teal-500" />
                <div>
                  <h2 className="text-xl font-semibold text-tide-text">Docker Configuration</h2>
                  <p className="text-sm text-tide-text-muted mt-0.5">Configure Docker daemon connection</p>
                </div>
              </div>
              <HelpTooltip content="Docker socket enables TideWatch to monitor and update containers. Compose directory should contain all your docker-compose.yml files. The compose command template supports placeholders: {compose_file}, {env_file}, {service}." />
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  Compose Directory
                </label>
                <input
                  type="text"
                  value={String(settings.compose_directory || '')}
                  onChange={(e) => handleTextChange('compose_directory', e.target.value)}
                  disabled={saving}
                  placeholder="/compose"
                  className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                />
                <p className="text-xs text-tide-text-muted mt-1">
                  Directory containing docker-compose files
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  Docker Compose Command
                </label>
                <input
                  type="text"
                  value={String(settings.docker_compose_command || '')}
                  onChange={(e) => handleTextChange('docker_compose_command', e.target.value)}
                  disabled={saving}
                  placeholder='docker compose -p homelab -f /compose/base.yml -f /compose/backup.yml'
                  className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                />
                <p className="text-xs text-tide-text-muted mt-1">
                  Docker compose command template. Use {'{compose_file}'}, {'{env_file}'}, {'{service}'} placeholders
                </p>
              </div>
            </div>
          </div>

          {/* My Projects Configuration Card */}
          <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <Star className="w-6 h-6 text-yellow-500" />
                <div>
                  <h2 className="text-xl font-semibold text-tide-text">My Projects Configuration</h2>
                  <p className="text-sm text-tide-text-muted mt-0.5">Manage dev containers and dependency tracking</p>
                </div>
              </div>
              <HelpTooltip content="My Projects groups dev containers separately on the Dashboard. Auto-scan discovers containers from {projects_directory}/*/compose.yaml files. Dependencies tab scans package.json, pyproject.toml, etc. You can also manually mark any container as 'My Project' in its Settings tab." />
            </div>

            <div className="space-y-4">
              {/* Enable My Projects Feature */}
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-sm font-medium text-tide-text">
                    Enable My Projects
                  </label>
                  <p className="text-xs text-tide-text-muted mt-1">
                    Show My Project toggle and Dependencies tab for dev containers
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => updateSetting('my_projects_enabled', !settings.my_projects_enabled)}
                  disabled={saving}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                    settings.my_projects_enabled ? 'bg-teal-500' : 'bg-red-500'
                  }`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.my_projects_enabled ? 'translate-x-6' : 'translate-x-1'
                  }`}></span>
                </button>
              </div>

              {/* Projects Directory */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2 flex items-center gap-2">
                  <FolderOpen className="w-4 h-4" />
                  Projects Directory
                </label>
                <input
                  type="text"
                  value={String(settings.projects_directory || '')}
                  onChange={(e) => handleTextChange('projects_directory', e.target.value)}
                  disabled={saving || !settings.my_projects_enabled}
                  placeholder="/projects"
                  className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none disabled:opacity-50"
                />
                <p className="text-xs text-tide-text-muted mt-1">
                  Directory containing project source code (mounted into Tidewatch)
                </p>
              </div>

              {/* Auto-Scan Enable/Disable */}
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-sm font-medium text-tide-text">
                    Auto-Scan Projects
                  </label>
                  <p className="text-xs text-tide-text-muted mt-1">
                    Automatically discover dev containers on startup
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => updateSetting('my_projects_auto_scan', !settings.my_projects_auto_scan)}
                  disabled={saving || !settings.my_projects_enabled}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none disabled:opacity-50 ${
                    settings.my_projects_auto_scan ? 'bg-teal-500' : 'bg-red-500'
                  }`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.my_projects_auto_scan ? 'translate-x-6' : 'translate-x-1'
                  }`}></span>
                </button>
              </div>

              {/* Docker Compose Command for My Projects */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  My Projects Docker Compose Command
                </label>
                <input
                  type="text"
                  value={String(settings.my_projects_compose_command || '')}
                  onChange={(e) => handleTextChange('my_projects_compose_command', e.target.value)}
                  disabled={saving || !settings.my_projects_enabled}
                  placeholder='docker compose'
                  className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none disabled:opacity-50"
                />
                <p className="text-xs text-tide-text-muted mt-1">
                  Simple Docker Compose command for dev containers (use {'{compose_file}'}, {'{service}'} placeholders)
                </p>
              </div>

              {/* Manual Scan Button */}
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleScanMyProjects}
                  disabled={scanningProjects || !settings.my_projects_enabled}
                  className="w-full px-4 py-2 bg-teal-600 hover:bg-teal-700 text-tide-text rounded-lg font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {scanningProjects ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      Scanning Projects...
                    </>
                  ) : (
                    <>
                      <Scan className="w-4 h-4" />
                      Scan Projects Now
                    </>
                  )}
                </button>
                <p className="text-xs text-tide-text-muted mt-2 text-center">
                  Manually scan {String(settings.projects_directory || '/projects')} for dev containers
                </p>
              </div>
            </div>

          </div>

          {/* Dockerfile Dependencies Configuration Card */}
          <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <FileText className="w-6 h-6 text-primary" />
                <div>
                  <h2 className="text-xl font-semibold text-tide-text">Dockerfile Dependency Tracking</h2>
                  <p className="text-sm text-tide-text-muted mt-0.5">Automatically track base and build images in Dockerfiles</p>
                </div>
              </div>
              <HelpTooltip content="Scans FROM statements in Dockerfiles to track base and build images, including multi-stage builds. Checks for updated image tags on schedule. View Dockerfile dependencies in the Dependencies tab (My Projects). Notifications sent when updates are available." />
            </div>

            <div className="space-y-4">
              {/* Auto-Scan Dockerfiles */}
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-sm font-medium text-tide-text">
                    Auto-Scan Dockerfiles
                  </label>
                  <p className="text-xs text-tide-text-muted mt-1">
                    Automatically scan Dockerfiles when containers are added
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => updateSetting('dockerfile_auto_scan', !settings.dockerfile_auto_scan)}
                  disabled={saving}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                    settings.dockerfile_auto_scan ? 'bg-teal-500' : 'bg-red-500'
                  }`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.dockerfile_auto_scan ? 'translate-x-6' : 'translate-x-1'
                  }`}></span>
                </button>
              </div>

              {/* Dockerfile Scan Schedule */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  Update Check Schedule
                </label>
                <select
                  value={String(settings.dockerfile_scan_schedule || 'daily')}
                  onChange={(e) => updateSetting('dockerfile_scan_schedule', e.target.value)}
                  disabled={saving}
                  className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none disabled:opacity-50"
                >
                  <option value="disabled">Disabled</option>
                  <option value="daily">Daily (3 AM)</option>
                  <option value="weekly">Weekly (Sunday 3 AM)</option>
                </select>
                <p className="text-xs text-tide-text-muted mt-1">
                  How often to check for updated base/build images
                </p>
              </div>

              {/* Manual Check All Button */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-2">
                  Manual Update Check
                </label>
                <button
                  onClick={async () => {
                    try {
                      const result = await api.containers.checkAllDockerfileUpdates();
                      toast.success(`Checked ${result.total_scanned} Dockerfiles, found ${result.updates_found} updates`);
                    } catch {
                      toast.error('Failed to check Dockerfile updates');
                    }
                  }}
                  className="px-4 py-2 bg-primary hover:bg-primary-dark text-tide-text rounded-lg font-medium transition-colors flex items-center gap-2"
                >
                  <RefreshCw size={16} />
                  Check All Dockerfile Updates
                </button>
                <p className="text-xs text-tide-text-muted mt-1">
                  Manually trigger an update check for all tracked Dockerfiles
                </p>
              </div>
            </div>

          </div>
        </div>
      )}
    </div>
  );
}
