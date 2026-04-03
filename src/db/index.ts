import { Pool } from 'pg';
import type { DailySnapshot, PlatformId } from '../types';

let _pool: Pool | null = null;

export function getPool(): Pool {
  if (!_pool) {
    _pool = new Pool({ connectionString: process.env.DATABASE_URL, ssl: { rejectUnauthorized: false } });
  }
  return _pool;
}

export async function initSchema(): Promise<void> {
  const pool = getPool();
  await pool.query(`
    CREATE TABLE IF NOT EXISTS snapshots (
      id             SERIAL PRIMARY KEY,
      date           TEXT NOT NULL,
      platform       TEXT NOT NULL,
      balance_native REAL NOT NULL DEFAULT 0,
      currency       TEXT NOT NULL,
      balance_usd    REAL NOT NULL DEFAULT 0,
      fx_rate        REAL NOT NULL DEFAULT 1,
      created_at     TEXT NOT NULL,
      UNIQUE(date, platform)
    );
    CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(date);
    CREATE TABLE IF NOT EXISTS manual_balances (
      platform       TEXT PRIMARY KEY,
      balance_native REAL NOT NULL DEFAULT 0,
      updated_at     TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS oauth_tokens (
      platform      TEXT PRIMARY KEY,
      access_token  TEXT NOT NULL,
      refresh_token TEXT,
      expires_at    TEXT NOT NULL,
      updated_at    TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS market_cache (
      key        TEXT PRIMARY KEY,
      data       TEXT NOT NULL,
      cached_at  TEXT NOT NULL
    );
  `);
  console.log('[DB] Schema initialised on PostgreSQL');
}

export async function upsertSnapshot(snap: Omit<DailySnapshot, 'id'>): Promise<void> {
  const pool = getPool();
  await pool.query(`
    INSERT INTO snapshots (date, platform, balance_native, currency, balance_usd, fx_rate, created_at)
    VALUES ($1,$2,$3,$4,$5,$6,$7)
    ON CONFLICT(date, platform) DO UPDATE SET
      balance_native = EXCLUDED.balance_native,
      balance_usd    = EXCLUDED.balance_usd,
      fx_rate        = EXCLUDED.fx_rate,
      created_at     = EXCLUDED.created_at
  `, [snap.date, snap.platform, snap.balanceNative, snap.currency, snap.balanceUsd, snap.fxRate, snap.createdAt]);
}

export async function getLatestSnapshots(): Promise<any[]> {
  const pool = getPool();
  const res = await pool.query(`
    SELECT s.* FROM snapshots s
    INNER JOIN (
      SELECT platform, MAX(date) AS max_date FROM snapshots GROUP BY platform
    ) latest ON s.platform = latest.platform AND s.date = latest.max_date
    ORDER BY s.platform
  `);
  return res.rows;
}

export async function getSnapshotHistory(days: number = 90): Promise<any[]> {
  const pool = getPool();
  const res = await pool.query(`
    SELECT date, SUM(balance_usd) AS total_usd
    FROM snapshots
    WHERE date >= (CURRENT_DATE - $1 * INTERVAL '1 day')::TEXT
    GROUP BY date ORDER BY date ASC
  `, [days]);
  return res.rows;
}

export async function upsertManualBalance(platform: PlatformId, balanceNative: number): Promise<void> {
  const pool = getPool();
  await pool.query(`
    INSERT INTO manual_balances (platform, balance_native, updated_at)
    VALUES ($1,$2,$3)
    ON CONFLICT(platform) DO UPDATE SET
      balance_native = EXCLUDED.balance_native,
      updated_at     = EXCLUDED.updated_at
  `, [platform, balanceNative, new Date().toISOString()]);
}

export async function getManualBalance(platform: PlatformId): Promise<{ balanceNative: number; updatedAt: string } | null> {
  const pool = getPool();
  const res = await pool.query(
    `SELECT balance_native, updated_at FROM manual_balances WHERE platform = $1`, [platform]
  );
  if (!res.rows[0]) return null;
  return { balanceNative: res.rows[0].balance_native, updatedAt: res.rows[0].updated_at };
}

export async function saveOAuthToken(platform: string, accessToken: string, refreshToken: string | null, expiresAt: Date): Promise<void> {
  const pool = getPool();
  await pool.query(`
    INSERT INTO oauth_tokens (platform, access_token, refresh_token, expires_at, updated_at)
    VALUES ($1,$2,$3,$4,$5)
    ON CONFLICT(platform) DO UPDATE SET
      access_token  = EXCLUDED.access_token,
      refresh_token = EXCLUDED.refresh_token,
      expires_at    = EXCLUDED.expires_at,
      updated_at    = EXCLUDED.updated_at
  `, [platform, accessToken, refreshToken, expiresAt.toISOString(), new Date().toISOString()]);
}

export async function getOAuthToken(platform: string): Promise<{ accessToken: string; refreshToken: string | null; expiresAt: Date } | null> {
  const pool = getPool();
  const res = await pool.query(
    `SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE platform = $1`, [platform]
  );
  if (!res.rows[0]) return null;
  return { accessToken: res.rows[0].access_token, refreshToken: res.rows[0].refresh_token, expiresAt: new Date(res.rows[0].expires_at) };
}

export async function setMarketCache(key: string, data: any): Promise<void> {
  const pool = getPool();
  await pool.query(`
    INSERT INTO market_cache (key, data, cached_at)
    VALUES ($1,$2,$3)
    ON CONFLICT(key) DO UPDATE SET
      data      = EXCLUDED.data,
      cached_at = EXCLUDED.cached_at
  `, [key, JSON.stringify(data), new Date().toISOString()]);
}

export async function getMarketCache(key: string, maxAgeHours: number = 26): Promise<any | null> {
  const pool = getPool();
  const res = await pool.query(
    `SELECT data, cached_at FROM market_cache WHERE key = $1`, [key]
  );
  if (!res.rows[0]) return null;
  const ageHours = (Date.now() - new Date(res.rows[0].cached_at).getTime()) / (1000 * 60 * 60);
  if (ageHours > maxAgeHours) return null;
  return JSON.parse(res.rows[0].data);
}
