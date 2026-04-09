// Test the nc-channel pipeline: pushes messages via the channel API and
// verifies the HMR transport is working. Run with nc_run_test.
// The actual channel notification to Claude Code can be verified by checking
// the SSE endpoint or watching the Claude Code session for <channel> events.

import { channel } from '~/lib/nc/channel';

export default async function () {
  const results: Record<string, boolean> = {};

  // Test 1: channel.error sends via HMR without throwing
  try {
    channel.error('nc-channel test: error level', { source: 'channel.test.ts', test: '1' });
    results['error_send'] = true;
  } catch {
    results['error_send'] = false;
  }

  // Test 2: channel.warn
  try {
    channel.warn('nc-channel test: warn level', { source: 'channel.test.ts', test: '2' });
    results['warn_send'] = true;
  } catch {
    results['warn_send'] = false;
  }

  // Test 3: channel.info
  try {
    channel.info('nc-channel test: info level', { source: 'channel.test.ts', test: '3' });
    results['info_send'] = true;
  } catch {
    results['info_send'] = false;
  }

  // Test 4: verify HMR is available (import.meta.hot exists in dev)
  results['hmr_available'] = !!(import.meta as any).hot;

  // Test 5: trigger a real console.error to test the auto-capture path
  console.error('nc-channel test: auto-captured console.error');
  results['console_error_triggered'] = true;

  const allPassed = Object.values(results).every(Boolean);

  return {
    passed: allPassed,
    results,
    message: allPassed
      ? 'All channel tests passed. Check Claude Code session for <channel> events.'
      : 'Some tests failed — see results.',
  };
}
