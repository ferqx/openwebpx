import { Tabs } from '@/components/ui/tabs';
import { CreateEnvironmentDialog } from '@/business/portal/create-environment-dialog';
import { PortalCodeReviewContinueFixDialog } from '@/business/portal/portal-code-review-continue-fix-dialog';
import { PortalDeleteTaskDialog } from '@/business/portal/portal-delete-task-dialog';
import { PortalHeader } from '@/business/portal/portal-header';
import { PortalCodeReviewSettingsSheet } from '@/business/portal/portal-code-review-settings-sheet';
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
            value={controller.tab}
            onValueChange={(value) =>
              controller.onTabChange(value as PortalTab)
            }
          >
            <div className="sticky top-0 z-10 bg-background">
              <PortalHeader
                onLogoClick={controller.onLogoClick}
                onSettingsClick={controller.onSettingsClick}
                onLogout={controller.onLogout}
              />
              <div className="mx-auto mt-4 max-w-3xl space-y-5">
                <h1 className="text-center text-3xl tracking-tight">
                  你可以提问让它帮你写代码，或者审查你的改动
                </h1>
                <PortalPromptPanel {...controller.promptPanelProps} />
                <PortalTaskToolbar {...controller.taskToolbarProps} />
              </div>
            </div>
            <div className="mx-auto w-full max-w-3xl">
              <PortalTaskContent {...controller.taskContentProps} />
            </div>
          </Tabs>
        </section>
      </div>

      <PortalDeleteTaskDialog {...controller.deleteTaskDialogProps} />
      <ScmOauthDialog {...controller.scmOauthDialogProps} />
      <CreateEnvironmentDialog {...controller.createEnvironmentDialogProps} />
      <PortalCodeReviewSettingsSheet
        {...controller.codeReviewSettingsSheetProps}
      />
      <PortalCodeReviewContinueFixDialog
        {...controller.codeReviewContinueFixDialogProps}
      />
    </main>
  );
}
