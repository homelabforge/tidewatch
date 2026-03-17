import { useState, useCallback } from 'react';
import { api } from '../services/api';
import { useEventStream, type CheckJobProgressEvent } from './useEventStream';
import type { CheckJobState } from '../components/CheckProgressBar';
import { toast } from 'sonner';

interface UseCheckJobOptions {
  onCompleted?: () => void;
  onCanceled?: () => void;
}

export function useCheckJob(options: UseCheckJobOptions = {}) {
  const { onCompleted, onCanceled } = options;

  const [checkJob, setCheckJob] = useState<CheckJobState | null>(null);
  const [checkingUpdates, setCheckingUpdates] = useState(false);

  const handleCheckJobProgress = useCallback((data: CheckJobProgressEvent) => {
    setCheckJob({
      jobId: data.job_id,
      status: data.status as CheckJobState['status'],
      totalCount: data.total_count,
      checkedCount: data.checked_count,
      updatesFound: data.updates_found,
      errorsCount: data.errors_count || 0,
      currentContainer: data.current_container || null,
      progressPercent: data.progress_percent || 0,
    });
  }, []);

  const handleCheckJobCompleted = useCallback((data: CheckJobProgressEvent) => {
    setCheckJob({
      jobId: data.job_id,
      status: 'done',
      totalCount: data.total_count,
      checkedCount: data.checked_count,
      updatesFound: data.updates_found,
      errorsCount: data.errors_count || 0,
      currentContainer: null,
      progressPercent: 100,
    });
    onCompleted?.();
  }, [onCompleted]);

  const handleCheckJobFailed = useCallback(() => {
    setCheckJob(prev => prev ? { ...prev, status: 'failed' } : null);
  }, []);

  const handleCheckJobCanceled = useCallback(() => {
    setCheckJob(prev => prev ? { ...prev, status: 'canceled' } : null);
    onCanceled?.();
  }, [onCanceled]);

  useEventStream({
    onCheckJobStarted: handleCheckJobProgress,
    onCheckJobProgress: handleCheckJobProgress,
    onCheckJobCompleted: handleCheckJobCompleted,
    onCheckJobFailed: handleCheckJobFailed,
    onCheckJobCanceled: handleCheckJobCanceled,
    enableToasts: false,
  });

  const startCheckAll = useCallback(async () => {
    setCheckingUpdates(true);
    try {
      const result = await api.updates.checkAll();
      if (result.already_running) {
        toast.info('Update check already in progress');
        const jobStatus = await api.updates.getCheckJob(result.job_id);
        setCheckJob({
          jobId: jobStatus.id,
          status: jobStatus.status as CheckJobState['status'],
          totalCount: jobStatus.total_count,
          checkedCount: jobStatus.checked_count,
          updatesFound: jobStatus.updates_found,
          errorsCount: jobStatus.errors_count,
          currentContainer: jobStatus.current_container ?? null,
          progressPercent: jobStatus.progress_percent,
        });
      } else {
        setCheckJob({
          jobId: result.job_id,
          status: 'queued',
          totalCount: 0,
          checkedCount: 0,
          updatesFound: 0,
          errorsCount: 0,
          currentContainer: null,
          progressPercent: 0,
        });
        toast.info('Update check started');
      }
      setCheckingUpdates(false);
    } catch {
      toast.error('Failed to start update check');
      setCheckingUpdates(false);
    }
  }, []);

  const cancelCheckJob = useCallback(async () => {
    if (!checkJob) return;
    try {
      await api.updates.cancelCheckJob(checkJob.jobId);
      toast.info('Cancellation requested');
    } catch {
      toast.error('Failed to cancel check');
    }
  }, [checkJob]);

  const dismissCheckJob = useCallback(() => {
    setCheckJob(null);
  }, []);

  return {
    checkJob,
    checkingUpdates,
    startCheckAll,
    cancelCheckJob,
    dismissCheckJob,
  };
}
