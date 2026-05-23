/**
 * MarketPhase — Centralized Ad Manager
 * ─────────────────────────────────────
 * HOW TO UPDATE SLOT IDs:
 *   1. Log in to AdSense → Ads → By ad unit
 *   2. Create (or copy) your ad units and paste their slot IDs below
 *   3. That's it — every page on the site updates automatically
 *
 * Ad types supported (use via <div class="mp-ad" data-ad-type="..."></div>):
 *   banner      — full-width responsive (top of page, between sections)
 *   mid         — full-width responsive (mid-content, identical to banner)
 *   sidebar     — fixed 300×250 rectangle
 *   leaderboard — fixed 728×90 (homepage top only)
 *   feed        — full-width responsive with bottom margin (daily digest)
 */

const MP_ADS = {
  PUB: 'ca-pub-5264064065432511',

  // ── Slot IDs ── Replace XXXXXXXXXX with real IDs from AdSense dashboard ──
  SLOTS: {
    banner:      '7841682790',   // Full-width responsive (guides, top/mid)
    mid:         '7841682790',   // Full-width responsive (mid-content)
    sidebar:     '7841682790',   // 300×250 rectangle — replace with a dedicated rectangle slot if you create one
    leaderboard: '7841682790',   // 728×90 leaderboard (homepage) — replace with a dedicated leaderboard slot if you create one
    feed:        '7841682790',   // Daily digest in-content
  },

  // ── Ad unit specs per type ────────────────────────────────────────────────
  SPECS: {
    banner: {
      style: 'display:block',
      extra: { 'data-ad-format': 'auto', 'data-full-width-responsive': 'true' },
    },
    mid: {
      style: 'display:block',
      extra: { 'data-ad-format': 'auto', 'data-full-width-responsive': 'true' },
    },
    sidebar: {
      style: 'display:inline-block;width:300px;height:250px',
      extra: {},
    },
    leaderboard: {
      style: 'display:inline-block;width:728px;height:90px',
      extra: {},
    },
    feed: {
      style: 'display:block;margin-bottom:2rem',
      extra: { 'data-ad-format': 'auto', 'data-full-width-responsive': 'true' },
    },
  },
};

(function () {
  function injectAds() {
    var markers = document.querySelectorAll('.mp-ad[data-ad-type]');
    if (!markers.length) return;

    markers.forEach(function (marker) {
      var type = marker.getAttribute('data-ad-type');
      var slot = MP_ADS.SLOTS[type];
      var spec = MP_ADS.SPECS[type];
      if (!slot || !spec) return;

      // Build <ins> element
      var ins = document.createElement('ins');
      ins.className = 'adsbygoogle';
      ins.style.cssText = spec.style;
      ins.setAttribute('data-ad-client', MP_ADS.PUB);
      ins.setAttribute('data-ad-slot', slot);
      Object.keys(spec.extra).forEach(function (attr) {
        ins.setAttribute(attr, spec.extra[attr]);
      });

      marker.replaceWith(ins);

      // Push to AdSense queue
      try {
        (window.adsbygoogle = window.adsbygoogle || []).push({});
      } catch (e) {}
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectAds);
  } else {
    injectAds();
  }
})();
