import { useCallback, useEffect, useRef, useState } from "react";
import { client } from "@/lib/langgraph-sdk";
import {
  type SandboxBootstrapResult,
  getSandboxThreadBootstrapStatus,
  resetSandboxThreadBootstrap,
  startSandboxThreadBootstrap,
  streamSandboxThreadBootstrap,
} from "@/lib/sandbox";
import { type StreamContextType } from "@/provider/stream";
import {
  type EnvironmentInitDisplay,
  buildEnvironmentDisplayFromBootstrap,
  buildEnvironmentResetDisplay,
  getErrorStatusCode,
  isAbortError,
} from "@/hooks/thread-chat-utils";

type JoinThreadRun = StreamContextType["joinStream"];

type UseThreadEnvironmentBootstrapOptions = {
  threadId: string;
  joinStream?: JoinThreadRun;
  messageCount: number;
  enableEnvironmentInitialization: boolean;
  enableBootstrapRunJoinStream: boolean;
};

export function useThreadEnvironmentBootstrap({
  threadId,
  joinStream,
  messageCount,
  enableEnvironmentInitialization,
  enableBootstrapRunJoinStream,
}: UseThreadEnvironmentBootstrapOptions) {
  const [isEnvironmentReady, setIsEnvironmentReady] = useState(false);
  const [isEnvironmentBootstrapHydrated, setIsEnvironmentBootstrapHydrated] =
    useState(false);
  const [isEnvironmentResetting, setIsEnvironmentResetting] = useState(false);
  const [environmentInitDisplay, setEnvironmentInitDisplay] =
    useState<EnvironmentInitDisplay | null>(null);

  const joinStreamRef = useRef(joinStream);
  const joinedRunIdsRef = useRef<Set<string>>(new Set());
  const bootstrapPollEpochRef = useRef(0);
  const bootstrapStreamAbortRef = useRef<AbortController | null>(null);
  const bootstrapStreamSeqRef = useRef(0);

  useEffect(() => {
    joinStreamRef.current = joinStream;
  }, [joinStream]);

  useEffect(() => {
    return () => {
      bootstrapPollEpochRef.current += 1;
      bootstrapStreamAbortRef.current?.abort();
      bootstrapStreamAbortRef.current = null;
    };
  }, []);

  useEffect(() => {
    bootstrapPollEpochRef.current += 1;
    bootstrapStreamAbortRef.current?.abort();
    bootstrapStreamAbortRef.current = null;
    bootstrapStreamSeqRef.current = 0;
    joinedRunIdsRef.current.clear();
    setIsEnvironmentReady(false);
    setIsEnvironmentBootstrapHydrated(false);
    setEnvironmentInitDisplay(null);
    setIsEnvironmentResetting(false);
  }, [threadId]);

  useEffect(() => {
    if (!enableEnvironmentInitialization || threadId.length === 0) {
      setIsEnvironmentBootstrapHydrated(true);
    }
  }, [enableEnvironmentInitialization, threadId]);

  const tryJoinRunStream = useCallback(
    (runId?: string, runStatus?: string) => {
      if (!enableBootstrapRunJoinStream) return;
      const normalizedRunId = runId?.trim() ?? "";
      const normalizedRunStatus = runStatus?.trim().toLowerCase() ?? "";
      if (!normalizedRunId) return;
      if (!threadId) return;
      if (joinedRunIdsRef.current.has(normalizedRunId)) return;
      if (!joinStreamRef.current) return;

      joinedRunIdsRef.current.add(normalizedRunId);
      let joined = false;
      void (async () => {
        try {
          const run = await client.runs.get(threadId, normalizedRunId);
          const latestRunStatus = run.status?.trim().toLowerCase() ?? "";
          const canJoin =
            latestRunStatus === "pending" || latestRunStatus === "running";
          if (!canJoin) return;

          await joinStreamRef.current?.(normalizedRunId, undefined, {
            streamMode: ["messages-tuple"],
          });
          joined = true;
        } catch (joinError) {
          if (getErrorStatusCode(joinError) === 404) {
            return;
          }
          console.error("Failed to join bootstrap run stream", {
            threadId,
            runId: normalizedRunId,
            runStatus: normalizedRunStatus || undefined,
            error: joinError,
          });
        } finally {
          if (!joined) {
            joinedRunIdsRef.current.delete(normalizedRunId);
          }
        }
      })();
    },
    [enableBootstrapRunJoinStream, threadId],
  );

  const streamBootstrapUntilSettled = useCallback(
    async (
      currentThreadId: string,
      requestId?: string,
      epoch?: number,
    ): Promise<SandboxBootstrapResult | null> => {
      const streamController = new AbortController();
      bootstrapStreamAbortRef.current?.abort();
      bootstrapStreamAbortRef.current = streamController;

      let settledStatus: SandboxBootstrapResult | null = null;
      try {
        await streamSandboxThreadBootstrap(currentThreadId, {
          fromSeq: bootstrapStreamSeqRef.current,
          signal: streamController.signal,
          onEvent: (event) => {
            if (
              typeof epoch === "number" &&
              bootstrapPollEpochRef.current !== epoch
            ) {
              streamController.abort();
              return;
            }

            if (event.type === "bootstrap_event") {
              if (event.data.seq > bootstrapStreamSeqRef.current) {
                bootstrapStreamSeqRef.current = event.data.seq;
              }
              return;
            }

            if (event.type === "bootstrap_snapshot") {
              const snapshot = event.data;
              const snapshotSeq = snapshot.event_seq ?? 0;
              if (snapshotSeq > bootstrapStreamSeqRef.current) {
                bootstrapStreamSeqRef.current = snapshotSeq;
              }

              if (
                requestId &&
                snapshot.request_id &&
                snapshot.request_id !== requestId
              ) {
                return;
              }

              setEnvironmentInitDisplay(
                buildEnvironmentDisplayFromBootstrap(snapshot),
              );

              if (snapshot.status === "success") {
                setIsEnvironmentReady(true);
                tryJoinRunStream(snapshot.run_id, snapshot.run_status);
                settledStatus = snapshot;
                streamController.abort();
                return;
              }

              if (snapshot.status === "error" || snapshot.status === "idle") {
                settledStatus = snapshot;
                streamController.abort();
                return;
              }

              tryJoinRunStream(snapshot.run_id, snapshot.run_status);
              return;
            }

            if (event.type === "bootstrap_done") {
              if (event.data.event_seq > bootstrapStreamSeqRef.current) {
                bootstrapStreamSeqRef.current = event.data.event_seq;
              }
              return;
            }

            if (event.type === "bootstrap_error") {
              const messageText =
                event.data.message?.trim() || "环境初始化流式通道异常";
              settledStatus = {
                thread_id: currentThreadId,
                graph_id: "",
                status: "error",
                error: messageText,
                steps: [],
                logs: [],
                event_seq: bootstrapStreamSeqRef.current,
              };
              streamController.abort();
            }
          },
        });
      } catch (streamError) {
        if (!isAbortError(streamError)) {
          throw streamError;
        }
      } finally {
        if (bootstrapStreamAbortRef.current === streamController) {
          bootstrapStreamAbortRef.current = null;
        }
      }

      return settledStatus;
    },
    [tryJoinRunStream],
  );

  const pollBootstrapUntilSettled = useCallback(
    async (
      currentThreadId: string,
      requestId?: string,
      epoch?: number,
    ): Promise<SandboxBootstrapResult | null> => {
      while (true) {
        if (
          typeof epoch === "number" &&
          bootstrapPollEpochRef.current !== epoch
        ) {
          return null;
        }

        const latest = await getSandboxThreadBootstrapStatus(currentThreadId);
        if (
          typeof epoch === "number" &&
          bootstrapPollEpochRef.current !== epoch
        ) {
          return null;
        }

        if (requestId && latest.request_id && latest.request_id !== requestId) {
          return latest;
        }

        setEnvironmentInitDisplay(buildEnvironmentDisplayFromBootstrap(latest));
        bootstrapStreamSeqRef.current = Math.max(
          bootstrapStreamSeqRef.current,
          latest.event_seq ?? 0,
        );
        if (latest.status === "success") {
          setIsEnvironmentReady(true);
          tryJoinRunStream(latest.run_id, latest.run_status);
          return latest;
        }

        if (latest.status === "error" || latest.status === "idle") {
          return latest;
        }

        tryJoinRunStream(latest.run_id, latest.run_status);
        await new Promise((resolve) => {
          window.setTimeout(resolve, 1200);
        });
      }
    },
    [tryJoinRunStream],
  );

  const watchBootstrapUntilSettled = useCallback(
    async (
      currentThreadId: string,
      requestId?: string,
      epoch?: number,
    ): Promise<SandboxBootstrapResult | null> => {
      try {
        const streamedStatus = await streamBootstrapUntilSettled(
          currentThreadId,
          requestId,
          epoch,
        );
        if (streamedStatus) return streamedStatus;
      } catch (streamError) {
        console.error(
          "Failed to consume bootstrap stream, fallback to polling",
          streamError,
        );
      }
      return pollBootstrapUntilSettled(currentThreadId, requestId, epoch);
    },
    [pollBootstrapUntilSettled, streamBootstrapUntilSettled],
  );

  useEffect(() => {
    if (messageCount > 0) {
      setIsEnvironmentReady(true);
    }
  }, [messageCount]);

  useEffect(() => {
    if (!enableEnvironmentInitialization) return;
    if (!threadId) return;

    const epoch = bootstrapPollEpochRef.current;

    const syncBootstrapStatus = async () => {
      try {
        const status = await getSandboxThreadBootstrapStatus(threadId);
        if (bootstrapPollEpochRef.current !== epoch) return;
        bootstrapStreamSeqRef.current = Math.max(
          bootstrapStreamSeqRef.current,
          status.event_seq ?? 0,
        );

        setEnvironmentInitDisplay(buildEnvironmentDisplayFromBootstrap(status));
        setIsEnvironmentBootstrapHydrated(true);

        if (status.status === "running") {
          void watchBootstrapUntilSettled(threadId, status.request_id, epoch);
          return;
        }

        if (status.status === "success") {
          setIsEnvironmentReady(true);
          tryJoinRunStream(status.run_id, status.run_status);
        }
      } catch (bootstrapError) {
        console.error("Failed to sync sandbox bootstrap status", bootstrapError);
        setIsEnvironmentBootstrapHydrated(true);
      }
    };

    void syncBootstrapStatus();
  }, [
    enableEnvironmentInitialization,
    threadId,
    tryJoinRunStream,
    watchBootstrapUntilSettled,
  ]);

  const initializeEnvironmentForPrompt = useCallback(
    async (prompt: string) => {
      const shouldInitializeEnvironment =
        enableEnvironmentInitialization &&
        threadId.length > 0 &&
        !isEnvironmentReady &&
        messageCount === 0;

      if (!shouldInitializeEnvironment) {
        return false;
      }

      const currentEpoch = bootstrapPollEpochRef.current;
      const bootstrapStart = await startSandboxThreadBootstrap(threadId, {
        message: prompt,
        stream_mode: ["messages-tuple"],
      });
      if (bootstrapPollEpochRef.current !== currentEpoch) {
        return true;
      }

      setEnvironmentInitDisplay(buildEnvironmentDisplayFromBootstrap(bootstrapStart));
      bootstrapStreamSeqRef.current = Math.max(
        bootstrapStreamSeqRef.current,
        bootstrapStart.event_seq ?? 0,
      );
      tryJoinRunStream(bootstrapStart.run_id, bootstrapStart.run_status);

      if (bootstrapStart.status === "error") {
        const initError = bootstrapStart.error?.trim() || "环境初始化失败";
        throw new Error(initError);
      }

      if (bootstrapStart.status === "running") {
        const settledStatus = await watchBootstrapUntilSettled(
          threadId,
          bootstrapStart.request_id,
          currentEpoch,
        );
        if (!settledStatus) return true;
        if (settledStatus.status === "error") {
          throw new Error(settledStatus.error?.trim() || "环境初始化失败");
        }
        if (settledStatus.status !== "success") {
          throw new Error("环境初始化未完成，请稍后重试");
        }
        return true;
      }

      if (bootstrapStart.status === "success") {
        setIsEnvironmentReady(true);
        return true;
      }

      return true;
    },
    [
      enableEnvironmentInitialization,
      isEnvironmentReady,
      messageCount,
      threadId,
      tryJoinRunStream,
      watchBootstrapUntilSettled,
    ],
  );

  const resetEnvironmentInitialization = useCallback(async () => {
    if (!enableEnvironmentInitialization) return;
    if (!threadId) return;
    if (isEnvironmentResetting) return;

    const nextEpoch = bootstrapPollEpochRef.current + 1;
    bootstrapPollEpochRef.current = nextEpoch;
    bootstrapStreamAbortRef.current?.abort();
    bootstrapStreamAbortRef.current = null;
    bootstrapStreamSeqRef.current = 0;
    joinedRunIdsRef.current.clear();

    setIsEnvironmentResetting(true);
    try {
      const resetResult = await resetSandboxThreadBootstrap(threadId, {
        destroy_container: true,
      });
      if (bootstrapPollEpochRef.current !== nextEpoch) return;
      setIsEnvironmentReady(false);
      setEnvironmentInitDisplay(buildEnvironmentResetDisplay(resetResult));
      const resetFailed =
        resetResult.reset_success === false ||
        (typeof resetResult.reset_error === "string" &&
          resetResult.reset_error.trim().length > 0);
      if (resetFailed) {
        throw new Error(
          resetResult.reset_error?.trim() || "环境初始化重置失败，请重试。",
        );
      }
    } finally {
      setIsEnvironmentResetting(false);
    }
  }, [
    enableEnvironmentInitialization,
    isEnvironmentResetting,
    threadId,
  ]);

  const isEnvironmentInitializing =
    enableEnvironmentInitialization &&
    threadId.length > 0 &&
    !isEnvironmentReady &&
    environmentInitDisplay?.status === "running";

  return {
    environmentInitDisplay,
    initializeEnvironmentForPrompt,
    isEnvironmentBootstrapHydrated,
    isEnvironmentInitializing,
    isEnvironmentReady,
    isEnvironmentResetting,
    resetEnvironmentInitialization,
  };
}
