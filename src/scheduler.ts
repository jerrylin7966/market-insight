import cron from 'node-cron';
import { runAllFetchers } from './fetchers';
import { sendWeeklyEmail } from './mailer';

export function startScheduler(): void {
  console.log('[Scheduler] Daily fetch scheduled at 07:00 SGT (23:00 UTC)');
  cron.schedule('0 23 * * *', async () => {
    console.log('[Scheduler] Starting daily fetch...');
    try {
      await runAllFetchers();
    } catch (err) {
      console.error('[Scheduler] Run failed:', err);
    }

    // Pre-cache all market data for the day
    console.log('[Scheduler] Pre-caching market data...');
    try {
      const base = `http://localhost:${process.env.PORT ?? 3000}`;
      const credentials = Buffer.from(`:${process.env.DASHBOARD_PASSWORD}`).toString('base64');
      const headers = { Authorization: `Basic ${credentials}` };
      const axios = (await import('axios')).default;

      await Promise.allSettled([
        axios.get(`${base}/api/market/ratio`,    { headers, timeout: 30000 }),
        axios.get(`${base}/api/market/vix`,      { headers, timeout: 30000 }),
        axios.get(`${base}/api/market/breadth`,  { headers, timeout: 30000 }),
        axios.get(`${base}/api/market/heatmap`,  { headers, timeout: 30000 }),
        axios.get(`${base}/api/market/claims`,   { headers, timeout: 30000 }),
        axios.get(`${base}/api/market/signals`,  { headers, timeout: 30000 }),
      ]);
      console.log('[Scheduler] Market data cached successfully');
    } catch (err) {
      console.error('[Scheduler] Market cache pre-fetch failed:', err);
    }
  }, { timezone: 'UTC' });

  console.log('[Scheduler] Weekly email scheduled at 08:00 SGT Monday (00:00 UTC Monday)');
  cron.schedule('0 0 * * 1', async () => {
    console.log('[Scheduler] Starting weekly email...');
    try {
      await sendWeeklyEmail();
    } catch (err) {
      console.error('[Scheduler] Weekly email failed:', err);
    }
  }, { timezone: 'UTC' });
}

if (require.main === module) {
  if (process.argv.includes('--run-now')) {
    require('dotenv').config();
    runAllFetchers().then(() => process.exit(0)).catch(err => {
      console.error(err);
      process.exit(1);
    });
  }
}
