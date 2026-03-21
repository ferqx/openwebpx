import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { type Message } from '@langchain/langgraph-sdk';
import {
  INITIAL_MESSAGES_MAX_WAIT_MS,
  buildMessagesDigest
} from '@/business/task-detail/task-detail-utils';

type UseTaskDetailMessageHydrationOptions = {
  threadId?: string;
  messages: Message[];
  isThreadLoading: boolean;
};

export const useTaskDetailMessageHydration = ({
  threadId,
  messages,
  isThreadLoading
}: UseTaskDetailMessageHydrationOptions) => {
  const [renderMessages, setRenderMessages] = useState(messages);
  const [isInitialMessageHydrating, setIsInitialMessageHydrating] = useState(true);
  const hydrationStartedAtRef = useRef<number>(0);
  const hydrationCommitFrameRef = useRef<number | null>(null);
  const pendingRenderMessagesRef = useRef(messages);
  const pendingHydrationFlagRef = useRef<boolean | undefined>(undefined);
  const lastCommittedMessagesDigestRef = useRef<string>(
    buildMessagesDigest(messages)
  );
  const latestHydrationMessagesRef = useRef(messages);

  const scheduleRenderCommit = useCallback(
    (nextMessages: Message[], nextHydrationFlag?: boolean) => {
      if (typeof window === 'undefined') return;

      pendingRenderMessagesRef.current = nextMessages;
      if (typeof nextHydrationFlag === 'boolean') {
        pendingHydrationFlagRef.current = nextHydrationFlag;
      }
      if (hydrationCommitFrameRef.current != null) return;

      hydrationCommitFrameRef.current = window.requestAnimationFrame(() => {
        hydrationCommitFrameRef.current = null;
        const nextDigest = buildMessagesDigest(pendingRenderMessagesRef.current);
        setRenderMessages(pendingRenderMessagesRef.current);
        lastCommittedMessagesDigestRef.current = nextDigest;
        const hydrationFlag = pendingHydrationFlagRef.current;
        pendingHydrationFlagRef.current = undefined;
        if (typeof hydrationFlag === 'boolean') {
          setIsInitialMessageHydrating(hydrationFlag);
        }
      });
    },
    []
  );

  const flushInitialHydration = useCallback(() => {
    if (!isInitialMessageHydrating) return;
    scheduleRenderCommit(latestHydrationMessagesRef.current, false);
  }, [isInitialMessageHydrating, scheduleRenderCommit]);

  useEffect(() => {
    hydrationStartedAtRef.current = Date.now();
    latestHydrationMessagesRef.current = [];
    if (hydrationCommitFrameRef.current != null && typeof window !== 'undefined') {
      window.cancelAnimationFrame(hydrationCommitFrameRef.current);
      hydrationCommitFrameRef.current = null;
    }
    scheduleRenderCommit([], true);
  }, [scheduleRenderCommit, threadId]);

  useEffect(() => {
    if (!isInitialMessageHydrating) {
      const nextDigest = buildMessagesDigest(messages);
      if (nextDigest === lastCommittedMessagesDigestRef.current) {
        return;
      }
      scheduleRenderCommit(messages);
      return;
    }

    latestHydrationMessagesRef.current = messages;
    if (isThreadLoading) return;
    if (typeof window === 'undefined') {
      flushInitialHydration();
      return;
    }

    const elapsed = Date.now() - hydrationStartedAtRef.current;
    if (elapsed >= INITIAL_MESSAGES_MAX_WAIT_MS) {
      flushInitialHydration();
      return;
    }

    flushInitialHydration();
  }, [
    flushInitialHydration,
    isInitialMessageHydrating,
    isThreadLoading,
    messages,
    scheduleRenderCommit
  ]);

  useEffect(
    () => () => {
      if (hydrationCommitFrameRef.current != null && typeof window !== 'undefined') {
        window.cancelAnimationFrame(hydrationCommitFrameRef.current);
      }
    },
    []
  );

  const hydratedMessages = useMemo(() => renderMessages, [renderMessages]);

  return {
    hydratedMessages,
    isInitialMessageHydrating
  };
};
