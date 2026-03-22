import { type ScmProvider } from '@/lib/scm';

export type PortalTab = 'tasks' | 'review';

export const portalTabs = ['tasks', 'review'] as const satisfies readonly PortalTab[];

export const isPortalTab = (value: unknown): value is PortalTab =>
  value === 'tasks' || value === 'review';

export const resolvePortalRouteTab = (
  value: unknown
): PortalTab | undefined => {
  if (isPortalTab(value)) {
    return value;
  }
  return undefined;
};

export type PortalRouteState = {
  portalTab?: PortalTab;
};

export type PortalScmSource = {
  key: string;
  label: string;
  provider: ScmProvider;
  gitlabBaseUrl?: string;
};

export type PortalScmRepositoryOption = {
  key: string;
  fullName: string;
  defaultBranch?: string;
  source: PortalScmSource;
};
