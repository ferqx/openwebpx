import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchSandboxThreadGitStaged,
  fetchSandboxThreadGitUnstaged,
  type SandboxThreadGitChangesResult
} from '@/lib/sandbox';
import { getErrorMessage } from '@/business/task-detail/task-detail-utils';

type GitDiffState = {
  staged: SandboxThreadGitChangesResult | null;
  unstaged: SandboxThreadGitChangesResult | null;
  hasLoaded: boolean;
  loading: boolean;
  error?: string;
  lastUpdatedAt?: string;
};

const EMPTY_GIT_DIFF_STATE: GitDiffState = {
  staged: null,
  unstaged: null,
  hasLoaded: false,
  loading: false,
  error: undefined,
  lastUpdatedAt: undefined
};

type UseTaskDetailGitDiffOptions = {
  threadId?: string;
  enabled: boolean;
  blockRefresh?: boolean;
  isNotFound: boolean;
  pageError?: unknown;
};

export const useTaskDetailGitDiff = ({
  threadId,
  enabled,
  blockRefresh = false,
  isNotFound,
  pageError
}: UseTaskDetailGitDiffOptions) => {
  const [gitDiffState, setGitDiffState] = useState<GitDiffState>(
    EMPTY_GIT_DIFF_STATE
  );
  const gitDiffRequestSeqRef = useRef(0);

  const refreshGitDiff = useCallback(async () => {
    const normalizedThreadId = threadId?.trim();
    if (!normalizedThreadId) return;

    const requestSeq = gitDiffRequestSeqRef.current + 1;
    gitDiffRequestSeqRef.current = requestSeq;
    setGitDiffState((prev) => ({
      ...prev,
      loading: true,
      error: undefined
    }));

    try {
      const [staged, unstaged] = await Promise.all([
        fetchSandboxThreadGitStaged(normalizedThreadId, {
          includeDiff: true,
          diffMaxChars: 0
        }),
        fetchSandboxThreadGitUnstaged(normalizedThreadId, {
          includeDiff: true,
          diffMaxChars: 0
        })
      ]);
      if (gitDiffRequestSeqRef.current !== requestSeq) return;
      setGitDiffState({
        staged,
        unstaged,
        hasLoaded: true,
        loading: false,
        error: undefined,
        lastUpdatedAt: new Date().toISOString()
      });
    } catch (gitDiffError) {
      if (gitDiffRequestSeqRef.current !== requestSeq) return;
      setGitDiffState((prev) => ({
        ...prev,
        hasLoaded: true,
        loading: false,
        error: getErrorMessage(gitDiffError),
        lastUpdatedAt: new Date().toISOString()
      }));
    }
  }, [threadId]);

  useEffect(() => {
    setGitDiffState(EMPTY_GIT_DIFF_STATE);
  }, [threadId]);

  useEffect(() => {
    if (!threadId || !enabled || blockRefresh || isNotFound || pageError) return;
    void refreshGitDiff();
  }, [blockRefresh, enabled, isNotFound, pageError, refreshGitDiff, threadId]);

  return {
    gitDiffState,
    refreshGitDiff
  };
};
