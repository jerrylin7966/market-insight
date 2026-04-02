import { fetchTrading212 } from './trading212';
import { fetchKraken }     from './kraken';
import { fetchBinance, fetchCoinbase, fetchPhantom, fetchRevolutBalance, fetchRevolutStocks, fetchRevolutCrypto, fetchTiger, fetchChinaBank, fetchCtbcBalance, fetchCtbcStocks, fetchDbs, fetchTiktokRsu, fetchMetaRsu } from './manual';
import { upsertSnapshot, getManualBalance } from '../db';
import { warmRates }       from '../fx';
import type { FetchResult } from '../types';

export interface RunResult {
  results:      FetchResult[];
  successCount: number;
  failCount:    number;
  totalUsd:     number;
  runAt:        string;
}

export async function runAllFetchers(): Promise<RunResult> {
  const runAt = new Date().toISOString();
  const today = runAt.slice(0, 10);

  console.log(`\n${'='.repeat(50)}`);
  console.log(`ASSET HUB — Daily fetch: ${runAt}`);
  console.log('='.repeat(50));

  await warmRates();

  const results = await Promise.all([
    safe(fetchTrading212),
    safe(fetchKraken),
    safe(fetchBinance),
    safe(fetchCoinbase),
    safe(fetchPhantom),
    safe(fetchRevolutBalance),
    safe(fetchRevolutStocks),
    safe(fetchRevolutCrypto),
    safe(fetchTiger),
    safe(fetchChinaBank),
    safe(fetchCtbcBalance),
    safe(fetchCtbcStocks),
    safe(fetchDbs),
    safe(fetchTiktokRsu),
    safe(fetchMetaRsu),
  ]);

  const MANUAL_PLATFORMS = new Set(['binance','coinbase','phantom','revolut_balance','revolut_stocks','revolut_crypto','tiger','china_bank','ctbc_balance','ctbc_stocks','dbs','tiktok_rsu','meta_rsu']);

  for (const r of results) {
    if (MANUAL_PLATFORMS.has(r.platform) && r.balanceNative === 0 && !getManualBalance(r.platform)) continue;
    upsertSnapshot({
      date:          today,
      platform:      r.platform,
      balanceNative: r.balanceNative,
      currency:      r.currency,
      balanceUsd:    r.balanceUsd,
      fxRate:        r.fxRate,
      createdAt:     r.fetchedAt,
    });
  }

  const successCount = results.filter(r => !r.error).length;
  const failCount    = results.filter(r => !!r.error).length;
  const totalUsd     = results.reduce((sum, r) => sum + r.balanceUsd, 0);

  console.log(`\nDone: ${successCount} ok, ${failCount} failed`);
  console.log(`Total: $${totalUsd.toLocaleString('en-US', { minimumFractionDigits: 2 })}`);
  console.log('='.repeat(50) + '\n');

  return { results, successCount, failCount, totalUsd, runAt };
}

async function safe(fn: () => Promise<FetchResult>): Promise<FetchResult> {
  try {
    return await fn();
  } catch (err: any) {
    console.error(`[Fetcher crash] ${fn.name}: ${err?.message}`);
    return { platform: 'dbs', balanceNative: 0, currency: 'USD', balanceUsd: 0, fxRate: 1, fetchedAt: new Date().toISOString(), error: err?.message };
  }
}
