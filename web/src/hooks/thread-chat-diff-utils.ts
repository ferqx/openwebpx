export const APPLY_PATCH_FILE_HEADER_RE =
  /^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$/;
export const APPLY_PATCH_HUNK_HEADER_RE =
  /^@@\s*-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s*@@/;

export type ApplyPatchDiffHunk = {
  oldStart: number;
  oldCount: number;
  newStart: number;
  newCount: number;
};

type SearchReplaceBlock = {
  search: string;
  replace: string;
};

type RawFileSection = {
  action: "Add" | "Delete";
  content: string;
};

const parseSearchReplaceBlocks = (patchContent: string): SearchReplaceBlock[] => {
  const searchBlocks: string[] = [];
  const replaceBlocks: string[] = [];
  let activeTag: "search" | "replace" | null = null;
  let buffer: string[] = [];

  const flush = () => {
    if (!activeTag) return;
    const value = buffer.join("\n");
    if (activeTag === "search") searchBlocks.push(value);
    if (activeTag === "replace") replaceBlocks.push(value);
    activeTag = null;
    buffer = [];
  };

  patchContent.split("\n").forEach((line) => {
    const marker = line.trim().toLowerCase();
    if (marker === "<search>" || marker === "<replace>") {
      flush();
      activeTag = marker === "<search>" ? "search" : "replace";
      return;
    }
    if (marker === "</search>" || marker === "</replace>") {
      flush();
      return;
    }
    if (activeTag) buffer.push(line);
  });
  flush();

  const count = Math.max(searchBlocks.length, replaceBlocks.length);
  const blocks: SearchReplaceBlock[] = [];
  for (let index = 0; index < count; index += 1) {
    blocks.push({
      search: searchBlocks[index] ?? "",
      replace: replaceBlocks[index] ?? "",
    });
  }
  return blocks;
};

const normalizeLegacySectionLines = (lines: string[], prefix: "+" | "-") => {
  const nonEmptyLines = lines.filter((line) => line.length > 0);
  if (
    nonEmptyLines.length > 0 &&
    nonEmptyLines.every((line) => line.startsWith(prefix))
  ) {
    return lines.map((line) => (line.startsWith(prefix) ? line.slice(1) : line));
  }
  return lines;
};

const parseRawAddDeleteSections = (patchContent: string): RawFileSection[] => {
  const sections: RawFileSection[] = [];
  let activeAction: RawFileSection["action"] | null = null;
  let buffer: string[] = [];

  const flush = () => {
    if (!activeAction) return;
    const rawNonEmptyLines = buffer.filter((line) => line.length > 0);
    const usesRawBody =
      rawNonEmptyLines.length > 0 &&
      !rawNonEmptyLines.every((line) =>
        line.startsWith(activeAction === "Add" ? "+" : "-"),
      );
    const normalizedLines = normalizeLegacySectionLines(
      buffer,
      activeAction === "Add" ? "+" : "-",
    );
    if (usesRawBody) {
      sections.push({
        action: activeAction,
        content: normalizedLines.join("\n"),
      });
    }
    activeAction = null;
    buffer = [];
  };

  patchContent.split("\n").forEach((line) => {
    if (/^\*\*\* Add File:\s*(.+?)\s*$/.test(line)) {
      flush();
      activeAction = "Add";
      return;
    }
    if (/^\*\*\* Delete File:\s*(.+?)\s*$/.test(line)) {
      flush();
      activeAction = "Delete";
      return;
    }
    if (
      /^\*\*\* Update File:\s*(.+?)\s*$/.test(line) ||
      line === "*** Begin Patch" ||
      line === "*** End Patch"
    ) {
      flush();
      return;
    }
    if (!activeAction) return;
    buffer.push(line);
  });

  flush();
  return sections;
};

const getLineDiffCount = (oldText: string, newText: string) => {
  const oldLines = oldText.trim() ? oldText.split("\n") : [];
  const newLines = newText.trim() ? newText.split("\n") : [];

  if (oldLines.length === 0 && newLines.length === 0) {
    return { added: 0, removed: 0 };
  }
  if (oldLines.length === 0) {
    return { added: newLines.length, removed: 0 };
  }
  if (newLines.length === 0) {
    return { added: 0, removed: oldLines.length };
  }

  // Myers computes the shortest edit script exactly without the O(n*m) memory cost.
  const frontier = new Map<number, number>([[1, 0]]);
  const oldLength = oldLines.length;
  const newLength = newLines.length;

  for (let distance = 0; distance <= oldLength + newLength; distance += 1) {
    for (let diagonal = -distance; diagonal <= distance; diagonal += 2) {
      const down = frontier.get(diagonal + 1) ?? 0;
      const right = frontier.get(diagonal - 1) ?? 0;
      let oldIndex =
        diagonal === -distance ||
        (diagonal !== distance && right < down)
          ? down
          : right + 1;
      let newIndex = oldIndex - diagonal;

      while (
        oldIndex < oldLength &&
        newIndex < newLength &&
        oldLines[oldIndex] === newLines[newIndex]
      ) {
        oldIndex += 1;
        newIndex += 1;
      }

      frontier.set(diagonal, oldIndex);
      if (oldIndex >= oldLength && newIndex >= newLength) {
        const delta = newLength - oldLength;
        const added = (distance + delta) / 2;
        return {
          added,
          removed: distance - added,
        };
      }
    }
  }

  return {
    added: newLength,
    removed: oldLength,
  };
};

export const getApplyPatchContent = (toolCallArgs: unknown) => {
  if (toolCallArgs == null) return "";
  let normalizedArgs: unknown = toolCallArgs;
  if (typeof toolCallArgs === "string") {
    try {
      normalizedArgs = JSON.parse(toolCallArgs) as unknown;
    } catch {
      return "";
    }
  }
  if (typeof normalizedArgs !== "object") return "";
  const patchContent = (normalizedArgs as { patch_content?: unknown }).patch_content;
  if (typeof patchContent !== "string") return "";
  return patchContent;
};

export const getApplyPatchFilePaths = (patchContent: string) => {
  const paths: string[] = [];
  const seen = new Set<string>();
  patchContent.split("\n").forEach((line) => {
    const match = line.match(APPLY_PATCH_FILE_HEADER_RE);
    if (!match?.[1]) return;
    const path = match[1].trim();
    if (!path || seen.has(path)) return;
    seen.add(path);
    paths.push(path);
  });
  return paths;
};

export const getApplyPatchDiffValues = (patchContent: string) => {
  if (!patchContent.trim()) return { oldValue: "", newValue: "" };

  const oldLines: string[] = [];
  const newLines: string[] = [];
  let inUpdateHunk = false;
  let inAddSection = false;
  let inDeleteSection = false;

  patchContent.split("\n").forEach((line) => {
    if (/^\*\*\* Add File:\s*(.+?)\s*$/.test(line)) {
      inUpdateHunk = false;
      inAddSection = true;
      inDeleteSection = false;
      return;
    }

    if (/^\*\*\* Update File:\s*(.+?)\s*$/.test(line)) {
      inUpdateHunk = false;
      inAddSection = false;
      inDeleteSection = false;
      return;
    }

    if (/^\*\*\* Delete File:\s*(.+?)\s*$/.test(line)) {
      inUpdateHunk = false;
      inAddSection = false;
      inDeleteSection = true;
      return;
    }

    if (line.startsWith("@@")) {
      inUpdateHunk = true;
      inAddSection = false;
      inDeleteSection = false;
      return;
    }

    if (line.startsWith("*** ")) return;

    if (inAddSection && line.startsWith("+")) {
      newLines.push(line.slice(1));
      return;
    }

    if (inDeleteSection && line.startsWith("-")) {
      oldLines.push(line.slice(1));
      return;
    }

    if (!inUpdateHunk) return;
    if (line.startsWith(" ")) {
      const context = line.slice(1);
      oldLines.push(context);
      newLines.push(context);
      return;
    }
    if (line.startsWith("-")) {
      oldLines.push(line.slice(1));
      return;
    }
    if (line.startsWith("+")) {
      newLines.push(line.slice(1));
    }
  });

  const rawSections = parseRawAddDeleteSections(patchContent);
  rawSections.forEach((section) => {
    if (!section.content.trim()) return;
    if (section.action === "Add") {
      newLines.push(section.content);
      return;
    }
    oldLines.push(section.content);
  });

  if (oldLines.length === 0 && newLines.length === 0) {
    const blocks = parseSearchReplaceBlocks(patchContent);
    if (blocks.length > 0) {
      return {
        oldValue: blocks
          .map((block) => block.search.trim())
          .filter(Boolean)
          .join("\n\n"),
        newValue: blocks
          .map((block) => block.replace.trim())
          .filter(Boolean)
          .join("\n\n"),
      };
    }
  }

  return {
    oldValue: oldLines.join("\n"),
    newValue: newLines.join("\n"),
  };
};

export const getApplyPatchDiffHunks = (patchContent: string) => {
  if (!patchContent.trim()) return [] as ApplyPatchDiffHunk[];

  return patchContent
    .split("\n")
    .map((line) => {
      const match = line.match(APPLY_PATCH_HUNK_HEADER_RE);
      if (!match) return undefined;
      return {
        oldStart: Number.parseInt(match[1] ?? "0", 10),
        oldCount: Number.parseInt(match[2] ?? "1", 10),
        newStart: Number.parseInt(match[3] ?? "0", 10),
        newCount: Number.parseInt(match[4] ?? "1", 10),
      };
    })
    .filter((hunk): hunk is ApplyPatchDiffHunk => Boolean(hunk));
};

export const getApplyPatchChangeCount = (patchContent: string) => {
  if (!patchContent.trim()) return { added: 0, removed: 0 };
  let added = 0;
  let removed = 0;

  patchContent.split("\n").forEach((line) => {
    if (!line) return;
    if (line.startsWith("+++ ") || line.startsWith("--- ")) return;
    if (line.startsWith("*** ")) return;
    if (line.startsWith("@@")) return;
    if (line.startsWith("+")) {
      added += 1;
      return;
    }
    if (line.startsWith("-")) {
      removed += 1;
    }
  });

  const rawSections = parseRawAddDeleteSections(patchContent);
  rawSections.forEach((section) => {
    const rawChange = getLineDiffCount(
      section.action === "Delete" ? section.content : "",
      section.action === "Add" ? section.content : "",
    );
    added += rawChange.added;
    removed += rawChange.removed;
  });

  const blocks = parseSearchReplaceBlocks(patchContent);
  if (blocks.length > 0 && added === 0 && removed === 0) {
    const blockChangeCount = blocks.reduce(
      (acc, block) => {
        const blockDiff = getLineDiffCount(block.search, block.replace);
        return {
          added: acc.added + blockDiff.added,
          removed: acc.removed + blockDiff.removed,
        };
      },
      { added: 0, removed: 0 },
    );
    return blockChangeCount;
  }

  return { added, removed };
};
