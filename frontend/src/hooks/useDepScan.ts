import { useState, useCallback, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { useEventStream, type DepScanProgressEvent } from './useEventStream';
import type { DepScanJobState } from '../components/DepScanProgressBar';
import type { DependencySummary } from '../types';
import { useDependencySummaryQuery } from './useDependencyQueries';
import { toast } from 'sonner';

interface UseDepScanOptions {
  onCompleted?: () => void;
  onCanceled?: () => void;
}

const EMPTY_SUMMARY: Record<string, DependencySummary> = {};

export function useDepScan(options: UseDepScanOptions = {}) {
  const { onCompleted, onCanceled } = options;

  const queryClient = useQueryClient();
  const [depScanJob, setDepScanJob] = useState<DepScanJobState | null>(null);
  const depSummaryQuery = useDependencySummaryQuery();
  const depSummary: Record<string, DependencySummary> = useMemo(
    () => depSummaryQuery.data?.summaries ?? EMPTY_SUMMARY,
    [depSummaryQuery.data],
  );

  const refreshSummary = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['containers', 'dependencySummary'] });
  }, [queryClient]);

  const handleDepScanProgress = useCallback((data: DepScanProgressEvent) => {
    setDepScanJob({
      jobId: data.job_id,
      status: data.status as DepScanJobState['status'],
      totalCount: data.total_count,
      scannedCount: data.scanned_count,
      updatesFound: data.updates_found,
      errorsCount: data.errors_count || 0,
      currentProject: data.current_project || null,
      progressPercent: data.progress_percent || 0,
    });
  }, []);

  const handleDepScanCompleted = useCallback((data: DepScanProgressEvent) => {
    setDepScanJob({
      jobId: data.job_id,
      status: 'done',
      totalCount: data.total_count,
      scannedCount: data.scanned_count,
      updatesFound: data.updates_found,
      errorsCount: data.errors_count || 0,
      currentProject: null,
      progressPercent: 100,
    });
    refreshSummary();
    onCompleted?.();
  }, [refreshSummary, onCompleted]);

  const handleDepScanFailed = useCallback(() => {
    setDepScanJob(prev => prev ? { ...prev, status: 'failed' } : null);
  }, []);

  const handleDepScanCanceled = useCallback(() => {
    setDepScanJob(prev => prev ? { ...prev, status: 'canceled' } : null);
    refreshSummary();
    onCanceled?.();
  }, [refreshSummary, onCanceled]);

  useEventStream({
    onDepScanStarted: handleDepScanProgress,
    onDepScanProgress: handleDepScanProgress,
    onDepScanCompleted: handleDepScanCompleted,
    onDepScanFailed: handleDepScanFailed,
    onDepScanCanceled: handleDepScanCanceled,
    enableToasts: false,
  });

  const startDepScan = useCallback(async () => {
    try {
      const result = await api.containers.scanAllProjectDependencies();
      if (result.already_running) {
        toast.info('Dependency scan already in progress');
        const jobStatus = await api.containers.getDependencyScanStatus(result.job_id);
        setDepScanJob({
          jobId: jobStatus.job_id,
          status: jobStatus.status as DepScanJobState['status'],
          totalCount: jobStatus.total_count,
          scannedCount: jobStatus.scanned_count,
          updatesFound: jobStatus.updates_found,
          errorsCount: jobStatus.errors_count,
          currentProject: jobStatus.current_project,
          progressPercent: jobStatus.progress_percent,
        });
      } else {
        setDepScanJob({
          jobId: result.job_id,
          status: 'queued',
          totalCount: 0,
          scannedCount: 0,
          updatesFound: 0,
          errorsCount: 0,
          currentProject: null,
          progressPercent: 0,
        });
        toast.info('Dependency scan started');
      }
    } catch {
      toast.error('Failed to start dependency scan');
    }
  }, []);

  const cancelDepScan = useCallback(async () => {
    if (!depScanJob) return;
    try {
      await api.containers.cancelDependencyScan(depScanJob.jobId);
      toast.info('Cancellation requested');
    } catch {
      toast.error('Failed to cancel scan');
    }
  }, [depScanJob]);

  const dismissDepScan = useCallback(() => {
    setDepScanJob(null);
  }, []);

  return {
    depScanJob,
    depSummary,
    startDepScan,
    cancelDepScan,
    dismissDepScan,
  };
}
