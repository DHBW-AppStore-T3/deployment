<!DOCTYPE html>
<html lang="${(currentLanguageTag!'de')}" class="login-pf">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>DHBW AppStore – Login</title>
  <link rel="icon" href="${url.resourcesPath}/img/favicon.png" type="image/png">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    @font-face {
      font-family: 'Inter';
      src: url('${url.resourcesPath}/img/InterVariable.woff2') format('woff2');
      font-weight: 100 900; font-style: normal; font-display: swap;
    }

    /* T3 auth palette — values from frontend/src/theme/themes/t3.ts */
    :root {
      --accent:       rgb(180 0 37);
      --accent-hover: rgb(148 0 30);
      --muted:        rgb(116 123 138);
      --surface:      rgb(250 250 250);
      --heading:      rgb(15 27 48);
      --label:        rgb(31 46 68);
      --input-border: rgb(228 233 239);
      --lang-border:  rgb(231 231 235);
      --lang-text:    rgb(100 107 120);
      --lang-sel:     rgb(247 224 229);
      --lang-hover:   rgb(244 233 236);
      --fold:         rgb(238 238 239);
      --card-bg:      rgb(255 255 255 / .878);
      --card-border:  rgb(255 255 255 / .251);
      --card-shadow:  rgb(23 32 43 / .051);
      --card-text:    rgb(57 67 75);
      --connector:    rgb(255 255 255 / .439);
      --line:         rgb(255 255 255 / .565);
      --status-ring:  rgb(216 82 106);
    }

    html, body { height: 100%; }
    body {
      font-family: 'Inter', ui-sans-serif, system-ui, sans-serif;
      background: var(--surface);
      color: var(--heading);
    }

    /* ── Page shell ─────────────────────────────────────────────
       --u mirrors React's --auth-unit: min(100vw/1672, 100svh/941)
       All sizes scale proportionally so the layout matches the
       frontend AuthLayout pixel-for-pixel at every viewport size.
    ─────────────────────────────────────────────────────────── */
    .page {
      --u: min(calc(100vw / 1672), calc(100svh / 941));
      position: relative;
      width: 100vw;
      height: 100svh;
      overflow: hidden;
    }

    .page-bg {
      position: absolute;
      inset: 0;
      background-image: url('${url.resourcesPath}/img/background.jpg');
      background-size: cover;
      background-position: left center;
      filter: saturate(.72) brightness(.97);
      z-index: 0;
    }

    .page-panel {
      position: absolute;
      inset: 0;
      width: 100%; height: 100%;
      z-index: 1;
      pointer-events: none;
    }
    .panel-surface   { fill: var(--surface); }
    .panel-fold-stop { stop-color: var(--fold); }

    /* ── Content column ── */
    .left {
      position: absolute;
      z-index: 2;
      top: 0; left: 0; bottom: 0;
      width: calc(370 * var(--u));
      margin-left: 6.95%;
    }

    /* ── Header (logo) ── */
    .hdr { padding-top: 9.7svh; }

    .brand {
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      gap: calc(7 * var(--u));
      color: var(--muted);
      font-size: calc(13 * var(--u));
    }

    .logo-mark {
      width: calc(80 * var(--u));
      aspect-ratio: 182 / 151;
      background: var(--accent);
      mask: url('${url.resourcesPath}/img/logo.png') center / contain no-repeat;
      -webkit-mask: url('${url.resourcesPath}/img/logo.png') center / contain no-repeat;
    }

    /* ── Language switcher ── */
    .lang-switcher {
      position: absolute;
      z-index: 3;
      top: 4.4%;
      left: 32.1%;
      display: flex;
      overflow: hidden;
      border: 1px solid var(--lang-border);
      border-radius: calc(9 * var(--u));
    }
    .lang-switcher button {
      padding: calc(6 * var(--u)) calc(12 * var(--u));
      font-family: inherit;
      font-size: calc(13 * var(--u));
      color: var(--lang-text);
      background: none;
      border: none;
      cursor: pointer;
      transition: background .15s;
      min-height: calc(32 * var(--u));
    }
    .lang-switcher button[aria-pressed='true'] { color: var(--accent); background: var(--lang-sel); }
    .lang-switcher button:hover               { background: var(--lang-hover); }

    /* ── Main content ── */
    .main {
      position: absolute;
      top: 27.3%;
      width: 100%;
    }

    .eyebrow {
      margin: 0 0 calc(18 * var(--u));
      font-size: calc(13 * var(--u));
      line-height: 1.3;
      letter-spacing: .23em;
      color: var(--accent);
    }

    .title {
      margin: 0 0 calc(12 * var(--u));
      font-size: calc(58 * var(--u));
      font-weight: 750;
      line-height: 1.03;
      letter-spacing: -.005em;
    }
    .title span        { display: block; }
    .title-accent      { color: var(--accent); }

    .description {
      margin: 0 0 calc(32 * var(--u));
      color: var(--muted);
      font-size: calc(17 * var(--u));
      line-height: 1.5;
    }

    /* ── Keycloak alert messages ── */
    .alert {
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: calc(16 * var(--u));
      font-size: calc(14 * var(--u));
      line-height: 1.4;
    }
    .alert-error   { background: #fde8e8; border: 1px solid #fbd5d5; color: #b91c1c; }
    .alert-warning { background: #fef3c7; border: 1px solid #fde68a; color: #b45309; }
    .alert-info    { background: #dbeafe; border: 1px solid #bfdbfe; color: #1d4ed8; }

    /* ── Form ── */
    .form-group { margin-bottom: calc(12 * var(--u)); }

    .form-row-between {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: calc(6 * var(--u));
    }

    label {
      display: block;
      font-size: calc(14 * var(--u));
      font-weight: 600;
      color: var(--label);
      margin-bottom: calc(6 * var(--u));
    }

    .forgot { font-size: calc(13 * var(--u)); color: var(--accent); font-weight: 500; text-decoration: none; }
    .forgot:hover { text-decoration: underline; }

    input[type="text"],
    input[type="email"],
    input[type="password"] {
      width: 100%;
      height: calc(44 * var(--u));
      padding: 0 calc(12 * var(--u));
      font-family: inherit;
      font-size: calc(14 * var(--u));
      color: var(--heading);
      background: #fff;
      border: 1.5px solid var(--input-border);
      border-radius: calc(8 * var(--u));
      outline: none;
      transition: border-color .15s, box-shadow .15s;
    }
    input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgb(180 0 37 / .12);
    }

    .btn-primary {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: calc(8 * var(--u));
      width: 100%;
      min-height: calc(44 * var(--u));
      padding: calc(11 * var(--u)) calc(18 * var(--u));
      font-family: inherit;
      font-size: calc(14 * var(--u));
      font-weight: 600;
      color: #fff;
      background: var(--accent);
      border: none;
      border-radius: calc(13 * var(--u));
      cursor: pointer;
      transition: background .15s;
      margin-top: calc(8 * var(--u));
    }
    .btn-primary:hover { background: var(--accent-hover); }
    .btn-primary svg   { width: calc(20 * var(--u)); height: calc(20 * var(--u)); flex-shrink: 0; }

    .help {
      margin-top: calc(20 * var(--u));
      color: var(--muted);
      font-size: calc(13 * var(--u));
      line-height: 1.5;
    }

    /* ── Decorative workflow cards (right side) ── */
    .workflow {
      position: absolute;
      z-index: 2;
      top: 36%;
      left: 60.9%;
      width: calc(220 * var(--u));
      display: grid;
      gap: calc(30 * var(--u));
      transform: skewY(4deg);
      pointer-events: none;
    }
    .workflow::after {
      content: '';
      position: absolute;
      z-index: -1;
      top: -30%; right: -24%; bottom: -20%;
      width: 75%;
      border: 1px solid var(--connector);
      border-left: 0;
      border-radius: 0 24px 24px 0;
    }

    .step {
      position: relative;
      display: flex;
      align-items: center;
      gap: calc(8 * var(--u));
      height: calc(64 * var(--u));
      padding: calc(16 * var(--u));
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: calc(13 * var(--u));
      color: var(--card-text);
      box-shadow: 0 12px 36px var(--card-shadow);
      backdrop-filter: blur(10px);
    }
    .step::after {
      content: '';
      position: absolute;
      left: 100%; top: 50%;
      width: 24%;
      border-top: 1px solid var(--line);
    }
    .step span      { font-size: calc(11.5 * var(--u)); white-space: nowrap; }
    .step svg       { flex-shrink: 0; width: calc(20 * var(--u)); height: calc(20 * var(--u)); stroke-width: 1.5; }
    .step-check     { margin-left: auto; }
    .step-circle {
      margin-left: auto;
      flex-shrink: 0;
      width: calc(17 * var(--u));
      height: calc(17 * var(--u));
      border: 1px solid var(--status-ring);
      border-radius: 50%;
    }

    /* ── Mobile (narrow or short viewport) ─────────────────────
       Below 1024px wide or 650px tall: switch to a simple
       single-column flow, hide photo/panel/cards.
    ─────────────────────────────────────────────────────────── */
    @media (max-width: 1023px), (max-height: 650px) {
      .page {
        height: auto;
        min-height: 100svh;
        overflow: visible;
      }
      .page-bg, .page-panel, .workflow { display: none; }
      .page::before {
        content: '';
        position: fixed;
        z-index: -1;
        inset: 45% -50% -20%;
        background: linear-gradient(135deg, rgb(241 241 243), var(--surface));
        transform: rotate(-35deg);
      }

      .left {
        position: static;
        width: 100%;
        max-width: 488px;
        min-height: 100svh;
        margin: 0 auto;
        padding: 32px 24px 40px;
        display: flex;
        flex-direction: column;
      }

      .hdr {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        padding-top: 0;
        flex-shrink: 0;
      }
      .brand      { font-size: 0.8125rem; gap: 6px; }
      .logo-mark  { width: 56px; }

      .lang-switcher        { position: static; border-radius: 9px; }
      .lang-switcher button { font-size: 0.8125rem; padding: 6px 14px; min-height: 36px; }

      .main {
        position: static;
        flex: 1;
        display: flex;
        flex-direction: column;
        justify-content: center;
        padding: 40px 0 24px;
      }
      .eyebrow     { font-size: 0.8125rem; margin-bottom: 14px; }
      .title       { font-size: clamp(34px, 8.5vw, 58px); margin-bottom: 10px; letter-spacing: -.035em; }
      .description { font-size: 0.9375rem; margin-bottom: 24px; }
      label        { font-size: 0.875rem; margin-bottom: 6px; }
      .form-group  { margin-bottom: 12px; }
      input[type="text"], input[type="email"], input[type="password"] {
        height: 44px; font-size: 0.875rem; border-radius: 8px; padding: 0 12px;
      }
      .btn-primary     { min-height: 44px; font-size: 0.875rem; border-radius: 13px; padding: 11px 18px; margin-top: 8px; }
      .btn-primary svg { width: 18px; height: 18px; }
      .help            { font-size: 0.8125rem; margin-top: 18px; }
    }
  </style>
</head>
<body>
<div class="page">

  <div class="page-bg" aria-hidden="true"></div>

  <svg class="page-panel" viewBox="0 0 1672 941" preserveAspectRatio="none" aria-hidden="true">
    <defs>
      <linearGradient id="fold-grad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" class="panel-fold-stop" stop-opacity=".28"/>
        <stop offset="1" class="panel-fold-stop" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <path class="panel-surface" d="M0 0H737L555 743Q548 765 568 781L800 941H0Z"/>
    <path fill="url(#fold-grad)"   d="M0 625L303 900Q317 914 320 941H0Z"/>
  </svg>

  <div class="left">

    <header class="hdr">
      <div class="brand">
        <div class="logo-mark" role="img" aria-label="T3 AppStore"></div>
        <span>AppStore</span>
      </div>
    </header>

    <div class="lang-switcher" role="group" aria-label="Language">
      <button type="button" lang="de" id="btn-de" onclick="setLang('de')">DE</button>
      <button type="button" lang="en" id="btn-en" onclick="setLang('en')">EN</button>
    </div>

    <main class="main">
      <p class="eyebrow" id="eyebrow">CLICK'N DEPLOY</p>

      <h1 class="title" id="title-h1">
        <span>Anwendungen einfach</span>
        <span class="title-accent" id="title-accent">bereitstellen</span>
      </h1>

      <p class="description" id="desc">Der DHBW AppStore stellt vorkonfigurierte Anwendungen und Umgebungen für Lehre, Forschung und Verwaltung bereit.</p>

      <#if displayMessage?? && message?has_content>
        <div class="alert alert-${message.type}">${kcSanitize(message.summary)?no_esc}</div>
      </#if>

      <#if realm.password>
        <form id="kc-form-login" action="${url.loginAction}" method="post">
          <input type="hidden" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>

          <div class="form-group">
            <label for="username" id="label-username">Benutzername</label>
            <input type="text" id="username" name="username"
              value="${(login.username!'')}"
              autocomplete="username" autofocus
              <#if usernameEditDisabled??>disabled</#if>/>
          </div>

          <div class="form-group">
            <div class="form-row-between">
              <label for="password" id="label-password">Passwort</label>
              <#if realm.resetPasswordAllowed>
                <a class="forgot" href="${url.loginResetCredentialsUrl}" id="link-forgot">Passwort vergessen?</a>
              </#if>
            </div>
            <input type="password" id="password" name="password" autocomplete="current-password"/>
          </div>

          <button type="submit" class="btn-primary" id="kc-login">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
              <polyline points="10 17 15 12 10 7"/>
              <line x1="15" y1="12" x2="3" y2="12"/>
            </svg>
            <span id="btn-label">Mit DHBW anmelden</span>
          </button>
        </form>
      </#if>

      <p class="help" id="help">Kein Account? Wenden Sie sich an Ihren Administrator.</p>
    </main>

  </div>

  <div class="workflow" aria-hidden="true">
    <div class="step">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/>
      </svg>
      <span id="step-0">App konfigurieren</span>
      <svg class="step-check" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="20 6 9 17 4 12"/>
      </svg>
    </div>
    <div class="step">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>
      </svg>
      <span id="step-1">Umgebung bereitstellen</span>
      <svg class="step-check" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="20 6 9 17 4 12"/>
      </svg>
    </div>
    <div class="step">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="5 3 19 12 5 21 5 3"/>
      </svg>
      <span id="step-2">Direkt loslegen</span>
      <span class="step-circle"></span>
    </div>
  </div>

</div>

<script>
var STRINGS = {
  de: {
    eyebrow: 'CLICK\'N DEPLOY',
    lead:    'Anwendungen einfach',
    accent:  'bereitstellen',
    desc:    'Der DHBW AppStore stellt vorkonfigurierte Anwendungen und Umgebungen für Lehre, Forschung und Verwaltung bereit.',
    btn:     'Mit DHBW anmelden',
    help:    'Kein Account? Wenden Sie sich an Ihren Administrator.',
    labelUser: 'Benutzername',
    labelPw:   'Passwort',
    forgot:    'Passwort vergessen?',
    steps:   ['App konfigurieren', 'Umgebung bereitstellen', 'Direkt loslegen']
  },
  en: {
    eyebrow: 'CLICK\'N DEPLOY',
    lead:    'Deploy\napplications with',
    accent:  'ease',
    desc:    'The DHBW AppStore provides preconfigured applications and environments for teaching, research, and administration.',
    btn:     'Sign in with DHBW',
    help:    'No account? Contact your administrator.',
    labelUser: 'Username',
    labelPw:   'Password',
    forgot:    'Forgot password?',
    steps:   ['Configure app', 'Deploy environment', 'Get started']
  }
};

function applyLang(l) {
  var d = STRINGS[l];

  document.getElementById('eyebrow').textContent = d.eyebrow;
  document.getElementById('desc').textContent    = d.desc;
  document.getElementById('btn-label').textContent = d.btn;
  document.getElementById('help').textContent    = d.help;

  var el;
  if ((el = document.getElementById('label-username'))) el.textContent = d.labelUser;
  if ((el = document.getElementById('label-password'))) el.textContent = d.labelPw;
  if ((el = document.getElementById('link-forgot')))    el.textContent = d.forgot;

  /* Rebuild title lead spans — mirrors React's titleLeadLines.map() */
  var h1     = document.getElementById('title-h1');
  var accent = document.getElementById('title-accent');
  while (h1.firstChild !== accent) h1.removeChild(h1.firstChild);
  d.lead.split('\n').reverse().forEach(function(line) {
    var span = document.createElement('span');
    span.textContent = line;
    h1.insertBefore(span, accent);
  });
  accent.textContent = d.accent;

  for (var i = 0; i < 3; i++) {
    if ((el = document.getElementById('step-' + i))) el.textContent = d.steps[i];
  }

  document.getElementById('btn-de').setAttribute('aria-pressed', l === 'de' ? 'true' : 'false');
  document.getElementById('btn-en').setAttribute('aria-pressed', l === 'en' ? 'true' : 'false');
  document.documentElement.lang = l;
}

function setLang(l) {
  try { localStorage.setItem('kc-lang', l); } catch (e) {}
  applyLang(l);
}

(function init() {
  var saved;
  try { saved = localStorage.getItem('kc-lang'); } catch (e) {}
  applyLang(saved === 'en' ? 'en' : 'de');
}());
</script>
</body>
</html>
