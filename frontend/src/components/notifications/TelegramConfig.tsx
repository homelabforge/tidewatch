import { AtSign, RefreshCw, CircleCheck, Info, ExternalLink } from 'lucide-react';
import { HelpTooltip } from '../HelpTooltip';

interface TelegramConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: unknown) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function TelegramConfig({ settings, onSettingChange, onTextChange, onTest, testing, saving }: TelegramConfigProps) {
  return (
    <div className="bg-tide-surface rounded-lg p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <AtSign className="w-6 h-6 text-teal-500" />
          <div>
            <h2 className="text-xl font-semibold text-tide-text">Telegram Configuration</h2>
            <p className="text-sm text-tide-text-muted mt-0.5">Secure messaging notifications</p>
          </div>
        </div>
        <HelpTooltip content="Send notifications via Telegram bot. Create a bot with @BotFather and get your chat ID." />
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <label className="block text-sm font-medium text-tide-text">Enable Telegram</label>
            <p className="text-xs text-tide-text-muted mt-1">Send notifications via Telegram</p>
          </div>
          <button
            type="button"
            onClick={() => onSettingChange('telegram_enabled', !settings.telegram_enabled)}
            disabled={saving}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
              settings.telegram_enabled ? 'bg-teal-500' : 'bg-red-500'
            }`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              settings.telegram_enabled ? 'translate-x-6' : 'translate-x-1'
            }`}></span>
          </button>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-sm font-medium text-tide-text">Bot Token</span>
            <p className="text-xs text-tide-text-muted mb-2">Token from @BotFather</p>
            <input
              placeholder="123456789:ABC..."
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
              type="password"
              value={String(settings.telegram_bot_token || '')}
              onChange={(e) => onTextChange('telegram_bot_token', e.target.value)}
              disabled={saving}
            />
          </label>
        </div>

        <div className="space-y-2">
          <label className="block">
            <span className="text-sm font-medium text-tide-text">Chat ID</span>
            <p className="text-xs text-tide-text-muted mb-2">Your chat or group ID</p>
            <input
              placeholder="-100..."
              className="w-full px-3 py-2 bg-tide-surface border border-tide-border rounded-lg text-tide-text focus:outline-none focus:ring-2 focus:ring-teal-500"
              type="text"
              value={String(settings.telegram_chat_id || '')}
              onChange={(e) => onTextChange('telegram_chat_id', e.target.value)}
              disabled={saving}
            />
          </label>
        </div>

        <button
          type="button"
          onClick={onTest}
          disabled={testing || !settings.telegram_enabled}
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
                <p className="mb-2">1. Message @BotFather to create a bot and get token</p>
                <p className="mb-2">2. Message @userinfobot to get your chat ID</p>
                <a
                  href="https://core.telegram.org/bots#how-do-i-create-a-bot"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-teal-400 hover:text-teal-300"
                >
                  <ExternalLink className="w-3 h-3" />
                  Telegram Bot Guide
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
