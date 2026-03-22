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
  const [autoFixFilter, setAutoFixFilter] = useState<'all' | 'fixable'>('all');
  const [fileQuery, setFileQuery] = useState('');

  const visibleFindings = useMemo(() => {
    const normalizedQuery = fileQuery.trim().toLowerCase();
    return findings.filter((finding) => {
      const matchesSeverity =
        severityFilter === 'all'
          ? true
          : finding.severity.toLowerCase() === severityFilter;
      const matchesAutoFix =
        autoFixFilter === 'fixable' ? finding.can_auto_fix : true;
      const matchesFile =
        normalizedQuery.length === 0
          ? true
          : (finding.file_path ?? '').toLowerCase().includes(normalizedQuery);
      return matchesSeverity && matchesAutoFix && matchesFile;
    });
  }, [autoFixFilter, fileQuery, findings, severityFilter]);

  return (
    <div className="space-y-4">
      <Card size="sm">
        <CardContent className="space-y-4 py-4">
          <div className="space-y-1">
            <p className="text-sm font-medium text-foreground">审查发现</p>
            <p className="text-xs text-muted-foreground">
              共 {findings.length} 项，当前显示 {visibleFindings.length} 项
            </p>
          </div>

          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_140px_160px]">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label="筛选文件路径"
                className="pl-9"
                placeholder="搜索文件路径"
                value={fileQuery}
                onChange={(event) => setFileQuery(event.target.value)}
              />
            </div>
            <Select
              value={severityFilter}
              onValueChange={(value) =>
                setSeverityFilter(value as FindingSeverityFilter)
              }
            >
              <SelectTrigger className="w-full" size="sm">
                <SelectValue placeholder="严重级别" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部级别</SelectItem>
                <SelectItem value="high">高</SelectItem>
                <SelectItem value="medium">中</SelectItem>
                <SelectItem value="low">低</SelectItem>
                <SelectItem value="info">信息</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={autoFixFilter}
              onValueChange={(value) =>
                setAutoFixFilter(value as 'all' | 'fixable')
              }
            >
              <SelectTrigger className="w-full" size="sm">
                <SelectValue placeholder="修复能力" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部发现</SelectItem>
                <SelectItem value="fixable">仅自动修复</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {visibleFindings.length === 0 ? (
        <Card size="sm">
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            当前没有匹配条件的审查发现
          </CardContent>
        </Card>
      ) : (
        <Accordion className="space-y-3" type="multiple">
          {visibleFindings.map((finding) => {
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
                <AccordionTrigger className="cursor-pointer py-3 hover:no-underline">
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge
                        variant="outline"
                        className={getFindingSeverityClassName(finding.severity)}
                      >
                        {finding.severity}
                      </Badge>
                      {finding.can_auto_fix ? (
                        <Badge variant="outline">可自动修复</Badge>
                      ) : null}
                      {finding.rule_id ? (
                        <Badge variant="outline">{finding.rule_id}</Badge>
                      ) : null}
                      {findingStatusById[finding.id] ? (
                        <Badge variant="outline">{findingStatusById[finding.id]}</Badge>
                      ) : null}
                    </div>
                    <div className="space-y-1 text-left">
                      <p className="text-sm font-medium text-foreground">
                        {finding.title}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {finding.file_path ?? '未知文件'}
                        {lineRange ? ` : ${lineRange}` : ''}
                      </p>
                    </div>
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-3 border-t py-3 text-sm">
                    <p className="whitespace-pre-wrap text-foreground">
                      {finding.body ?? '暂无附加说明'}
                    </p>
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
