import test from "node:test";
import assert from "node:assert/strict";

import {
  getApplyPatchChangeCount,
  getApplyPatchContent,
  getApplyPatchDiffHunks,
  getApplyPatchDiffValues,
  getApplyPatchFilePaths,
} from "../../src/hooks/thread-chat-diff-utils.ts";

test("extracts apply_patch content and file paths", () => {
  const patchContent = `*** Begin Patch
*** Add File: packages/components/src/theme/common/dark.scss
+:root[data-theme="dark"] {}
*** Update File: packages/components/src/theme/index.scss
@@ add-import
 @use './search.scss';
+@use './common/dark.scss';
*** End Patch`;

  assert.equal(
    getApplyPatchContent({ patch_content: patchContent }),
    patchContent,
  );
  assert.deepEqual(getApplyPatchFilePaths(patchContent), [
    "packages/components/src/theme/common/dark.scss",
    "packages/components/src/theme/index.scss",
  ]);
  assert.equal(
    getApplyPatchContent(JSON.stringify({ patch_content: patchContent })),
    patchContent,
  );
});

test("builds diff values and change counts from apply_patch payload", () => {
  const patchContent = `*** Begin Patch
*** Update File: app/main.ts
@@ update-main
 const mode = "light";
-const enabled = false;
+const enabled = true;
*** Add File: app/theme.ts
+export const theme = "dark";
*** End Patch`;

  const diffValues = getApplyPatchDiffValues(patchContent);
  assert.equal(diffValues.oldValue.includes('const enabled = false;'), true);
  assert.equal(diffValues.newValue.includes('const enabled = true;'), true);
  assert.equal(
    diffValues.newValue.includes('export const theme = "dark";'),
    true,
  );

  const changeCount = getApplyPatchChangeCount(patchContent);
  assert.deepEqual(changeCount, { added: 2, removed: 1 });
});

test("parses raw Add File bodies from apply_patch payload", () => {
  const patchContent = `*** Begin Patch
*** Add File: /workspace/toolChangeDisplay-example.vue
<template>
  <div>
    <NovaQuillEditor
      ref="quillEditorRef"
      v-model="content"
      :toolbarTheme="showToolbar ? 'full' : []"
    />
  </div>
</template>
*** End Patch`;

  const diffValues = getApplyPatchDiffValues(patchContent);
  assert.equal(diffValues.oldValue, "");
  assert.equal(diffValues.newValue.includes("<template>"), true);
  assert.equal(diffValues.newValue.includes("NovaQuillEditor"), true);

  const changeCount = getApplyPatchChangeCount(patchContent);
  assert.deepEqual(changeCount, { added: 9, removed: 0 });
});

test("extracts absolute hunk line numbers from apply_patch payload", () => {
  const patchContent = `*** Begin Patch
*** Update File: app/main.ts
@@ -42,2 +42,2 @@
 const mode = "light";
-const enabled = false;
+const enabled = true;
@@ -90,0 +90,2 @@
+const trace = true;
+const verbose = false;
*** End Patch`;

  assert.deepEqual(getApplyPatchDiffHunks(patchContent), [
    { oldStart: 42, oldCount: 2, newStart: 42, newCount: 2 },
    { oldStart: 90, oldCount: 0, newStart: 90, newCount: 2 },
  ]);
});

test("parses search/replace apply_patch payload into diff values and counts", () => {
  const patchContent = `*** Begin Patch
*** Update File: packages/components/src/theme/search-form.scss
<search>
  gap: 16px;
</search>
<replace>
  gap: 20px;
  padding: 20px;
</replace>
*** End Patch`;

  const diffValues = getApplyPatchDiffValues(patchContent);
  assert.equal(diffValues.oldValue.includes("gap: 16px;"), true);
  assert.equal(diffValues.newValue.includes("gap: 20px;"), true);
  assert.equal(diffValues.newValue.includes("padding: 20px;"), true);

  const changeCount = getApplyPatchChangeCount(patchContent);
  assert.deepEqual(changeCount, { added: 2, removed: 1 });
});

test("aggregates unified hunks and search/replace blocks in one apply_patch payload", () => {
  const patchContent = `*** Begin Patch
*** Update File: app/main.ts
@@ -1,2 +1,3 @@
 const mode = "light";
-const enabled = false;
+const enabled = true;
+const theme = "dark";
*** Update File: app/theme.ts
<search>
  color: #000;
</search>
<replace>
  color: #111;
  background: #fff;
</replace>
*** End Patch`;

  const changeCount = getApplyPatchChangeCount(patchContent);
  assert.deepEqual(changeCount, { added: 2, removed: 1 });
});

test("counts large repetitive search/replace patches exactly", () => {
  const oldLines = [...Array.from({ length: 2500 }, () => "a"), "x", ...Array.from({ length: 2500 }, () => "a")];
  const newLines = [...Array.from({ length: 2500 }, () => "a"), "y", ...Array.from({ length: 2500 }, () => "a")];
  const patchContent = `*** Begin Patch
*** Update File: app/theme.scss
<search>
${oldLines.join("\n")}
</search>
<replace>
${newLines.join("\n")}
</replace>
*** End Patch`;

  const changeCount = getApplyPatchChangeCount(patchContent);
  assert.deepEqual(changeCount, { added: 1, removed: 1 });
});
