import { useEffect, useRef, useState, useCallback } from 'react';
import { toast } from 'sonner';

export type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting';

interface EventStreamEvent {
  type: string;
  data?: Record<string, unknown>;
  timestamp?: string;
}

// Check job progress event data
export interface CheckJobProgressEvent {
  job_id: number;
  status: string;
  total_count: number;
  checked_count: number;
  updates_found: number;
  errors_count?: number;
  current_container?: string;
  progress_percent?: number;
  duration_seconds?: number;
  error?: string;
}

interface UseEventStreamOptions {
  onUpdateAvailable?: (data: Record<string, unknown> | undefined) => void;
  onUpdateApplied?: (data: Record<string, unknown> | undefined) => void;
  onUpdateFailed?: (data: Record<string, unknown> | undefined) => void;
  onContainerRestarted?: (data: Record<string, unknown> | undefined) => void;
  onHealthCheckFailed?: (data: Record<string, unknown> | undefined) => void;
  // Check job callbacks
  onCheckJobCreated?: (data: CheckJobProgressEvent) => void;
  onCheckJobStarted?: (data: CheckJobProgressEvent) => void;
  onCheckJobProgress?: (data: CheckJobProgressEvent) => void;
  onCheckJobCompleted?: (data: CheckJobProgressEvent) => void;
  onCheckJobFailed?: (data: CheckJobProgressEvent) => void;
  onCheckJobCanceled?: (data: CheckJobProgressEvent) => void;
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
    onCheckJobCreated,
    onCheckJobStarted,
    onCheckJobProgress,
    onCheckJobCompleted,
    onCheckJobFailed,
    onCheckJobCanceled,
    enableToasts = true,
  } = options;

  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected');
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY);
  const isMountedRef = useRef(true);
  const connectRef = useRef<(() => void) | undefined>(undefined);

  const handleEvent = useCallback((event: EventStreamEvent & Record<string, unknown>) => {
    // Backend sends flat events: {type, job_id, status, ...} not {type, data: {...}}
    // Extract type, treat everything else as data (timestamp is harmless extra field)
    const { type, data: explicitData, ...restData } = event;
    const data = (explicitData as Record<string, unknown> | undefined) ??
      (Object.keys(restData).length > 0 ? restData : undefined);

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
            description: String(data?.error ?? 'Unknown error occurred'),
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
            description: String(data?.error ?? 'Container may be unhealthy'),
          });
        }
        break;

      case 'ping':
        // Heartbeat, no action needed
        break;

      // Check job events
      case 'check-job-created':
        if (data) onCheckJobCreated?.(data as unknown as CheckJobProgressEvent);
        break;

      case 'check-job-started':
        if (data) onCheckJobStarted?.(data as unknown as CheckJobProgressEvent);
        break;

      case 'check-job-progress':
        if (data) onCheckJobProgress?.(data as unknown as CheckJobProgressEvent);
        break;

      case 'check-job-completed':
        if (data) onCheckJobCompleted?.(data as unknown as CheckJobProgressEvent);
        if (enableToasts) {
          toast.success('Update check complete', {
            description: `Found ${data?.updates_found || 0} updates (${data?.checked_count}/${data?.total_count} containers)`,
          });
        }
        break;

      case 'check-job-failed':
        if (data) onCheckJobFailed?.(data as unknown as CheckJobProgressEvent);
        if (enableToasts) {
          toast.error('Update check failed', {
            description: String(data?.error ?? 'Unknown error occurred'),
          });
        }
        break;

      case 'check-job-canceled':
        if (data) onCheckJobCanceled?.(data as unknown as CheckJobProgressEvent);
        if (enableToasts) {
          toast.info('Update check canceled', {
            description: `Checked ${data?.checked_count || 0} of ${data?.total_count || 0} containers`,
          });
        }
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
    onCheckJobCreated,
    onCheckJobStarted,
    onCheckJobProgress,
    onCheckJobCompleted,
    onCheckJobFailed,
    onCheckJobCanceled,
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
