import { useState, useCallback } from 'react';
import { useEventStream } from './useEventStream';

/**
 * Live progress of an in-flight update apply, keyed by container id.
 *
 * Apply is asynchronous: the API returns 202 immediately and the backend runs
 * the update flow (backup → pull → deploy → health check) in the background,
 * streaming `update-progress` events and a terminal `update-complete`. This
 * hook turns that stream into per-container state the Updates page can render
 * as a progress bar.
 */
export interface ApplyProgress {
  containerId: number;
  containerName: string;
  phase: string; // starting, backup, data-backup, compose-updated, pulling, pulled, deploying, health-check
  progress: number; // 0..1
  message?: string;
}

export function useApplyProgress() {
  const [applyProgress, setApplyProgress] = useState<Map<number, ApplyProgress>>(new Map());

  // Optimistically seed a "starting" entry the instant an apply is requested,
  // so the bar appears without waiting for the first SSE frame.
  const markApplying = useCallback((containerId: number, containerName: string) => {
    setApplyProgress((prev) => {
      const next = new Map(prev);
      next.set(containerId, { containerId, containerName, phase: 'starting', progress: 0.02 });
      return next;
    });
  }, []);

  const clear = useCallback((containerId: number) => {
    setApplyProgress((prev) => {
      if (!prev.has(containerId)) return prev;
      const next = new Map(prev);
      next.delete(containerId);
      return next;
    });
  }, []);

  useEventStream({
    onUpdateProgress: (data) => {
      const id = Number(data?.container_id);
      if (!id) return;
      setApplyProgress((prev) => {
        const next = new Map(prev);
        next.set(id, {
          containerId: id,
          containerName: String(data?.container_name ?? ''),
          phase: String(data?.phase ?? 'in_progress'),
          progress: typeof data?.progress === 'number' ? data.progress : 0,
          message: data?.message != null ? String(data.message) : undefined,
        });
        return next;
      });
    },
    onUpdateComplete: (data) => {
      const id = Number(data?.container_id);
      if (!id) return;
      // Terminal: drop the bar. The list itself is refetched by
      // EventStreamContext's invalidation, and the success/failure toast is
      // emitted there too, so there's nothing more to show here.
      clear(id);
    },
  });

  return { applyProgress, markApplying };
}
