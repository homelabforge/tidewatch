import { createContext, useContext, useEffect, useRef, useState, useCallback, type ReactNode } from 'react';
import { toast } from 'sonner';
import type { ConnectionStatus, CheckJobProgressEvent, DepScanProgressEvent } from '../hooks/useEventStream';

interface EventStreamEvent {
  type: string;
  data?: Record<string, unknown>;
  timestamp?: string;
}

type EventCallback = (event: EventStreamEvent & Record<string, unknown>) => void;

interface EventStreamContextType {
  connectionStatus: ConnectionStatus;
  reconnect: () => void;
  subscribe: (callback: EventCallback) => () => void;
}

const EventStreamContext = createContext<EventStreamContextType | undefined>(undefined);

const API_BASE = import.meta.env.VITE_API_URL || '';
const SSE_ENDPOINT = `${API_BASE}/api/v1/events/stream`;
const MAX_RECONNECT_DELAY = 30000;
const INITIAL_RECONNECT_DELAY = 1000;

interface EventStreamProviderProps {
  children: ReactNode;
  enableToasts?: boolean;
}

export function EventStreamProvider({ children, enableToasts = true }: EventStreamProviderProps) {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected');
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY);
  const isMountedRef = useRef(true);
  const connectRef = useRef<(() => void) | undefined>(undefined);
  const subscribersRef = useRef<Set<EventCallback>>(new Set());

  const subscribe = useCallback((callback: EventCallback) => {
    subscribersRef.current.add(callback);
    return () => {
      subscribersRef.current.delete(callback);
    };
  }, []);

  const dispatchEvent = useCallback((event: EventStreamEvent & Record<string, unknown>) => {
    // Dispatch to all subscribers
    for (const subscriber of subscribersRef.current) {
      subscriber(event);
    }

    // Handle toasts centrally
    if (!enableToasts) return;

    const { type, data: explicitData, ...restData } = event;
    const data = (explicitData as Record<string, unknown> | undefined) ??
      (Object.keys(restData).length > 0 ? restData : undefined);

    switch (type) {
      case 'update_available':
        toast.info(`Update available for ${data?.container_name || 'container'}`, {
          description: `New version: ${data?.new_version || 'unknown'}`,
        });
        break;
      case 'update_applied':
        toast.success(`Update applied to ${data?.container_name || 'container'}`, {
          description: `Updated to version ${data?.new_version || 'unknown'}`,
        });
        break;
      case 'update_failed':
        toast.error(`Update failed for ${data?.container_name || 'container'}`, {
          description: String(data?.error ?? 'Unknown error occurred'),
        });
        break;
      case 'container_restarted':
        toast.info(`Container restarted: ${data?.container_name || 'unknown'}`, {
          description: `Restart reason: ${data?.reason || 'manual'}`,
        });
        break;
      case 'health_check_failed':
        toast.warning(`Health check failed for ${data?.container_name || 'container'}`, {
          description: String(data?.error ?? 'Container may be unhealthy'),
        });
        break;
      case 'check-job-completed':
        toast.success('Update check complete', {
          description: `Found ${data?.updates_found || 0} updates (${data?.checked_count}/${data?.total_count} containers)`,
        });
        break;
      case 'check-job-failed':
        toast.error('Update check failed', {
          description: String(data?.error ?? 'Unknown error occurred'),
        });
        break;
      case 'check-job-canceled':
        toast.info('Update check canceled', {
          description: `Checked ${data?.checked_count || 0} of ${data?.total_count || 0} containers`,
        });
        break;
      case 'dependency-scan-completed':
        toast.success('Dependency scan complete', {
          description: `Found ${data?.updates_found || 0} updates across ${data?.scanned_count || 0} projects`,
        });
        break;
      case 'dependency-scan-failed':
        toast.error('Dependency scan failed', {
          description: String(data?.error ?? 'Unknown error occurred'),
        });
        break;
      case 'dependency-scan-canceled':
        toast.info('Dependency scan canceled', {
          description: `Scanned ${data?.scanned_count || 0} of ${data?.total_count || 0} projects`,
        });
        break;
    }
  }, [enableToasts]);

  const connect = useCallback(() => {
    if (!isMountedRef.current) return;

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
        setConnectionStatus('connected');
        reconnectDelayRef.current = INITIAL_RECONNECT_DELAY;
      };

      eventSource.onmessage = (event) => {
        if (!isMountedRef.current) return;
        try {
          const parsed = JSON.parse(event.data);
          dispatchEvent(parsed);
        } catch (error) {
          console.error('[EventStream] Failed to parse event data:', error);
        }
      };

      eventSource.addEventListener('ping', () => {});

      eventSource.onerror = () => {
        if (!isMountedRef.current) return;
        setConnectionStatus('disconnected');
        eventSource.close();
        eventSourceRef.current = null;

        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }

        reconnectTimeoutRef.current = setTimeout(() => {
          if (!isMountedRef.current) return;
          connectRef.current?.();
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
  }, [dispatchEvent]);

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
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [connect]);

  return (
    <EventStreamContext.Provider value={{ connectionStatus, reconnect: connect, subscribe }}>
      {children}
    </EventStreamContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useEventStreamContext(): EventStreamContextType {
  const context = useContext(EventStreamContext);
  if (!context) {
    throw new Error('useEventStreamContext must be used within an EventStreamProvider');
  }
  return context;
}

// Re-export types for convenience
export type { CheckJobProgressEvent, DepScanProgressEvent };
