import { useEffect, useRef, useState, useCallback } from 'react';
import { toast } from 'sonner';

export type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting';

interface EventStreamEvent {
  type: string;
  data?: Record<string, unknown>;
  timestamp?: string;
}

interface UseEventStreamOptions {
  onUpdateAvailable?: (data: Record<string, unknown>) => void;
  onUpdateApplied?: (data: Record<string, unknown>) => void;
  onUpdateFailed?: (data: Record<string, unknown>) => void;
  onContainerRestarted?: (data: Record<string, unknown>) => void;
  onHealthCheckFailed?: (data: Record<string, unknown>) => void;
  enableToasts?: boolean;
}

const API_BASE = import.meta.env.VITE_API_URL || '';
const SSE_ENDPOINT = `${API_BASE}/api/v1/events/stream`;
const MAX_RECONNECT_DELAY = 30000; // 30 seconds
const INITIAL_RECONNECT_DELAY = 1000; // 1 second

export function useEventStream(options: UseEventStreamOptions = {}) {
  const {
    onUpdateAvailable,
    onUpdateApplied,
    onUpdateFailed,
    onContainerRestarted,
    onHealthCheckFailed,
    enableToasts = true,
  } = options;

  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected');
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY);
  const isMountedRef = useRef(true);
  const connectRef = useRef<() => void>();

  const handleEvent = useCallback((event: EventStreamEvent) => {
    const { type, data } = event;

    switch (type) {
      case 'connected':
        // Initial connection confirmation
        break;

      case 'update_available':
        onUpdateAvailable?.(data);
        if (enableToasts) {
          toast.info(`Update available for ${data?.container_name || 'container'}`, {
            description: `New version: ${data?.new_version || 'unknown'}`,
          });
        }
        break;

      case 'update_applied':
        onUpdateApplied?.(data);
        if (enableToasts) {
          toast.success(`Update applied to ${data?.container_name || 'container'}`, {
            description: `Updated to version ${data?.new_version || 'unknown'}`,
          });
        }
        break;

      case 'update_failed':
        onUpdateFailed?.(data);
        if (enableToasts) {
          toast.error(`Update failed for ${data?.container_name || 'container'}`, {
            description: data?.error || 'Unknown error occurred',
          });
        }
        break;

      case 'container_restarted':
        onContainerRestarted?.(data);
        if (enableToasts) {
          toast.info(`Container restarted: ${data?.container_name || 'unknown'}`, {
            description: `Restart reason: ${data?.reason || 'manual'}`,
          });
        }
        break;

      case 'health_check_failed':
        onHealthCheckFailed?.(data);
        if (enableToasts) {
          toast.warning(`Health check failed for ${data?.container_name || 'container'}`, {
            description: data?.error || 'Container may be unhealthy',
          });
        }
        break;

      case 'ping':
        // Heartbeat, no action needed
        break;

      default:
        console.debug('[EventStream] Unknown event type:', type, data);
    }
  }, [
    onUpdateAvailable,
    onUpdateApplied,
    onUpdateFailed,
    onContainerRestarted,
    onHealthCheckFailed,
    enableToasts,
  ]);

  const connect = useCallback(() => {
    if (!isMountedRef.current) return;

    // Clean up existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    try {
      setConnectionStatus('reconnecting');

      const eventSource = new EventSource(SSE_ENDPOINT);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        if (!isMountedRef.current) return;

        console.log('[EventStream] Connected to SSE');
        setConnectionStatus('connected');
        reconnectDelayRef.current = INITIAL_RECONNECT_DELAY; // Reset backoff
      };

      eventSource.onmessage = (event) => {
        if (!isMountedRef.current) return;

        try {
          const parsed = JSON.parse(event.data);
          handleEvent(parsed);
        } catch (error) {
          console.error('[EventStream] Failed to parse event data:', error);
          // Notify user of parsing error via toast
          if (enableToasts) {
            toast.error('Event stream error', {
              description: 'Failed to process server event. Some updates may be missed.',
            });
          }
        }
      };

      // Listen for custom event types
      eventSource.addEventListener('ping', () => {
        // Heartbeat received, connection is alive
      });

      eventSource.onerror = (error) => {
        if (!isMountedRef.current) return;

        console.error('[EventStream] Connection error:', error);
        setConnectionStatus('disconnected');

        // Close the failed connection
        eventSource.close();
        eventSourceRef.current = null;

        // Schedule reconnect with exponential backoff
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }

        reconnectTimeoutRef.current = setTimeout(() => {
          if (!isMountedRef.current) return;

          console.log(`[EventStream] Reconnecting in ${reconnectDelayRef.current}ms...`);
          connectRef.current?.();

          // Increase delay for next attempt (exponential backoff)
          reconnectDelayRef.current = Math.min(
            reconnectDelayRef.current * 2,
            MAX_RECONNECT_DELAY
          );
        }, reconnectDelayRef.current);
      };
    } catch (error) {
      console.error('[EventStream] Failed to create EventSource:', error);
      setConnectionStatus('disconnected');
    }
  }, [handleEvent, enableToasts]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    isMountedRef.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    connect();

    return () => {
      isMountedRef.current = false;

      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }

      if (eventSourceRef.current) {
        console.log('[EventStream] Disconnecting...');
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [connect]);

  return {
    connectionStatus,
    reconnect: connect,
  };
}
