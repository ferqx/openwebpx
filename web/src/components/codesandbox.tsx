import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Nodebox } from '@codesandbox/nodebox';

interface Files {
  [path: string]: string;
}

interface Props {
  files: Files;
  isStreaming: boolean;
}

const NodeboxPreview: React.FC<Props> = ({ files, isStreaming }) => {
  const nodeboxIframeRef = useRef<HTMLIFrameElement>(null);
  const nodeBoxRef = useRef<Nodebox | null>(null);
  const setupQueue = useRef<Promise<void>>(Promise.resolve());
  const [previewUrl, setPreviewUrl] = useState<string | undefined>(undefined);

  // 3. 执行安装和启动脚本
  const runSetup = useCallback(async (targetFiles: Files) => {
    if (!nodeBoxRef.current) return;

    try {
      // 检查是否有 package.json
      const hasPackageJson = Object.keys(targetFiles).some((p) =>
        p.includes('package.json')
      );

      if (hasPackageJson) {
        console.log(
          'Running setup: installing dependencies and starting dev server'
        );

        // 执行安装。注意：Nodebox 内部会有缓存优化
        const installProcess = nodeBoxRef.current.shell.create();
        installProcess.on('progress', (status) => {
          console.log('Install Progress:', status);
        });
        await installProcess.runCommand('npm', ['install']);

        const devProcess = nodeBoxRef.current.shell.create();

        devProcess.on('progress', (status) => {
          console.log('Dev Progress:', status);
        });

        const dev = await devProcess.runCommand('npm', ['dev']);

        // 执行启动命令
        const previewInfo = await nodeBoxRef.current.preview.getByShellId(
          dev.id,
          3000
        );
        setPreviewUrl(previewInfo.url);
      }
    } catch (err) {
      console.error('Execution Error:', err);
    }
  }, []);

  // 2. 同步文件到虚拟文件系统
  const syncFiles = useCallback(
    async (newFiles: Files) => {
      if (!nodeBoxRef.current) return;

      const fs = nodeBoxRef.current.fs;

      console.log('Syncing files to Nodebox:', newFiles);

      await fs.init(newFiles);

      await runSetup(newFiles);
    },
    [runSetup]
  );

  // 1. 初始化 Nodebox 实例
  useEffect(() => {
    const initNodeBox = async () => {
      try {
        const nodeBox = new Nodebox({
          iframe: nodeboxIframeRef.current!
        });

        nodeBoxRef.current = nodeBox;

        await nodeBoxRef.current.connect();
      } catch (err) {
        console.error('Nodebox Init Error:', err);
      }
    };

    if (!nodeBoxRef.current) {
      setupQueue.current = initNodeBox();
    }

    if (nodeBoxRef.current && !isStreaming) {
      setupQueue.current = setupQueue.current
        .then(async () => {
          await syncFiles(files);
        })
        .catch((err) => {
          console.error('Setup Queue Error:', err);
        });
    }
  }, [files, isStreaming, syncFiles]);

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        border: '1px solid #ddd'
      }}
    >
      {/* 预览窗口 */}
      <div style={{ flex: 1, position: 'relative', background: '#fff' }}>
        <iframe
          id="preview-iframe"
          src={previewUrl}
          style={{ width: '100%', height: '100%', border: 'none' }}
          title="AI App Preview"
          allow="accelerometer; camera; encrypted-media; geolocation; gyroscope; hid; microphone; midi; clipboard-read; clipboard-write; report-sample; speaker-selection; usb; wireless-innovations; attribution-reporting; display-capture; publickey-credentials-get; storage-access"
        />
        <iframe
          id="nodebox-iframe"
          ref={nodeboxIframeRef}
          style={{ display: 'none' }}
        ></iframe>
      </div>
    </div>
  );
};

export default NodeboxPreview;
