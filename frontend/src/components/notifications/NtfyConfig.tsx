import { Bell, RefreshCw, CircleCheck, Info } from 'lucide-react';
import { HelpTooltip } from '../HelpTooltip';

interface NtfyConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: unknown) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function NtfyConfig({ settings, onSettingChange, onTextChange, onTest, testing, saving }: NtfyConfigProps) {
  return (
    <div className="bg-tide-surface rounded-lg p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <Bell className="w-6 h-6 text-teal-500" />
          <div>
            <h2 className="text-xl font-semibold text-tide-text">ntfy Configuration</h2>
            <p className="text-sm text-tide-text-muted mt-0.5">Lightweight push notifications</p>
          </div>
        </div>
        <HelpTooltip content="ntfy is a simple pub-sub notification service. Self-hosted or use ntfy.sh. Supports Android, iOS, and web clients." />
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <label className="block text-sm font-medium text-tide-text">Enable ntfy</label>
            <p className="text-xs text-tide-text-muted mt-1">Send notifications via ntfy</p>
          </div>
          <button
            type="button"
            onClick={() => onSettingChange('ntfy_enabled', !settings.ntfy_enabled)}
            disabled={saving}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
              settings.ntfy_enabled ? 'bg-teal-500' : 'bg-red-500'
            }`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              settings.ntfy_enabled ? 'translate-x-6' : 'translate-x-1'
            }`}></span>
          </button>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-sm font-medium text-tide-text">Server URL</span>
            <p className="text-xs text-tide-text-muted mb-2">ntfy server (e.g., https://ntfy.sh)</p>
            <input
              placeholder="https://ntfy.sh"
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
              type="text"
              value={String(settings.ntfy_server || '')}
              onChange={(e) => onTextChange('ntfy_server', e.target.value)}
              disabled={saving}
            />
          </label>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-sm font-medium text-tide-text">Topic</span>
            <p className="text-xs text-tide-text-muted mb-2">Unique topic name for your notifications</p>
            <input
              placeholder="my-tidewatch-notifications"
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
              type="text"
              value={String(settings.ntfy_topic || '')}
              onChange={(e) => onTextChange('ntfy_topic', e.target.value)}
              disabled={saving}
            />
          </label>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-sm font-medium text-tide-text">API Token (Optional)</span>
            <p className="text-xs text-tide-text-muted mb-2">For authenticated ntfy servers</p>
            <input
              placeholder="tk_..."
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
              type="password"
              value={String(settings.ntfy_token || '')}
              onChange={(e) => onTextChange('ntfy_token', e.target.value)}
              disabled={saving}
            />
          </label>
        </div>

        <button
          type="button"
          onClick={onTest}
          disabled={testing || !settings.ntfy_enabled}
          className="px-4 py-2 bg-tide-surface hover:bg-tide-surface-light text-tide-text rounded-lg text-sm flex items-center gap-2 transition-colors disabled:opacity-50 border border-tide-border"
        >
          {testing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CircleCheck className="w-4 h-4" />}
          {testing ? 'Testing...' : 'Test Connection'}
        </button>

        <div className="pt-4 border-t border-tide-border">
          <div className="p-3 bg-blue-500/10 rounded-lg border border-blue-500/30">
            <div className="flex items-start gap-2">
              <Info className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
              <div className="text-xs text-tide-text-muted">
                <p className="font-medium text-tide-text mb-1">Security Note</p>
                <p>Use a unique, hard-to-guess topic name. Anyone with the topic name can receive your notifications.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
