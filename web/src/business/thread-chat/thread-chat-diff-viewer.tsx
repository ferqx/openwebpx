import {
  type CSSProperties,
  type ReactNode,
  useEffect,
  useMemo,
  useState
} from 'react';
import ReactDiffViewer from 'react-diff-viewer';
import { useTheme } from 'next-themes';
import { highlightCode } from '@/components/ai-elements/code-block';

type HighlightToken = {
  content: string;
  color?: string;
  htmlStyle?: CSSProperties;
};

type HighlightedResult = {
  tokens: HighlightToken[][];
};

const inferLanguageFromPath = (filePath?: string) => {
  const normalized = filePath?.trim().toLowerCase() ?? '';
  if (!normalized) return 'plaintext';

  const extension = normalized.split('.').pop() ?? '';
  const extensionMap: Record<string, string> = {
    cjs: 'javascript',
    css: 'css',
    scss: 'scss',
    less: 'less',
    go: 'go',
    html: 'html',
    java: 'java',
    js: 'javascript',
    json: 'json',
    jsx: 'javascript',
    md: 'markdown',
    mjs: 'javascript',
    py: 'python',
    rb: 'ruby',
    rs: 'rust',
    sh: 'shell',
    sql: 'sql',
    ts: 'typescript',
    tsx: 'typescript',
    txt: 'plaintext',
    vue: 'html',
    xml: 'xml',
    yaml: 'yaml',
    yml: 'yaml'
  };

  return extensionMap[extension] ?? 'plaintext';
};

const mapToShikiLanguage = (language: string) => {
  const mapping: Record<string, string> = {
    plaintext: 'text',
    shell: 'bash'
  };

  return mapping[language] ?? language;
};

const createLineHighlightMap = (result: HighlightedResult | null) => {
  const map = new Map<string, ReactNode>();
  if (!result) return map;

  result.tokens.forEach((lineTokens) => {
    const lineText = lineTokens.map((token) => token.content).join('');
    if (!lineText || map.has(lineText)) return;

    map.set(
      lineText,
      <span>
        {lineTokens.map((token, index) => (
          <span
            key={`${lineText}-${index}`}
            style={{
              color: token.color,
              ...token.htmlStyle
            }}
          >
            {token.content}
          </span>
        ))}
      </span>
    );
  });

  return map;
};

type ThreadChatDiffViewerProps = {
  filePath?: string;
  oldValue?: string;
  newValue?: string;
  diffLineOffset?: number;
  diffLineMode?: 'absolute' | 'relative';
  diffHunks?: Array<{
    oldStart: number;
    oldCount: number;
    newStart: number;
    newCount: number;
  }>;
  diffSections?: Array<{
    id: string;
    filePath?: string;
    oldValue?: string;
    newValue?: string;
    diffLineOffset?: number;
    diffLineMode?: 'absolute' | 'relative';
    diffHunks?: Array<{
      oldStart: number;
      oldCount: number;
      newStart: number;
      newCount: number;
    }>;
  }>;
};

const HIGHLIGHT_CHAR_LIMIT = 12_000;

export const ThreadChatDiffViewer = ({
  filePath,
  oldValue,
  newValue,
  diffLineOffset,
  diffLineMode,
  diffHunks,
  diffSections
}: ThreadChatDiffViewerProps) => {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';
  const language = inferLanguageFromPath(filePath);
  const shikiLanguage = mapToShikiLanguage(language);
  const shouldDisableHighlight =
    (oldValue?.length ?? 0) + (newValue?.length ?? 0) > HIGHLIGHT_CHAR_LIMIT;

  const [oldAsync, setOldAsync] = useState<HighlightedResult | null>(null);
  const [newAsync, setNewAsync] = useState<HighlightedResult | null>(null);

  const oldSync = useMemo(
    () =>
      shouldDisableHighlight
        ? null
        : ((highlightCode(
            oldValue ?? '',
            shikiLanguage as Parameters<typeof highlightCode>[1]
          ) as HighlightedResult | null) ?? null),
    [oldValue, shikiLanguage, shouldDisableHighlight]
  );

  const newSync = useMemo(
    () =>
      shouldDisableHighlight
        ? null
        : ((highlightCode(
            newValue ?? '',
            shikiLanguage as Parameters<typeof highlightCode>[1]
          ) as HighlightedResult | null) ?? null),
    [newValue, shikiLanguage, shouldDisableHighlight]
  );

  useEffect(() => {
    let cancelled = false;
    if (shouldDisableHighlight) return undefined;

    highlightCode(
      oldValue ?? '',
      shikiLanguage as Parameters<typeof highlightCode>[1],
      (result) => {
        if (!cancelled) setOldAsync(result as HighlightedResult);
      }
    );

    return () => {
      cancelled = true;
    };
  }, [oldValue, shikiLanguage, shouldDisableHighlight]);

  useEffect(() => {
    let cancelled = false;
    if (shouldDisableHighlight) return undefined;

    highlightCode(
      newValue ?? '',
      shikiLanguage as Parameters<typeof highlightCode>[1],
      (result) => {
        if (!cancelled) setNewAsync(result as HighlightedResult);
      }
    );

    return () => {
      cancelled = true;
    };
  }, [newValue, shikiLanguage, shouldDisableHighlight]);

  const highlightedLineMap = useMemo(() => {
    const map = new Map<string, ReactNode>();
    const oldMap = createLineHighlightMap(oldAsync ?? oldSync);
    const newMap = createLineHighlightMap(newAsync ?? newSync);

    oldMap.forEach((value, key) => map.set(key, value));
    newMap.forEach((value, key) => {
      if (!map.has(key)) map.set(key, value);
    });

    return map;
  }, [newAsync, newSync, oldAsync, oldSync]);

  const hunkLabel = useMemo(() => {
    const firstHunk = diffHunks?.[0];
    if (!firstHunk) return undefined;
    const first = `@@ -${firstHunk.oldStart},${firstHunk.oldCount} +${firstHunk.newStart},${firstHunk.newCount}`;
    if ((diffHunks?.length ?? 0) <= 1) return first;
    return `${first} (+${(diffHunks?.length ?? 1) - 1})`;
  }, [diffHunks]);

  const normalizedSections = useMemo(() => {
    if (!diffSections || diffSections.length === 0) {
      return [
        {
          id: 'default',
          filePath,
          oldValue: oldValue ?? '',
          newValue: newValue ?? '',
          diffLineOffset,
          diffLineMode,
          diffHunks
        }
      ];
    }

    return diffSections.map((section) => ({
      id: section.id,
      filePath: section.filePath ?? filePath,
      oldValue: section.oldValue ?? '',
      newValue: section.newValue ?? '',
      diffLineOffset: section.diffLineOffset,
      diffLineMode: section.diffLineMode,
      diffHunks: section.diffHunks
    }));
  }, [
    diffHunks,
    diffLineMode,
    diffLineOffset,
    diffSections,
    filePath,
    newValue,
    oldValue
  ]);

  const diffStyles = useMemo(
    () =>
      isDark
        ? {
            contentText: {
              fontFamily:
                'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
              fontSize: '12px',
              color: '#c9d1d9'
            },
            diffContainer: {
              border: 0
            },
            gutter: {
              background: '#161b22',
              color: '#8b949e',
              borderColor: '#30363d'
            },
            line: {
              padding: '0.2rem 0'
            },
            marker: {
              minWidth: '1.5rem',
              padding: '0 0.5rem',
              color: '#8b949e'
            },
            wordDiff: {
              padding: 0
            },
            diffRemoved: {
              background: '#3f1f24'
            },
            diffAdded: {
              background: '#1f3a2a'
            },
            highlightedGutter: {
              background: '#21262d'
            },
            highlightedLine: {
              background: '#161b22'
            },
            removedGutter: {
              background: '#4c1f24',
              color: '#f85149'
            },
            addedGutter: {
              background: '#1a3526',
              color: '#3fb950'
            },
            removedLine: {
              background: '#3f1f24',
              color: '#ffdcd7'
            },
            addedLine: {
              background: '#1f3a2a',
              color: '#aff5b4'
            },
            wordAdded: {
              background: '#2f6f44',
              color: '#aff5b4'
            },
            wordRemoved: {
              background: '#6e2a31',
              color: '#ffdcd7'
            }
          }
        : {
            contentText: {
              fontFamily:
                'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
              fontSize: '12px'
            },
            diffContainer: {
              border: 0
            },
            line: {
              padding: '0.2rem 0'
            },
            marker: {
              minWidth: '1.5rem',
              padding: '0 0.5rem'
            }
          },
    [isDark]
  );

  return (
    <div className="overflow-hidden rounded-md border bg-background">
      <div className="flex items-center justify-between gap-3 border-b bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
        <span className="truncate font-mono">
          {filePath?.trim() ? filePath : '未命名文件'}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          {hunkLabel ? (
            <span className="max-w-[24rem] truncate rounded-sm border bg-background px-1.5 py-0.5 font-mono text-[10px]">
              {hunkLabel}
            </span>
          ) : null}
          <span className="rounded-sm border bg-background px-1.5 py-0.5 font-mono text-[10px] uppercase">
            {language}
          </span>
        </div>
      </div>
      <div className="min-h-0 max-h-70 flex-1 overflow-x-scroll overflow-y-auto">
        <div className="divide-y">
          {normalizedSections.map((section, index) => {
            const sectionLinesOffset =
              section.diffLineMode !== 'absolute'
                ? 0
                : typeof section.diffLineOffset === 'number' &&
                    Number.isInteger(section.diffLineOffset) &&
                    section.diffLineOffset >= 0
                  ? section.diffLineOffset
                  : (() => {
                      const firstHunk = section.diffHunks?.[0];
                      if (!firstHunk) return 0;
                      const absoluteStart =
                        firstHunk.oldStart > 0
                          ? firstHunk.oldStart
                          : firstHunk.newStart > 0
                            ? firstHunk.newStart
                            : undefined;
                      return absoluteStart ? absoluteStart - 1 : 0;
                    })();

            const sectionHunkLabel = (() => {
              const firstHunk = section.diffHunks?.[0];
              if (!firstHunk) return undefined;
              const first = `@@ -${firstHunk.oldStart},${firstHunk.oldCount} +${firstHunk.newStart},${firstHunk.newCount}`;
              if ((section.diffHunks?.length ?? 0) <= 1) return first;
              return `${first} (+${(section.diffHunks?.length ?? 1) - 1})`;
            })();

            return (
              <div
                key={section.id}
                className={index > 0 ? 'border-t bg-muted/15' : ''}
              >
                {normalizedSections.length > 1 ? (
                  <div className="flex items-center justify-between gap-3 border-b bg-muted/35 px-3 py-2 text-[10px] text-muted-foreground">
                    <span>第 {index + 1} 段</span>
                    {sectionHunkLabel ? (
                      <span className="rounded-sm border bg-background px-1.5 py-0.5 font-mono">
                        {sectionHunkLabel}
                      </span>
                    ) : null}
                  </div>
                ) : null}
                <ReactDiffViewer
                  disableWordDiff={true}
                  hideLineNumbers={false}
                  linesOffset={sectionLinesOffset}
                  newValue={section.newValue}
                  oldValue={section.oldValue}
                  renderContent={(line) => (
                    <code className="font-mono text-xs">
                      {highlightedLineMap.get(line) ?? line}
                    </code>
                  )}
                  showDiffOnly={false}
                  splitView={false}
                  styles={diffStyles}
                  useDarkTheme={isDark}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
