# TIKTOKEN_CACHE_DIR 离线缓存说明

本项目在构建仓库上下文时会使用 `tiktoken` 进行 token 计数。`tiktoken` 首次加载编码
`o200k_base` 时会下载编码文件并写入本地缓存。对于离线环境，可以通过
`TIKTOKEN_CACHE_DIR` 指定缓存目录，避免运行时访问公网。

## 适用场景
- 依赖包在外网下载后导入内网构建
- 运行环境不允许访问公网
- 需要离线启动但仍保持较准确的 token 计数

## 准备缓存（外网环境）
使用脚本预热并打包缓存：

```bash
./scripts/prepare_offline_bundle.sh
```

脚本会在 `offline_bundle/tiktoken-cache/` 下生成缓存内容。

## 离线环境使用
将缓存目录带入内网后，设置环境变量：

```bash
export TIKTOKEN_CACHE_DIR="/path/to/offline_bundle/tiktoken-cache"
```

应用启动时会直接读取该目录，不再尝试联网下载编码文件。

## 常见问题
- 如果仍然出现下载错误，确认 `TIKTOKEN_CACHE_DIR` 指向的是缓存目录本身，
  且该目录下包含 `o200k_base` 编码文件。
- 若你希望完全跳过 `tiktoken`，可以设置
  `OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_DISABLE_TIKTOKEN=1`，使用启发式计数。
