import { Tabs } from '@/components/ui/tabs';
import { PortalCodeReviewContinueFixDialog } from '@/business/portal/portal-code-review-continue-fix-dialog';
import { PortalDeleteTaskDialog } from '@/business/portal/portal-delete-task-dialog';
import { PortalHeader } from '@/business/portal/portal-header';
import { PortalPromptPanel } from '@/business/portal/portal-prompt-panel';
import { PortalTaskContent } from '@/business/portal/portal-task-content';
import { PortalTaskToolbar } from '@/business/portal/portal-task-toolbar';
import { ScmOauthDialog } from '@/business/portal/scm-oauth-dialog';
import { usePortalPageController } from '@/hooks/use-portal-page-controller';
import { type PortalTab } from '@/business/portal/types';

export function PortalPage() {
  const controller = usePortalPageController();

  return (
    <main className="relative h-full overflow-auto bg-background">
      <div className="relative px-4 pb-8 md:px-8">
        <section>
          <Tabs
            className="flex flex-col space-y-2"
            onValueChange={(value) => controller.onTabChange(value as PortalTab)}
            value={controller.tab}
          >
            <div className="sticky top-0 z-10 space-y-4 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
              <PortalHeader
                onLogoClick={controller.onLogoClick}
                onSettingsClick={controller.onSettingsClick}
                onLogout={controller.onLogout}
              />
              <div className="mx-auto w-1/2 space-y-4">
                <PortalPromptPanel {...controller.promptPanelProps} />
                <PortalTaskToolbar {...controller.taskToolbarProps} />
              </div>
            </div>
            <div className="mx-auto w-1/2">
              <PortalTaskContent {...controller.taskContentProps} />
            </div>
          </Tabs>
        </section>
      </div>

      <PortalDeleteTaskDialog {...controller.deleteTaskDialogProps} />
      <ScmOauthDialog {...controller.scmOauthDialogProps} />
      <PortalCodeReviewContinueFixDialog
        {...controller.codeReviewContinueFixDialogProps}
      />
    </main>
  );
}
