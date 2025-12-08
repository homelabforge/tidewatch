import { Radio, RefreshCw, CircleCheck, Info } from 'lucide-react';
import { HelpTooltip } from '../HelpTooltip';

interface GotifyConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: unknown) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function GotifyConfig({ settings, onSettingChange, onTextChange, onTest, testing, saving }: GotifyConfigProps) {
  return (
    <div className="bg-tide-surface rounded-lg p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <Radio className="w-6 h-6 text-teal-500" />
          <div>
            <h2 className="text-xl font-semibold text-tide-text">Gotify Configuration</h2>
            <p className="text-sm text-tide-text-muted mt-0.5">Self-hosted notification server</p>
          </div>
        </div>
        <HelpTooltip content="Gotify is a self-hosted push notification server. Requires your own Gotify instance. Get app token from Gotify admin panel." />
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <label className="block text-sm font-medium text-tide-text">Enable Gotify</label>
            <p className="text-xs text-tide-text-muted mt-1">Send notifications via Gotify</p>
          </div>
          <button
            type="button"
            onClick={() => onSettingChange('gotify_enabled', !settings.gotify_enabled)}
            disabled={saving}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
              settings.gotify_enabled ? 'bg-teal-500' : 'bg-red-500'
            }`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              settings.gotify_enabled ? 'translate-x-6' : 'translate-x-1'
            }`}></span>
          </button>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-sm font-medium text-tide-text">Server URL</span>
            <p className="text-xs text-tide-text-muted mb-2">Your Gotify server URL</p>
            <input
              placeholder="https://gotify.example.com"
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
              type="text"
              value={String(settings.gotify_server || '')}
              onChange={(e) => onTextChange('gotify_server', e.target.value)}
              disabled={saving}
            />
          </label>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-sm font-medium text-tide-text">App Token</span>
            <p className="text-xs text-tide-text-muted mb-2">Application token from Gotify</p>
            <input
              placeholder="A..."
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
              type="password"
              value={String(settings.gotify_token || '')}
              onChange={(e) => onTextChange('gotify_token', e.target.value)}
              disabled={saving}
            />
          </label>
        </div>

        <button
          type="button"
          onClick={onTest}
          disabled={testing || !settings.gotify_enabled}
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
                <p className="font-medium text-tide-text mb-1">Getting Started</p>
                <p>Create an application in your Gotify admin panel and copy the app token. Supports Android client.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
