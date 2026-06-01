/**
 * MarketPhase — Universal Mobile Nav
 * Injects hamburger button + full-screen overlay menu on every page.
 * Works by reading the existing .nav-links / .site-nav-links content —
 * no HTML changes needed on individual pages.
 */
(function () {
  // ── Inject CSS ────────────────────────────────────────────────────────────
  var style = document.createElement('style');
  style.textContent = `
    /* Hamburger button — hidden on desktop */
    .mob-burger {
      display: none;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      gap: 5px;
      width: 40px;
      height: 40px;
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.18);
      border-radius: 8px;
      cursor: pointer;
      padding: 0;
      flex-shrink: 0;
      transition: background 0.15s;
      z-index: 1001;
    }
    .mob-burger:hover { background: rgba(255,255,255,0.14); }
    .mob-burger span {
      display: block;
      width: 20px;
      height: 2px;
      background: rgba(255,255,255,0.85);
      border-radius: 2px;
      transition: transform 0.25s, opacity 0.2s;
      transform-origin: center;
    }
    .mob-burger.open span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
    .mob-burger.open span:nth-child(2) { opacity: 0; transform: scaleX(0); }
    .mob-burger.open span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }

    /* Full-screen overlay menu */
    .mob-menu {
      display: none;
      position: fixed;
      inset: 0;
      top: 60px;
      background: #0f172a;
      z-index: 1000;
      flex-direction: column;
      padding: 1.5rem;
      overflow-y: auto;
      border-top: 1px solid rgba(255,255,255,0.08);
    }
    .mob-menu.open { display: flex; }

    /* Links inside overlay */
    .mob-menu a {
      display: block;
      color: rgba(255,255,255,0.85);
      font-size: 18px;
      font-weight: 500;
      text-decoration: none;
      padding: 14px 0;
      border-bottom: 1px solid rgba(255,255,255,0.07);
      transition: color 0.15s;
      font-family: inherit;
    }
    .mob-menu a:last-child { border-bottom: none; }
    .mob-menu a:hover { color: #fff; text-decoration: none; }

    /* CTA link in mobile menu */
    .mob-menu a.nav-cta {
      display: inline-block;
      margin-top: 1.25rem;
      background: #1d4ed8;
      color: #fff !important;
      padding: 13px 24px;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 600;
      border-bottom: none;
      text-align: center;
      width: 100%;
    }
    .mob-menu a.nav-cta:hover { background: #2563eb; }

    /* Show burger + hide regular links on mobile */
    @media (max-width: 768px) {
      .mob-burger { display: flex; }
      .nav-links, .site-nav-links { display: none !important; }
    }
  `;
  document.head.appendChild(style);

  // ── Wait for DOM ──────────────────────────────────────────────────────────
  function init() {
    var nav = document.querySelector('.nav, .site-nav');
    if (!nav) return;

    var links = nav.querySelector('.nav-links, .site-nav-links');
    if (!links) return;

    // ── Create hamburger button ──────────────────────────────────────────
    var burger = document.createElement('button');
    burger.className = 'mob-burger';
    burger.setAttribute('aria-label', 'Open menu');
    burger.innerHTML = '<span></span><span></span><span></span>';
    nav.appendChild(burger);

    // ── Create overlay menu ──────────────────────────────────────────────
    var menu = document.createElement('nav');
    menu.className = 'mob-menu';
    menu.setAttribute('aria-label', 'Mobile navigation');

    // Clone all links from the desktop nav
    var cloned = links.cloneNode(true);
    Array.from(cloned.children).forEach(function (el) {
      menu.appendChild(el.cloneNode(true));
    });

    document.body.appendChild(menu);

    // ── Toggle ───────────────────────────────────────────────────────────
    function openMenu() {
      menu.classList.add('open');
      burger.classList.add('open');
      burger.setAttribute('aria-label', 'Close menu');
      document.body.style.overflow = 'hidden';
    }
    function closeMenu() {
      menu.classList.remove('open');
      burger.classList.remove('open');
      burger.setAttribute('aria-label', 'Open menu');
      document.body.style.overflow = '';
    }

    burger.addEventListener('click', function () {
      menu.classList.contains('open') ? closeMenu() : openMenu();
    });

    // Close on link tap
    menu.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') closeMenu();
    });

    // Close on Escape
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeMenu();
    });

    // Close if viewport widens past 768px (e.g. orientation change)
    window.addEventListener('resize', function () {
      if (window.innerWidth > 768) closeMenu();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
