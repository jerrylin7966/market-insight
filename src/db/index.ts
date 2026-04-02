import Database from 'better-sqlite3';
import path from 'path';
import type { DailySnapshot, PlatformId } from '../types';

const DB_PATH = path.join(process.cwd(), 'asset-hub.db');
let _db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (!_db) {
    _db = new Database(DB_PATH);
    _db.pragma('journal_mode = WAL');
    _db.pragma('foreign_keys = ON');
    initSchema(_db);
  }
  return _db;
}

function initSchema(db: Database.Database): void {
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
}

export function upsertSnapshot(snap: Omit<DailySnapshot, 'id'>): void {
  const db = getDb();
  db.prepare(`
    INSERT INTO snapshots (date, platform, balance_native, currency, balance_usd, fx_rate, created_at)
    VALUES (@date, @platform, @balanceNative, @currency, @balanceUsd, @fxRate, @createdAt)
    ON CONFLICT(date, platform) DO UPDATE SET
      balance_native = excluded.balance_native,
      balance_usd    = excluded.balance_usd,
      fx_rate        = excluded.fx_rate,
      created_at     = excluded.created_at
  `).run(snap);
}

export function getLatestSnapshots(): any[] {
  const db = getDb();
  return db.prepare(`
    SELECT s.* FROM snapshots s
    INNER JOIN (
      SELECT platform, MAX(date) AS max_date
      FROM snapshots GROUP BY platform
    ) latest ON s.platform = latest.platform AND s.date = latest.max_date
    ORDER BY s.platform
  `).all();
}

export function getSnapshotHistory(days: number = 90): any[] {
  const db = getDb();
  return db.prepare(`
    SELECT date, SUM(balance_usd) AS total_usd
    FROM snapshots
    WHERE date >= date('now', '-' || ? || ' days')
    GROUP BY date ORDER BY date ASC
  `).all(days);
}

export function upsertManualBalance(platform: PlatformId, balanceNative: number): void {
  const db = getDb();
  db.prepare(`
    INSERT INTO manual_balances (platform, balance_native, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(platform) DO UPDATE SET
      balance_native = excluded.balance_native,
      updated_at     = excluded.updated_at
  `).run(platform, balanceNative, new Date().toISOString());
}

export function getManualBalance(platform: PlatformId): { balanceNative: number; updatedAt: string } | null {
  const db = getDb();
  const row = db.prepare(
    `SELECT balance_native, updated_at FROM manual_balances WHERE platform = ?`
  ).get(platform) as any;
  if (!row) return null;
  return { balanceNative: row.balance_native, updatedAt: row.updated_at };
}

export function setMarketCache(key: string, data: any): void {
  const db = getDb();
  db.prepare(`
    INSERT INTO market_cache (key, data, cached_at)
    VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET
      data      = excluded.data,
      cached_at = excluded.cached_at
  `).run(key, JSON.stringify(data), new Date().toISOString());
}

export function getMarketCache(key: string, maxAgeHours: number = 26): any | null {
  const db = getDb();
  const row = db.prepare(
    `SELECT data, cached_at FROM market_cache WHERE key = ?`
  ).get(key) as { data: string; cached_at: string } | undefined;
  if (!row) return null;
  const ageHours = (Date.now() - new Date(row.cached_at).getTime()) / (1000 * 60 * 60);
  if (ageHours > maxAgeHours) return null;
  return JSON.parse(row.data);
}

export function saveOAuthToken(platform: string, accessToken: string, refreshToken: string | null, expiresAt: Date): void {
  const db = getDb();
  db.prepare(`
    INSERT INTO oauth_tokens (platform, access_token, refresh_token, expires_at, updated_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(platform) DO UPDATE SET
      access_token  = excluded.access_token,
      refresh_token = excluded.refresh_token,
      expires_at    = excluded.expires_at,
      updated_at    = excluded.updated_at
  `).run(platform, accessToken, refreshToken, expiresAt.toISOString(), new Date().toISOString());
}

export function getOAuthToken(platform: string): { accessToken: string; refreshToken: string | null; expiresAt: Date } | null {
  const db = getDb();
  const row = db.prepare(
    `SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE platform = ?`
  ).get(platform) as any;
  if (!row) return null;
  return { accessToken: row.access_token, refreshToken: row.refresh_token, expiresAt: new Date(row.expires_at) };
}
