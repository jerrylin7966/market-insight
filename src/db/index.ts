import 'dotenv/config';
import Database from 'better-sqlite3';
import path from 'path';
import type { DailySnapshot, PlatformId } from '../types';

// ── DB file lives in the project root ────────────────────────────────────────
const DB_PATH = path.join(process.cwd(), 'asset-hub.db');
let _db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (!_db) {
    _db = new Database(DB_PATH);
    _db.pragma('journal_mode = WAL');
    _db.pragma('foreign_keys = ON');
  }
  return _db;
}

// ── Schema ────────────────────────────────────────────────────────────────────
export async function initSchema(): Promise<void> {
  const db = getDb();
  db.exec(`
    CREATE TABLE IF NOT EXISTS snapshots (
      id             INTEGER PRIMARY KEY AUTOINCREMENT,
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
  console.log('[DB] Schema initialised — SQLite at', DB_PATH);
}

// ── Snapshots ─────────────────────────────────────────────────────────────────
export async function upsertSnapshot(snap: Omit<DailySnapshot, 'id'>): Promise<void> {
  const db = getDb();
  db.prepare(`
    INSERT INTO snapshots (date, platform, balance_native, currency, balance_usd, fx_rate, created_at)
    VALUES (@date, @platform, @balanceNative, @currency, @balanceUsd, @fxRate, @createdAt)
    ON CONFLICT(date, platform) DO UPDATE SET
      balance_native = excluded.balance_native,
      balance_usd    = excluded.balance_usd,
      fx_rate        = excluded.fx_rate,
      created_at     = excluded.created_at
  `).run({
    date:          snap.date,
    platform:      snap.platform,
    balanceNative: snap.balanceNative,
    currency:      snap.currency,
    balanceUsd:    snap.balanceUsd,
    fxRate:        snap.fxRate,
    createdAt:     snap.createdAt,
  });
}

export async function getLatestSnapshots(): Promise<any[]> {
  const db = getDb();
  return db.prepare(`
    SELECT s.* FROM snapshots s
    INNER JOIN (
      SELECT platform, MAX(date) AS max_date FROM snapshots GROUP BY platform
    ) latest ON s.platform = latest.platform AND s.date = latest.max_date
    ORDER BY s.platform
  `).all() as any[];
}

export async function getSnapshotHistory(days: number = 90): Promise<any[]> {
  const db = getDb();
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  return db.prepare(`
    SELECT date, SUM(balance_usd) AS total_usd
    FROM snapshots
    WHERE date >= ?
    GROUP BY date
    ORDER BY date ASC
  `).all(cutoffStr) as any[];
}

// ── Manual balances ───────────────────────────────────────────────────────────
export async function upsertManualBalance(platform: PlatformId, balanceNative: number): Promise<void> {
  const db = getDb();
  db.prepare(`
    INSERT INTO manual_balances (platform, balance_native, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(platform) DO UPDATE SET
      balance_native = excluded.balance_native,
      updated_at     = excluded.updated_at
  `).run(platform, balanceNative, new Date().toISOString());
}

export async function getManualBalance(platform: PlatformId): Promise<number | null> {
  const db = getDb();
  const row = db.prepare(`SELECT balance_native FROM manual_balances WHERE platform = ?`).get(platform) as any;
  return row ? row.balance_native : null;
}

// ── OAuth tokens ──────────────────────────────────────────────────────────────
export async function getOAuthToken(platform: string): Promise<any | null> {
  const db = getDb();
  return db.prepare(`SELECT * FROM oauth_tokens WHERE platform = ?`).get(platform) || null;
}

export async function setOAuthToken(platform: string, token: {
  access_token: string;
  refresh_token?: string;
  expires_at: string;
}): Promise<void> {
  const db = getDb();
  db.prepare(`
    INSERT INTO oauth_tokens (platform, access_token, refresh_token, expires_at, updated_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(platform) DO UPDATE SET
      access_token  = excluded.access_token,
      refresh_token = excluded.refresh_token,
      expires_at    = excluded.expires_at,
      updated_at    = excluded.updated_at
  `).run(platform, token.access_token, token.refresh_token ?? null, token.expires_at, new Date().toISOString());
}

// ── Market cache (6-hour TTL) ─────────────────────────────────────────────────
const CACHE_TTL_HOURS = 6;

export async function getMarketCache(key: string): Promise<any | null> {
  const db = getDb();
  const row = db.prepare(`SELECT data, cached_at FROM market_cache WHERE key = ?`).get(key) as any;
  if (!row) return null;
  const ageHours = (Date.now() - new Date(row.cached_at).getTime()) / 3_600_000;
  if (ageHours > CACHE_TTL_HOURS) {
    db.prepare(`DELETE FROM market_cache WHERE key = ?`).run(key);
    return null;
  }
  try { return JSON.parse(row.data); } catch { return null; }
}

export async function setMarketCache(key: string, data: any): Promise<void> {
  const db = getDb();
  db.prepare(`
    INSERT INTO market_cache (key, data, cached_at)
    VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET
      data      = excluded.data,
      cached_at = excluded.cached_at
  `).run(key, JSON.stringify(data), new Date().toISOString());
}
