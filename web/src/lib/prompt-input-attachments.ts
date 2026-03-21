const SUPPORTED_ATTACHMENT_EXTENSIONS = [
  '.txt',
  '.md',
  '.mdx',
  '.json',
  '.jsonl',
  '.yaml',
  '.yml',
  '.toml',
  '.ini',
  '.cfg',
  '.conf',
  '.csv',
  '.tsv',
  '.log',
  '.xml',
  '.html',
  '.css',
  '.scss',
  '.less',
  '.svg',
  '.js',
  '.jsx',
  '.mjs',
  '.cjs',
  '.ts',
  '.tsx',
  '.py',
  '.rb',
  '.php',
  '.java',
  '.kt',
  '.kts',
  '.go',
  '.rs',
  '.swift',
  '.scala',
  '.sh',
  '.bash',
  '.zsh',
  '.fish',
  '.ps1',
  '.sql',
  '.c',
  '.cc',
  '.cpp',
  '.cxx',
  '.h',
  '.hpp',
  '.cs',
  '.vue',
  '.svelte',
  '.astro',
  '.dockerfile'
] as const;

export const SUPPORTED_PROMPT_ATTACHMENT_ACCEPT =
  SUPPORTED_ATTACHMENT_EXTENSIONS.join(',');

export const SUPPORTED_PROMPT_ATTACHMENT_HINT =
  '支持 txt、md、json、yaml、csv 以及常见代码文件，暂不支持图片、视频、压缩包和其他二进制文件。';

export const getPromptAttachmentErrorMessage = (error: {
  code: 'max_files' | 'max_file_size' | 'accept';
  message: string;
}) => {
  switch (error.code) {
    case 'accept':
      return `仅支持文本、配置、表格和常见代码文件。${SUPPORTED_PROMPT_ATTACHMENT_HINT}`;
    case 'max_file_size':
      return '文件过大，无法添加。请缩小后重试。';
    case 'max_files':
      return '添加的文件数量超出限制，部分文件未加入。';
    default:
      return error.message;
  }
};
