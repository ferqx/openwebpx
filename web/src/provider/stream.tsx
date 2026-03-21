import React, {
  createContext,
  useCallback,
  useEffect,
  useContext,
  useMemo,
  type ReactNode
} from 'react';
import { useStream } from '@langchain/langgraph-sdk/react';
import { type Message } from '@langchain/langgraph-sdk';
import { useThreads } from './thread';
import { client } from '@/lib/langgraph-sdk';
import { resolveAgentConfigByPath } from '@/lib/agent-config';
import { useLocation, useParams } from 'react-router-dom';

export type StateType = {
  messages: Message[];
  files?: Record<
    string,
    {
      content: string[];
      created_at: string;
      modified_at: string;
    }
  >;
  todos?: Array<{
    content: string;
    status: 'pending' | 'completed';
  }>;
};

const useTypedStream = useStream<
  StateType,
  {
    UpdateType: {
      messages?: Message[] | Message | string;
      context?: Record<string, unknown>;
    };
  }
>;

export type StreamContextType = ReturnType<typeof useTypedStream>;
const StreamContext = createContext<StreamContextType | undefined>(undefined);
const DEFAULT_STREAM_THROTTLE_MS = 48;

const resolveStreamThrottle = () => {
  const rawValue = import.meta.env.VITE_STREAM_THROTTLE_MS;
  if (rawValue == null || rawValue === '') return DEFAULT_STREAM_THROTTLE_MS;
  const parsed = Number.parseInt(rawValue, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return DEFAULT_STREAM_THROTTLE_MS;
  }
  return parsed;
};

const StreamSession = ({ children }: { children: ReactNode }) => {
  const params = useParams();
  const location = useLocation();
  const { getThreads } = useThreads();
  const threadId = params.id ?? null;

  useEffect(() => {
    void getThreads();
  }, [getThreads]);

  const activeAssistantId = useMemo(
    () => resolveAgentConfigByPath(location.pathname).assistantId,
    [location.pathname]
  );

  const handleThreadId = useCallback(() => {
    void getThreads();
  }, [getThreads]);

  const streamOptions = useMemo(
    () => ({
      client,
      assistantId: activeAssistantId,
      threadId: threadId ?? null,
      // Task detail only needs latest state + streaming continuation.
      // Skip full history state loading to reduce duplicate /state requests on init.
      fetchStateHistory: false,
      reconnectOnMount: Boolean(threadId),
      // Large historical threads can emit high-frequency partial events.
      // Use millisecond throttling to reduce frame drops on the chat page.
      throttle: resolveStreamThrottle(),
      onThreadId: handleThreadId
    }),
    [activeAssistantId, handleThreadId, threadId]
  );

  const streamValue = useTypedStream(streamOptions);

  return (
    <StreamContext.Provider value={streamValue}>
      {children}
    </StreamContext.Provider>
  );
};

export const StreamProvider: React.FC<{ children: ReactNode }> = ({
  children
}) => {
  return <StreamSession>{children}</StreamSession>;
};

// Create a custom hook to use the context
export const useStreamContext = (): StreamContextType => {
  const context = useContext(StreamContext);
  if (context === undefined) {
    throw new Error('useStreamContext must be used within a StreamProvider');
  }
  return context;
};

export default StreamContext;
