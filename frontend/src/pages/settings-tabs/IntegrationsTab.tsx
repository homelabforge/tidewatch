import { useState } from 'react';
import { Plug, RefreshCw, CircleCheck, Info, ChevronDown, ChevronRight, Settings as SettingsIcon } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '../../services/api';
import type { SettingCategory } from '../../types';
import { HelpTooltip } from '../../components/HelpTooltip';

interface IntegrationsTabProps {
  settings: Record<string, unknown>;
  saving: boolean;
  updateSetting: (key: string, value: unknown, updateState?: boolean) => Promise<void>;
  handleTextChange: (key: string, value: string) => void;
  categories: SettingCategory[];
}

export default function IntegrationsTab({ settings, saving, updateSetting, handleTextChange, categories }: IntegrationsTabProps) {
  const [testingVulnForge, setTestingVulnForge] = useState(false);
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
      integrations: Plug,
    };
    return icons[category] || SettingsIcon;
  };

  const getCategoryTitle = (category: string) => {
    const titles: Record<string, string> = {
      integrations: 'Integrations',
    };
    return titles[category] || category.charAt(0).toUpperCase() + category.slice(1);
  };

  const handleTestConnection = async () => {
    try {
      setTestingVulnForge(true);
      const result = await api.settings.testVulnForge();

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
      console.error('Failed to test VulnForge connection:', error);
      toast.error('Failed to test VulnForge connection');
    } finally {
      setTestingVulnForge(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Category-based view if categories available */}
      {categories.length > 0 && (
        <div className="space-y-4">
          {categories
            .filter((cat) => cat.category === 'integrations')
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

      {/* Integrations Cards */}
      {categories.length === 0 && (
        <div className="columns-1 xl:columns-2 gap-6" style={{ columnGap: '1.5rem' }}>
          {/* VulnForge Integration Card */}
          <div className="bg-tide-surface rounded-lg p-6 break-inside-avoid mb-6 border border-tide-border">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <Plug className="w-6 h-6 text-teal-500" />
                <div>
                  <h2 className="text-xl font-semibold text-tide-text">VulnForge Integration</h2>
                  <p className="text-sm text-tide-text-muted mt-0.5">Vulnerability scanning with authentication</p>
                </div>
              </div>
              <HelpTooltip content="VulnForge URL should point to your VulnForge instance (e.g., http://vulnforge:8787). API key authentication is required for external access. Use 'None' for internal/trusted network access only. Test connection after changing authentication settings." />
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-sm font-medium text-tide-text">
                    Enable Integration
                  </label>
                  <p className="text-xs text-tide-text-muted mt-1">
                    Enable VulnForge vulnerability scanning
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => updateSetting('vulnforge_enabled', !settings.vulnforge_enabled)}
                  disabled={saving}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                    settings.vulnforge_enabled ? 'bg-teal-500' : 'bg-red-500'
                  }`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.vulnforge_enabled ? 'translate-x-6' : 'translate-x-1'
                  }`}></span>
                </button>
              </div>

              <div className="flex items-start gap-2">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-tide-text mb-2">
                    VulnForge URL
                  </label>
                  <input
                    type="text"
                    value={String(settings.vulnforge_url || '')}
                    onChange={(e) => handleTextChange('vulnforge_url', e.target.value)}
                    disabled={saving}
                    placeholder="http://vulnforge:8787"
                    className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                  />
                  <p className="text-xs text-tide-text-muted mt-1">
                    URL to VulnForge instance
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={testingVulnForge}
                  className="mt-7 px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50 border border-tide-border"
                >
                  {testingVulnForge ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CircleCheck className="w-4 h-4" />}
                  {testingVulnForge ? 'Testing...' : 'Test Connection'}
                </button>
              </div>

              {/* Authentication Section */}
              <div>
                <label className="block text-sm font-medium text-tide-text mb-3">
                  <div className="flex items-center gap-2">
                    <Info className="w-4 h-4 text-teal-500" />
                    Authentication
                  </div>
                </label>
                <p className="text-xs text-tide-text-muted mb-3">
                  Select authentication method
                </p>

                {/* Auth Type Selector */}
                <div className="grid grid-cols-2 gap-2 mb-4">
                  <button
                    type="button"
                    onClick={() => updateSetting('vulnforge_auth_type', 'none')}
                    disabled={saving}
                    className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                      (settings.vulnforge_auth_type || 'none') === 'none'
                        ? 'bg-teal-500 text-tide-text'
                        : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
                    }`}
                  >
                    None
                  </button>
                  <button
                    type="button"
                    onClick={() => updateSetting('vulnforge_auth_type', 'api_key')}
                    disabled={saving}
                    className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                      settings.vulnforge_auth_type === 'api_key'
                        ? 'bg-teal-500 text-tide-text'
                        : 'bg-tide-surface text-tide-text hover:bg-tide-surface-light'
                    }`}
                  >
                    API Key
                  </button>
                </div>

                {/* Auth Info Message */}
                {(settings.vulnforge_auth_type || 'none') === 'none' && (
                  <div className="bg-teal-500/10 border border-teal-500/30 rounded p-3">
                    <p className="text-xs text-teal-400">
                      No authentication configured. VulnForge will be accessed without credentials.
                    </p>
                  </div>
                )}

                {/* API Key Field */}
                {settings.vulnforge_auth_type === 'api_key' && (
                  <div className="mt-3">
                    <label className="block text-sm font-medium text-tide-text mb-2">
                      API Key
                    </label>
                    <input
                      type="password"
                      value={String(settings.vulnforge_api_key || '')}
                      onChange={(e) => handleTextChange('vulnforge_api_key', e.target.value)}
                      disabled={saving}
                      className="w-full bg-tide-surface text-tide-text rounded px-3 py-2 border border-tide-border-light focus:border-blue-500 focus:outline-none"
                    />
                  </div>
                )}
              </div>

              {/* About VulnForge Link */}
              <div className="pt-4 border-t border-tide-border flex items-center gap-2">
                <Info className="w-4 h-4 text-teal-500" />
                <span className="text-sm text-tide-text">Learn more:</span>
                <HelpTooltip content="VulnForge scans container images for security vulnerabilities. Provides CVE tracking and vulnerability data comparisons. Enables security-driven update policies. Integration is optional but highly recommended for production use. Works with Docker Hub, GHCR, and custom registries." />
                <span className="text-sm text-tide-text-muted">About VulnForge</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
