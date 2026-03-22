import { type TaskItem } from '@/lib/tasks';

export type TaskRouteState = {
  task?: TaskItem;
  initialPrompt?: string;
  shouldAutoRun?: boolean;
  portalTab?: 'tasks' | 'review';
};

export const deriveInitialAutoRunState = (routeState: TaskRouteState | null) => {
  const shouldAutoRun = Boolean(routeState?.shouldAutoRun);
  return {
    shouldAutoRun,
    prompt: shouldAutoRun ? (routeState?.initialPrompt?.trim() ?? '') : ''
  };
};

export const stripConsumedTaskRouteState = (routeState: TaskRouteState | null) => {
  if (!routeState?.shouldAutoRun) return routeState;
  const nextState: TaskRouteState = {};
  if (routeState.task) nextState.task = routeState.task;
  if (routeState.portalTab) nextState.portalTab = routeState.portalTab;
  return Object.keys(nextState).length > 0 ? nextState : null;
};

export const buildBackToPortalState = (routeState: TaskRouteState | null) => {
  return routeState?.portalTab ? { portalTab: routeState.portalTab } : undefined;
};
