import { memo, useMemo } from 'react';
import { ThreadChatDiffViewer } from '@/business/thread-chat/thread-chat-diff-viewer';
import { type ThreadChatConversationFileChange } from '@/business/thread-chat/thread-chat-message-utils';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger
} from '@/components/ui/accordion';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

type ThreadChatFileChangeSummaryProps = {
  fileChanges: ThreadChatConversationFileChange[];
  title?: string;
};

export const ThreadChatFileChangeSummary = memo(
  ({ fileChanges, title }: ThreadChatFileChangeSummaryProps) => {
    const totals = useMemo(
      () =>
        fileChanges.reduce(
          (acc, change) => ({
            added: acc.added + change.added,
            removed: acc.removed + change.removed
          }),
          {
            added: 0,
            removed: 0
          }
        ),
      [fileChanges]
    );

    return (
      <Card className="w-full gap-0 py-0">
        <CardHeader className="py-2">
          <CardTitle>
            <div className="min-w-0">
              {title?.trim() ? (
                <p className="mb-1 text-neutral-400 text-xs">{title}</p>
              ) : null}
              <p className="text-neutral-400 text-xs">
                <span className="mr-2">{fileChanges.length} 个文件</span>
                <span className="mr-1 font-semibold text-emerald-600">
                  +{totals.added}
                </span>
                <span className="font-semibold text-red-400">
                  -{totals.removed}
                </span>
              </p>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Accordion className="w-full" type="multiple">
            {fileChanges.map((change) => (
              <AccordionItem
                className="border-b px-4 last:border-b-0"
                key={change.id}
                value={change.id}
              >
                <AccordionTrigger className="hover:no-underline !hover:no-underline cursor-pointer">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs">
                      <span className="truncate font-semibold">
                        {change.filePath}
                      </span>
                      <span className="font-semibold text-emerald-600">
                        +{change.added}
                      </span>
                      <span className="mr-1 font-semibold text-red-400">
                        -{change.removed}
                      </span>
                    </div>
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <ThreadChatDiffViewer
                    diffHunks={change.diffHunks}
                    diffLineMode={change.diffLineMode}
                    diffLineOffset={change.diffLineOffset}
                    filePath={change.filePath}
                    newValue={change.diffNewValue}
                    oldValue={change.diffOldValue}
                  />
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </CardContent>
      </Card>
    );
  }
);

ThreadChatFileChangeSummary.displayName = 'ThreadChatFileChangeSummary';
