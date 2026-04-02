import puppeteer from 'puppeteer';
import { Resend } from 'resend';
import { getLatestSnapshots, getSnapshotHistory } from './db';
import { PLATFORMS } from './types';

const resend = new Resend(process.env.RESEND_API_KEY);

const RECIPIENTS: string[] = (process.env.WEEKLY_EMAIL_RECIPIENTS ?? '')
  .split(',').map(e => e.trim()).filter(Boolean);

const FROM_EMAIL = process.env.FROM_EMAIL ?? 'weekly@yourdomain.com';

async function captureMarketScreenshot(): Promise<string | null> {
  try {
    const browser = await puppeteer.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });

    const baseUrl = `http://localhost:${process.env.PORT ?? 3000}`;
    await page.goto(baseUrl, { waitUntil: 'networkidle0', timeout: 30000 });

    // Set language preference before auth
    await page.evaluate(() => { localStorage.setItem('lang', 'zh'); });

    // Log in via the password form
    await page.type('#password-input', process.env.DASHBOARD_PASSWORD ?? '');
    await page.keyboard.press('Enter');

    // Wait for the app to become visible after successful login
    await page.waitForSelector('#app.ready', { timeout: 15000 });

    // Navigate to the market timing section
    await page.click('#btn-market');

    // Wait for at least the signals badge to appear (charts loaded)
    await page.waitForSelector('#auto-signal-badge:not(:empty)', { timeout: 20000 });

    // Extra pause for charts to finish rendering
    await new Promise(r => setTimeout(r, 3000));

    const screenshot = await page.screenshot({ encoding: 'base64', fullPage: false });
    await browser.close();
    return screenshot as string;
  } catch (err) {
    console.error('[Mailer] Screenshot failed:', err);
    return null;
  }
}

function buildEmailHtml(
  screenshot: string | null,
  totalUsd: number,
  weeklyChange: number,
  phase: string,
  phaseColor: string,
  snapshots: any[]
): string {
  const weekDate = new Date().toLocaleDateString('zh-TW', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });
  const changeSign = weeklyChange >= 0 ? '+' : '';
  const changeColor = weeklyChange >= 0 ? '#4eca8b' : '#e05c5c';
  const phaseColors: Record<string, string> = { green: '#4eca8b', yellow: '#e8a84a', red: '#e05c5c' };
  const phaseBadgeColor = phaseColors[phaseColor] ?? '#e8a84a';

  const platformRows = snapshots.map(s => {
    const meta = PLATFORMS[s.platform as keyof typeof PLATFORMS];
    if (!meta) return '';
    return `
      <tr>
        <td style="padding:8px 12px;border-bottom:1px solid #2a2e2a;font-size:13px;color:#e8ebe6">${meta.flag} ${meta.name}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #2a2e2a;font-size:13px;color:#e8ebe6;text-align:right">$${Math.round(s.balance_usd).toLocaleString('en-US')}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #2a2e2a;font-size:12px;color:#7a8278;text-align:right">${meta.currency} ${Math.round(s.balance_native).toLocaleString('en-US')}</td>
      </tr>`;
  }).join('');

  const screenshotSection = screenshot
    ? `<div style="margin:24px 0">
        <p style="font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:#7a8278;margin-bottom:12px">市場時機圖表</p>
        <img src="data:image/png;base64,${screenshot}" style="width:100%;border-radius:8px;border:1px solid #2a2e2a" />
      </div>`
    : `<p style="color:#7a8278;font-size:12px">圖表截圖本週不可用</p>`;

  return `
  <!DOCTYPE html>
  <html lang="zh-TW">
  <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
  <body style="margin:0;padding:0;background:#0d0f0e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
    <div style="max-width:640px;margin:0 auto;padding:32px 24px">

      <!-- Header -->
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:32px;padding-bottom:20px;border-bottom:1px solid #2a2e2a">
        <div style="font-family:monospace;font-size:14px;font-weight:500;color:#4eca8b;letter-spacing:0.08em">ASSET HUB</div>
        <div style="font-size:12px;color:#7a8278">${weekDate}</div>
      </div>

      <!-- Subject line -->
      <h1 style="font-size:20px;font-weight:400;color:#e8ebe6;margin:0 0 8px">每週資產報告</h1>
      <p style="font-size:13px;color:#7a8278;margin:0 0 32px">以下為本週資產概況與市場時機分析</p>

      <!-- Net worth -->
      <div style="background:#141714;border:1px solid #2a2e2a;border-radius:12px;padding:20px 24px;margin-bottom:16px">
        <p style="font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#7a8278;margin:0 0 8px">總資產淨值</p>
        <p style="font-family:monospace;font-size:36px;font-weight:300;color:#e8ebe6;margin:0 0 8px">USD ${Math.round(totalUsd).toLocaleString('en-US')}</p>
        <p style="font-family:monospace;font-size:14px;color:${changeColor};margin:0">${changeSign}$${Math.abs(Math.round(weeklyChange)).toLocaleString('en-US')} 較上週</p>
      </div>

      <!-- Market phase badge -->
      <div style="background:#141714;border:1px solid #2a2e2a;border-radius:12px;padding:16px 24px;margin-bottom:24px;display:flex;align-items:center;justify-content:space-between">
        <div>
          <p style="font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:#7a8278;margin:0 0 6px">市場時機訊號</p>
          <p style="font-size:13px;color:#e8ebe6;margin:0">基於5項指標自動計算</p>
        </div>
        <div style="background:${phaseBadgeColor}22;border:1px solid ${phaseBadgeColor};border-radius:20px;padding:6px 16px;font-family:monospace;font-size:12px;font-weight:500;color:${phaseBadgeColor}">${phase}</div>
      </div>

      <!-- Platform breakdown -->
      <div style="margin-bottom:24px">
        <p style="font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:#7a8278;margin-bottom:12px">各帳戶明細</p>
        <table style="width:100%;border-collapse:collapse;background:#141714;border-radius:12px;overflow:hidden;border:1px solid #2a2e2a">
          <thead>
            <tr style="background:#1b1e1b">
              <th style="padding:10px 12px;text-align:left;font-size:11px;color:#7a8278;font-weight:400">平台</th>
              <th style="padding:10px 12px;text-align:right;font-size:11px;color:#7a8278;font-weight:400">USD 價值</th>
              <th style="padding:10px 12px;text-align:right;font-size:11px;color:#7a8278;font-weight:400">原幣金額</th>
            </tr>
          </thead>
          <tbody>${platformRows}</tbody>
        </table>
      </div>

      <!-- Market screenshot -->
      ${screenshotSection}

      <!-- Footer -->
      <div style="border-top:1px solid #2a2e2a;padding-top:20px;margin-top:32px">
        <p style="font-size:11px;color:#7a8278;margin:0">此郵件由 Asset Hub 自動發送 · 每週一上午 8:00 SGT</p>
        <p style="font-size:11px;color:#7a8278;margin:4px 0 0">本報告僅供個人參考，不構成任何投資建議</p>
      </div>
    </div>
  </body>
  </html>`;
}

export async function sendWeeklyEmail(): Promise<void> {
  if (!process.env.RESEND_API_KEY) {
    console.log('[Mailer] RESEND_API_KEY not set — skipping weekly email');
    return;
  }
  if (RECIPIENTS.length === 0) {
    console.log('[Mailer] No recipients configured — skipping weekly email');
    return;
  }

  console.log('[Mailer] Starting weekly email generation...');

  // Get asset data
  const snapshots = getLatestSnapshots();
  const totalUsd = snapshots.reduce((sum, s) => sum + s.balance_usd, 0);

  // Calculate weekly change (compare latest day vs ~7 days prior)
  const history = getSnapshotHistory(14);
  const weeklyChange = history.length >= 2
    ? history[history.length - 1].total_usd - history[Math.max(0, history.length - 8)].total_usd
    : 0;

  // Get market phase from signals endpoint
  let phase = '市場訊號載入中';
  let phaseColor = 'yellow';
  try {
    const axios = (await import('axios')).default;
    const credentials = Buffer.from(`:${process.env.DASHBOARD_PASSWORD}`).toString('base64');
    const res = await axios.get(`http://localhost:${process.env.PORT ?? 3000}/api/market/signals`, {
      headers: { Authorization: `Basic ${credentials}` }, timeout: 15000,
    });
    const phaseMap: Record<string, string> = {
      green:  '🟢 第一階段 — 買入',
      yellow: '🟡 第二至三階段 — 觀察',
      red:    '🔴 第四階段 — 賣出',
    };
    phaseColor = res.data.color ?? 'yellow';
    phase = phaseMap[phaseColor] ?? '🟡 第二至三階段 — 觀察';
  } catch (err) {
    console.error('[Mailer] Could not fetch market signals:', err);
  }

  // Capture screenshot
  const screenshot = await captureMarketScreenshot();

  // Build and send email
  const html = buildEmailHtml(screenshot, totalUsd, weeklyChange, phase, phaseColor, snapshots);
  const weekStr = new Date().toLocaleDateString('zh-TW', { month: 'long', day: 'numeric' });

  try {
    await resend.emails.send({
      from: FROM_EMAIL,
      to: RECIPIENTS,
      subject: `📊 每週資產報告 ${weekStr} · ${phase}`,
      html,
    });
    console.log(`[Mailer] Weekly email sent to ${RECIPIENTS.length} recipient(s)`);
  } catch (err) {
    console.error('[Mailer] Failed to send email:', err);
  }
}
