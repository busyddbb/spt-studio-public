'use strict';
// Run the app's 读数据 script (native/MetricsReaderDOM.js) in offline macOS WebKit.
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const os = require('node:os');
if (process.platform !== 'darwin') {
  console.log('metrics reader DOM: skipped (requires macOS WebKit)');
} else {
  const root = path.resolve(__dirname, '..');
  const binary = path.join(os.tmpdir(), `spt-metrics-dom-${process.pid}`);
  for (const [command, args] of [
    ['xcrun', ['swiftc', '-framework', 'AppKit', '-framework', 'WebKit', path.join(__dirname, 'metrics_reader_dom_harness.swift'), '-o', binary]],
    [binary, []]
  ]) {
    const result = spawnSync(command, args, { cwd: root, encoding: 'utf8', timeout: 120000 });
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    if (result.error || result.status !== 0) {
      if (result.error) console.error(result.error.message);
      process.exit(result.status || 1);
    }
  }
}
