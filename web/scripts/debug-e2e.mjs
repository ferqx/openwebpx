import { spawn } from 'child_process';

const devServer = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1'], {
  stdio: 'inherit',
  shell: true
});

devServer.on('error', (err) => {
  console.error('Failed to start dev server:', err);
});

// Wait for server to be likely ready, then start playwright UI
setTimeout(() => {
  console.log('Starting Playwright UI...');
  spawn('npx', ['playwright', 'test', '--ui'], {
    stdio: 'inherit',
    shell: true,
    env: { ...process.env, HTTP_PROXY: '', HTTPS_PROXY: '', all_proxy: '' }
  });
}, 5000);

process.on('SIGINT', () => {
  devServer.kill();
  process.exit();
});
