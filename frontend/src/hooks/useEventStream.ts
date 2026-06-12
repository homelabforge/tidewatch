import { useEffect, useCallback } from 'react';
import { useEventStreamContext } from '../contexts/EventStreamContext';

export type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting';

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

// Sibling drift event data
export interface SiblingDriftEvent {
  job_id: number;
  compose_file: string;
  registry: string;
  image: string;
  sibling_names: string[];
  dominant_tag: string;
  per_container_tags: Record<string, string>;
  settings_divergent: boolean;
  reconciled_names: string[];
}

// Dependency scan progress event data
export interface DepScanProgressEvent {
  job_id: number;
  status: string;
  total_count: number;
  scanned_count: number;
  updates_found: number;
  errors_count?: number;
  current_project?: string | null;
  progress_percent?: number;
  error?: string;
}

interface UseEventStreamOptions {
  // Update lifecycle (backend emits hyphenated event names).
  onUpdateProgress?: (data: Record<string, unknown> | undefined) => void;
  onUpdateComplete?: (data: Record<string, unknown> | undefined) => void;
  // Check job callbacks
  onCheckJobCreated?: (data: CheckJobProgressEvent) => void;
  onCheckJobStarted?: (data: CheckJobProgressEvent) => void;
  onCheckJobProgress?: (data: CheckJobProgressEvent) => void;
  onCheckJobCompleted?: (data: CheckJobProgressEvent) => void;
  onCheckJobFailed?: (data: CheckJobProgressEvent) => void;
  onCheckJobCanceled?: (data: CheckJobProgressEvent) => void;
  // Dependency scan callbacks
  onDepScanStarted?: (data: DepScanProgressEvent) => void;
  onDepScanProgress?: (data: DepScanProgressEvent) => void;
  onDepScanCompleted?: (data: DepScanProgressEvent) => void;
  onDepScanFailed?: (data: DepScanProgressEvent) => void;
  onDepScanCanceled?: (data: DepScanProgressEvent) => void;
  // Sibling drift callback
  onSiblingDriftDetected?: (data: SiblingDriftEvent) => void;
  enableToasts?: boolean;
}

/**
 * Subscribe to SSE events from the shared EventStreamContext.
 *
 * This hook no longer creates its own EventSource — it subscribes to events
 * dispatched by the EventStreamProvider in App. Multiple components can call
 * this hook without multiplying SSE connections.
 */
export function useEventStream(options: UseEventStreamOptions = {}) {
  const {
    onUpdateProgress,
    onUpdateComplete,
    onCheckJobCreated,
    onCheckJobStarted,
    onCheckJobProgress,
    onCheckJobCompleted,
    onCheckJobFailed,
    onCheckJobCanceled,
    onDepScanStarted,
    onDepScanProgress,
    onDepScanCompleted,
    onDepScanFailed,
    onDepScanCanceled,
    onSiblingDriftDetected,
  } = options;

  const { connectionStatus, reconnect, subscribe } = useEventStreamContext();

  const handleEvent = useCallback((event: Record<string, unknown>) => {
    const { type, data: explicitData, ...restData } = event;
    const data = (explicitData as Record<string, unknown> | undefined) ??
      (Object.keys(restData).length > 0 ? restData : undefined);

    switch (type) {
      case 'update-progress':
        onUpdateProgress?.(data);
        break;
      case 'update-complete':
        onUpdateComplete?.(data);
        break;
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
        break;
      case 'check-job-failed':
        if (data) onCheckJobFailed?.(data as unknown as CheckJobProgressEvent);
        break;
      case 'check-job-canceled':
        if (data) onCheckJobCanceled?.(data as unknown as CheckJobProgressEvent);
        break;
      case 'dependency-scan-started':
        if (data) onDepScanStarted?.(data as unknown as DepScanProgressEvent);
        break;
      case 'dependency-scan-progress':
        if (data) onDepScanProgress?.(data as unknown as DepScanProgressEvent);
        break;
      case 'dependency-scan-completed':
        if (data) onDepScanCompleted?.(data as unknown as DepScanProgressEvent);
        break;
      case 'dependency-scan-failed':
        if (data) onDepScanFailed?.(data as unknown as DepScanProgressEvent);
        break;
      case 'dependency-scan-canceled':
        if (data) onDepScanCanceled?.(data as unknown as DepScanProgressEvent);
        break;
      case 'sibling-drift-detected':
        if (data) onSiblingDriftDetected?.(data as unknown as SiblingDriftEvent);
        break;
    }
  }, [
    onUpdateProgress,
    onUpdateComplete,
    onCheckJobCreated,
    onCheckJobStarted,
    onCheckJobProgress,
    onCheckJobCompleted,
    onCheckJobFailed,
    onCheckJobCanceled,
    onDepScanStarted,
    onDepScanProgress,
    onDepScanCompleted,
    onDepScanFailed,
    onDepScanCanceled,
    onSiblingDriftDetected,
  ]);

  useEffect(() => {
    return subscribe(handleEvent);
  }, [subscribe, handleEvent]);

  return {
    connectionStatus,
    reconnect,
  };
}
