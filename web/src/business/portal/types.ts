import { type ScmProvider } from '@/lib/scm';

export type PortalTab = 'tasks';

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
