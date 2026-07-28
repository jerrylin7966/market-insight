/**
 * Cloudflare Pages Function — Contact Form
 * POST /api/contact
 *
 * Env var required (set in Cloudflare Pages → Settings → Environment Variables):
 *   RESEND_API_KEY  — your Resend API key (re_xxxxxxxx)
 *
 * Resend domain: verify market-phase.com in your Resend dashboard so you can
 * send from contact@market-phase.com. Until verified, Resend will only deliver
 * to the email address tied to your account (safe for testing).
 */

export async function onRequestPost(ctx) {
  const CORS = {
    'Access-Control-Allow-Origin': 'https://www.market-phase.com',
    'Content-Type': 'application/json',
  };

  try {
    const body = await ctx.request.json();
    const { name, email, topic, message } = body;

    if (!name || !email || !message) {
      return new Response(JSON.stringify({ success: false, error: 'Missing fields' }), { status: 400, headers: CORS });
    }

    const resendKey = ctx.env.RESEND_API_KEY;
    if (!resendKey) {
      return new Response(JSON.stringify({ success: false, error: 'Server not configured' }), { status: 500, headers: CORS });
    }

    const html = `
      <div style="font-family:sans-serif;max-width:600px">
        <h2 style="color:#1d4ed8">New MarketPhase Contact</h2>
        <table style="border-collapse:collapse;width:100%">
          <tr><td style="padding:8px;font-weight:600;width:100px">Name</td><td style="padding:8px">${escHtml(name)}</td></tr>
          <tr style="background:#f8fafc"><td style="padding:8px;font-weight:600">Email</td><td style="padding:8px"><a href="mailto:${escHtml(email)}">${escHtml(email)}</a></td></tr>
          <tr><td style="padding:8px;font-weight:600">Topic</td><td style="padding:8px">${escHtml(topic || 'Not specified')}</td></tr>
        </table>
        <div style="margin-top:1rem;padding:1rem;background:#f8fafc;border-left:4px solid #1d4ed8;white-space:pre-wrap">${escHtml(message)}</div>
      </div>
    `;

    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${resendKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: 'MarketPhase Contact <contact@market-phase.com>',
        to: ['jerrylin7966@gmail.com'],
        reply_to: email,
        subject: `MarketPhase — ${topic || 'Contact Form'}`,
        html,
      }),
    });

    if (!res.ok) {
      const err = await res.text();
      console.error('Resend error:', err);
      return new Response(JSON.stringify({ success: false, error: 'Send failed' }), { status: 500, headers: CORS });
    }

    return new Response(JSON.stringify({ success: true }), { headers: CORS });

  } catch (e) {
    console.error('Contact function error:', e);
    return new Response(JSON.stringify({ success: false, error: 'Server error' }), { status: 500, headers: CORS });
  }
}

// Handle preflight
export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': 'https://www.market-phase.com',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
