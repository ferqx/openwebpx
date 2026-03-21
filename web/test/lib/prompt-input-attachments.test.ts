import test from 'node:test';
import assert from 'node:assert/strict';
import {
  SUPPORTED_PROMPT_ATTACHMENT_ACCEPT,
  SUPPORTED_PROMPT_ATTACHMENT_HINT,
  getPromptAttachmentErrorMessage
} from '../../src/lib/prompt-input-attachments.ts';

test('SUPPORTED_PROMPT_ATTACHMENT_ACCEPT contains expected extensions', () => {
  const extensions = SUPPORTED_PROMPT_ATTACHMENT_ACCEPT.split(',');
  assert.ok(extensions.length > 0);
  assert.ok(extensions.includes('.txt'));
  assert.ok(extensions.includes('.md'));
  assert.ok(extensions.includes('.json'));
  assert.ok(extensions.includes('.ts'));
  assert.ok(extensions.includes('.tsx'));
  assert.ok(extensions.includes('.js'));
  assert.ok(extensions.includes('.py'));
});

test('SUPPORTED_PROMPT_ATTACHMENT_HINT is non-empty string', () => {
  assert.equal(typeof SUPPORTED_PROMPT_ATTACHMENT_HINT, 'string');
  assert.ok(SUPPORTED_PROMPT_ATTACHMENT_HINT.length > 0);
  assert.ok(SUPPORTED_PROMPT_ATTACHMENT_HINT.includes('txt'));
  assert.ok(SUPPORTED_PROMPT_ATTACHMENT_HINT.includes('md'));
  assert.ok(SUPPORTED_PROMPT_ATTACHMENT_HINT.includes('json'));
});

test('getPromptAttachmentErrorMessage handles accept error code', () => {
  const error = {
    code: 'accept' as const,
    message: 'Invalid file type'
  };
  const message = getPromptAttachmentErrorMessage(error);
  assert.ok(message.includes('仅支持文本、配置、表格和常见代码文件'));
  assert.ok(message.includes(SUPPORTED_PROMPT_ATTACHMENT_HINT));
});

test('getPromptAttachmentErrorMessage handles max_file_size error code', () => {
  const error = {
    code: 'max_file_size' as const,
    message: 'File too large'
  };
  const message = getPromptAttachmentErrorMessage(error);
  assert.equal(message, '文件过大，无法添加。请缩小后重试。');
});

test('getPromptAttachmentErrorMessage handles max_files error code', () => {
  const error = {
    code: 'max_files' as const,
    message: 'Too many files'
  };
  const message = getPromptAttachmentErrorMessage(error);
  assert.equal(message, '添加的文件数量超出限制，部分文件未加入。');
});

test('getPromptAttachmentErrorMessage falls back to error message for unknown code', () => {
  const error = {
    code: 'unknown' as 'accept' | 'max_file_size' | 'max_files',
    message: 'Something went wrong'
  };
  const message = getPromptAttachmentErrorMessage(error);
  assert.equal(message, 'Something went wrong');
});
