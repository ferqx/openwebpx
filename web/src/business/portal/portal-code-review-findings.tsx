import React, { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger
} from '@/components/ui/accordion';
import { type CodeReviewFinding } from '@/business/portal/code-review-types';

type FindingSeverityFilter = 'all' | 'high' | 'medium' | 'low' | 'info';

const severityRank: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4
};

const getFindingSeverityClassName = (severity: string) => {
  switch (severity.toLowerCase()) {
    case 'high':
    case 'critical':
      return 'border-red-300 bg-red-50 text-red-700';
    case 'medium':
      return 'border-amber-300 bg-amber-50 text-amber-700';
    case 'low':
      return 'border-sky-300 bg-sky-50 text-sky-700';
    default:
      return 'border-border bg-muted/60 text-muted-foreground';
  }
};

type PortalCodeReviewFindingsProps = {
  findings: CodeReviewFinding[];
  findingStatusById?: Record<number, string>;
};

export function PortalCodeReviewFindings({
  findings,
  findingStatusById = {}
}: PortalCodeReviewFindingsProps) {
  const [severityFilter, setSeverityFilter] =
    useState<FindingSeverityFilter>('all');
  const [fileQuery, setFileQuery] = useState('');

  const sortedFindings = useMemo(() => {
    const normalizedQuery = fileQuery.trim().toLowerCase();
    return [...findings]
      .filter((finding) => {
        const matchesSeverity =
          severityFilter === 'all'
            ? true
            : finding.severity.toLowerCase() === severityFilter;
        const matchesFile =
          normalizedQuery.length === 0
            ? true
            : (finding.file_path ?? '').toLowerCase().includes(normalizedQuery);
        return matchesSeverity && matchesFile;
      })
      .sort((left, right) => {
        const leftRank = severityRank[left.severity.toLowerCase()] ?? Number.MAX_SAFE_INTEGER;
        const rightRank = severityRank[right.severity.toLowerCase()] ?? Number.MAX_SAFE_INTEGER;
        if (leftRank !== rightRank) {
          return leftRank - rightRank;
        }
        return left.id - right.id;
      });
  }, [fileQuery, findings, severityFilter]);

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 rounded-xl border bg-card/70 p-2.5 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="finding-search"
            aria-label="搜索文件路径"
            className="h-9 border-0 bg-background pl-9 text-sm shadow-none"
            placeholder="搜索文件路径"
            value={fileQuery}
            onChange={(event) => setFileQuery(event.target.value)}
          />
        </div>
        <div className="flex items-center gap-2 sm:justify-end">
          <span className="min-w-fit text-xs text-muted-foreground">
            {sortedFindings.length} / {findings.length}
          </span>
          <Select
            value={severityFilter}
            onValueChange={(value) =>
              setSeverityFilter(value as FindingSeverityFilter)
            }
          >
            <SelectTrigger aria-label="筛选级别" className="h-9 w-32 bg-background text-sm" size="sm">
              <SelectValue placeholder="级别" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部级别</SelectItem>
              <SelectItem value="high">高</SelectItem>
              <SelectItem value="medium">中</SelectItem>
              <SelectItem value="low">低</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {sortedFindings.length === 0 ? (
        <Card size="sm">
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            当前没有匹配条件的审查发现
          </CardContent>
        </Card>
      ) : (
        <Accordion
          className="space-y-2"
          type="single"
          collapsible
          defaultValue={sortedFindings[0]?.id ? `finding-${sortedFindings[0].id}` : undefined}
        >
          {sortedFindings.map((finding) => {
            const itemKey = `finding-${finding.id}`;
            const lineRange =
              finding.line_start === null
                ? ''
                : finding.line_end !== null && finding.line_end !== finding.line_start
                  ? `${finding.line_start}-${finding.line_end}`
                  : `${finding.line_start}`;

            return (
              <AccordionItem
                key={itemKey}
                value={itemKey}
                className="overflow-hidden rounded-xl border bg-card px-4"
              >
                <AccordionTrigger className="cursor-pointer py-2 hover:no-underline">
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-2 text-left">
                      <Badge
                        variant="outline"
                        className={`${getFindingSeverityClassName(finding.severity)} h-5 shrink-0 px-2 text-[11px]`}
                      >
                        {finding.severity}
                      </Badge>
                      <p className="line-clamp-1 flex-1 text-sm font-medium text-foreground">
                        {finding.title}
                      </p>
                      {finding.can_auto_fix ? (
                        <Badge variant="outline" className="h-5 shrink-0 px-2 text-[11px]">可自动修复</Badge>
                      ) : null}
                      {findingStatusById[finding.id] ? (
                        <Badge variant="outline" className="h-5 shrink-0 px-2 text-[11px]">
                          {findingStatusById[finding.id]}
                        </Badge>
                      ) : null}
                    </div>
                    <p className="line-clamp-1 text-xs text-muted-foreground">
                      {finding.file_path ?? '未知文件'}
                      {lineRange ? ` : ${lineRange}` : ''}
                    </p>
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-3 border-t py-3 text-sm">
                    <p className="whitespace-pre-wrap text-foreground">
                      {finding.body ?? '暂无附加说明'}
                    </p>
                    {finding.rule_id ? (
                      <p className="text-xs text-muted-foreground">
                        规则 {finding.rule_id}
                      </p>
                    ) : null}
                    {finding.category ? (
                      <p className="text-xs text-muted-foreground">
                        分类 {finding.category}
                      </p>
                    ) : null}
                  </div>
                </AccordionContent>
              </AccordionItem>
            );
          })}
        </Accordion>
      )}
    </div>
  );
}
