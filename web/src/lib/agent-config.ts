type AgentConfig = {
  assistantId: string;
  graphId: string;
};

const TASK_ASSISTANT_ID =
  import.meta.env.VITE_TASK_ASSISTANT_ID?.trim() || 'build_app_agent_v3';
const TASK_GRAPH_ID =
  import.meta.env.VITE_TASK_GRAPH_ID?.trim() || TASK_ASSISTANT_ID;

const CHAT_ASSISTANT_ID =
  import.meta.env.VITE_CHAT_ASSISTANT_ID?.trim() || TASK_ASSISTANT_ID;
const CHAT_GRAPH_ID =
  import.meta.env.VITE_CHAT_GRAPH_ID?.trim() || CHAT_ASSISTANT_ID;

export const taskAgentConfig: AgentConfig = {
  assistantId: TASK_ASSISTANT_ID,
  graphId: TASK_GRAPH_ID
};

export const chatAgentConfig: AgentConfig = {
  assistantId: CHAT_ASSISTANT_ID,
  graphId: CHAT_GRAPH_ID
};

export const resolveAgentConfigByPath = (pathname: string): AgentConfig => {
  if (pathname.startsWith('/tasks/')) return taskAgentConfig;
  if (pathname.startsWith('/apps/')) return chatAgentConfig;
  return taskAgentConfig;
};
