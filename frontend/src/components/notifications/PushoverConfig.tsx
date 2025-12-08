import { Send, RefreshCw, CircleCheck, Info, ExternalLink } from 'lucide-react';
import { HelpTooltip } from '../HelpTooltip';

interface PushoverConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: unknown) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function PushoverConfig({ settings, onSettingChange, onTextChange, onTest, testing, saving }: PushoverConfigProps) {
  return (
    <div className="bg-tide-surface rounded-lg p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <Send className="w-6 h-6 text-teal-500" />
          <div>
            <h2 className="text-xl font-semibold text-tide-text">Pushover Configuration</h2>
            <p className="text-sm text-tide-text-muted mt-0.5">Cross-platform push notifications</p>
          </div>
        </div>
        <HelpTooltip content="Pushover is a paid service ($5 one-time) for reliable push notifications. Works on iOS, Android, and desktop." />
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <label className="block text-sm font-medium text-tide-text">Enable Pushover</label>
            <p className="text-xs text-tide-text-muted mt-1">Send notifications via Pushover</p>
          </div>
          <button
            type="button"
            onClick={() => onSettingChange('pushover_enabled', !settings.pushover_enabled)}
            disabled={saving}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
              settings.pushover_enabled ? 'bg-teal-500' : 'bg-red-500'
            }`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              settings.pushover_enabled ? 'translate-x-6' : 'translate-x-1'
            }`}></span>
          </button>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-sm font-medium text-tide-text">User Key</span>
            <p className="text-xs text-tide-text-muted mb-2">Your Pushover user key</p>
            <input
              placeholder="u..."
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
              type="password"
              value={String(settings.pushover_user_key || '')}
              onChange={(e) => onTextChange('pushover_user_key', e.target.value)}
              disabled={saving}
            />
          </label>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-sm font-medium text-tide-text">API Token</span>
            <p className="text-xs text-tide-text-muted mb-2">Application API token from Pushover</p>
            <input
              placeholder="a..."
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
              type="password"
              value={String(settings.pushover_api_token || '')}
              onChange={(e) => onTextChange('pushover_api_token', e.target.value)}
              disabled={saving}
            />
          </label>
        </div>

        <button
          type="button"
          onClick={onTest}
          disabled={testing || !settings.pushover_enabled}
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
                <p className="mb-2">Register at pushover.net and create an application to get your API token.</p>
                <a
                  href="https://pushover.net"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-teal-400 hover:text-teal-300"
                >
                  <ExternalLink className="w-3 h-3" />
                  pushover.net
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
