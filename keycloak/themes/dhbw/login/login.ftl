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

    :root {
      --accent:       rgb(180 0 37);
      --accent-hover: rgb(148 0 30);
      --muted:        rgb(116 123 138);
      --surface:      rgb(250 250 250);
      --heading:      rgb(15 27 48);
      --divider:      rgb(233 233 237);
      --icon:         rgb(55 65 81);
      --lang-border:  rgb(231 231 235);
      --lang-text:    rgb(100 107 120);
      --lang-sel:     rgb(247 224 229);
      --lang-hover:   rgb(244 233 236);
      --card-bg:      rgba(255 255 255 / .878);
      --card-border:  rgba(255 255 255 / .251);
      --card-shadow:  rgba(23 32 43 / .051);
      --card-text:    rgb(57 67 75);
      --connector:    rgba(255 255 255 / .439);
      --line:         rgba(255 255 255 / .565);
      --status-ring:  rgb(216 82 106);
      --fold:         rgb(238 238 239);
      --input-border: rgb(228 233 239);
      --label:        rgb(31 46 68);
    }

    html, body { height: 100%; }

    body {
      font-family: 'Inter', ui-sans-serif, system-ui, sans-serif;
      background: var(--surface);
      color: var(--heading);
    }

    /* ═══════════════════════════════════════════════════════════
       SCALING UNIT — identical to React's --auth-unit
       min(100vw/1672, 100svh/941)
    ═══════════════════════════════════════════════════════════ */
    .page {
      --u: min(calc(100vw / 1672), calc(100svh / 941));
      position: relative;
      width: 100vw;
      height: 100svh;
      overflow: hidden;
    }

    /* Background photo */
    .page-bg {
      position: absolute;
      inset: 0;
      background-image: url('${url.resourcesPath}/img/background.jpg');
      background-size: cover;
      background-position: left center;
      filter: saturate(.72) brightness(.97);
      z-index: 0;
    }

    /* SVG diagonal white panel */
    .page-panel {
      position: absolute;
      inset: 0;
      width: 100%; height: 100%;
      z-index: 1;
      pointer-events: none;
    }
    .panel-surface { fill: var(--surface); }
    .panel-fold-stop { stop-color: var(--fold); }

    /* Content column — absolutely positioned, same as React auth-content */
    .left {
      position: absolute;
      z-index: 2;
      top: 0; left: 0; bottom: 0;
      width: calc(370 * var(--u));
      margin-left: 6.95%;
      display: flex;
      flex-direction: column;
    }

    /* ── Header ── */
    .hdr {
      padding-top: var(--auth-header-top, 9.7svh);
      flex-shrink: 0;
    }

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

    /* Language switcher — absolutely positioned like React */
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
    .lang-switcher button[aria-pressed='true'] {
      color: var(--accent);
      background: var(--lang-sel);
    }
    .lang-switcher button:hover { background: var(--lang-hover); }

    /* ── Main content — absolutely positioned, bounded above features ── */
    .main {
      position: absolute;
      top: 27.3%;
      bottom: calc(8.7% + 120 * var(--u));
      width: 100%;
      overflow: visible;
      display: flex;
      flex-direction: column;
      justify-content: flex-start;
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
    .title span { display: block; }
    .title-accent { color: var(--accent); }

    .description {
      margin: 0 0 calc(32 * var(--u));
      color: var(--muted);
      font-size: calc(17 * var(--u));
      line-height: 1.5;
    }

    /* ── Alert ── */
    .alert {
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: 16px;
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

    /* Primary button */
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
    .btn-primary svg { width: calc(20 * var(--u)); height: calc(20 * var(--u)); flex-shrink: 0; }

    .help {
      margin-top: calc(20 * var(--u));
      color: var(--muted);
      font-size: calc(13 * var(--u));
      line-height: 1.5;
    }

    /* ── Feature strip — absolutely positioned at bottom ── */
    .features {
      position: absolute;
      bottom: 8.7%;
      width: 100%;
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: calc(46 * var(--u));
      padding-top: calc(28 * var(--u));
      border-top: 1px solid var(--divider);
    }
    .feature {
      display: flex;
      flex-direction: column;
      gap: calc(13 * var(--u));
      color: var(--icon);
    }
    .feature svg { width: calc(23 * var(--u)); height: calc(23 * var(--u)); stroke-width: 1.5; }
    .feature span { color: var(--muted); font-size: calc(13 * var(--u)); line-height: 1.35; }

    /* ═══════════════════════════════════════════════════════════
       WORKFLOW CARDS — absolutely positioned, right side
    ═══════════════════════════════════════════════════════════ */
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
      right: -24%;
      top: -30%; bottom: -20%;
      width: 75%;
      border: 1px solid var(--connector);
      border-left: 0;
      border-radius: 0 24px 24px 0;
    }
    .step {
      display: flex;
      align-items: center;
      gap: calc(8 * var(--u));
      height: calc(64 * var(--u));
      padding: calc(16 * var(--u));
      border: 1px solid var(--card-border);
      border-radius: calc(13 * var(--u));
      background: var(--card-bg);
      color: var(--card-text);
      box-shadow: 0 12px 36px var(--card-shadow);
      backdrop-filter: blur(10px);
      position: relative;
    }
    .step::after {
      content: '';
      position: absolute;
      left: 100%; top: 50%;
      width: 24%;
      border-top: 1px solid var(--line);
    }
    .step span { font-size: calc(11.5 * var(--u)); white-space: nowrap; }
    .step svg  { flex-shrink: 0; width: calc(20 * var(--u)); height: calc(20 * var(--u)); stroke-width: 1.5; }
    .step-check { margin-left: auto; }
    .step-circle {
      margin-left: auto;
      width: calc(17 * var(--u));
      height: calc(17 * var(--u));
      border: 1px solid var(--status-ring);
      border-radius: 50%;
      flex-shrink: 0;
    }

    /* ═══════════════════════════════════════════════════════════
       MOBILE  (< 1024px or short viewport)
    ═══════════════════════════════════════════════════════════ */
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

      /* Full-height flex column, centred horizontally */
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

      .brand { font-size: 0.8125rem; gap: 6px; }
      .logo-mark { width: 56px; }

      .lang-switcher { position: static; border-radius: 9px; }
      .lang-switcher button { font-size: 0.8125rem; padding: 6px 14px; min-height: 36px; }

      /* Main grows to fill available space, form content top-aligned with gap from header */
      .main {
        position: static;
        width: 100%;
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
      .btn-primary {
        min-height: 44px; font-size: 0.875rem; border-radius: 13px;
        padding: 11px 18px; margin-top: 8px;
      }
      .btn-primary svg { width: 18px; height: 18px; }
      .help { font-size: 0.8125rem; margin-top: 18px; }

      /* Features sit at the very bottom — pushed there by flex */
      .features {
        position: static;
        flex-shrink: 0;
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 16px;
        padding-top: 24px;
        border-top: 1px solid var(--divider);
        margin-top: auto;
      }
      .feature svg  { width: 20px; height: 20px; }
      .feature span { font-size: 0.75rem; overflow-wrap: anywhere; }
    }
  </style>
</head>
<body>
<div class="page">

  <div class="page-bg" aria-hidden="true"></div>

  <!-- Diagonal white SVG panel -->
  <svg class="page-panel" viewBox="0 0 1672 941" preserveAspectRatio="none" aria-hidden="true">
    <defs>
      <linearGradient id="fold-grad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" class="panel-fold-stop" stop-opacity=".28"/>
        <stop offset="1" class="panel-fold-stop" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <path class="panel-surface" d="M0 0H737L555 743Q548 765 568 781L800 941H0Z"/>
    <path fill="url(#fold-grad)"  d="M0 625L303 900Q317 914 320 941H0Z"/>
  </svg>

  <!-- Left column -->
  <div class="left">

    <header class="hdr">
      <div class="brand">
        <div class="logo-mark" role="img" aria-label="T3 AppStore"></div>
        <span>AppStore</span>
      </div>
      <div class="lang-switcher" role="group" aria-label="Language">
        <button type="button" lang="de" id="btn-de" onclick="setLang('de')">DE</button>
        <button type="button" lang="en" id="btn-en" onclick="setLang('en')">EN</button>
      </div>
    </header>

    <main class="main">
      <p class="eyebrow" id="eyebrow">CLICK'N DEPLOY</p>

      <h1 class="title" id="title-h1">
        <span>Anwendungen einfach</span>
        <span class="title-accent" id="title-accent">bereitstellen</span>
      </h1>

      <p class="description" id="desc">Der DHBW AppStore stellt vorkonfigurierte Anwendungen und Umgebungen für Lehre, Forschung und Verwaltung bereit.</p>

      <!-- Keycloak error/info messages -->
      <#if displayMessage?? && message?has_content>
        <div class="alert alert-${message.type}">
          ${kcSanitize(message.summary)?no_esc}
        </div>
      </#if>

      <!-- Login form -->
      <#if realm.password>
        <form id="kc-form-login" action="${url.loginAction}" method="post">
          <input type="hidden" name="credentialId"
            <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>

          <div class="form-group">
            <label for="username" id="label-username">Benutzername</label>
            <input type="text" id="username" name="username"
              value="${(login.username!'')}"
              autocomplete="username"
              autofocus
              <#if usernameEditDisabled??>disabled</#if>
            />
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

    <footer class="features" aria-hidden="true">
      <div class="feature">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
        </svg>
        <span id="feat-0">Vielfältige Anwendungen</span>
      </div>
      <div class="feature">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>
        </svg>
        <span id="feat-1">Vorkonfigurierte Umgebungen</span>
      </div>
      <div class="feature">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        <span id="feat-2">Sicher &amp; Hochschulintern</span>
      </div>
    </footer>

  </div><!-- .left -->

  <!-- Decorative workflow cards -->
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

</div><!-- .page -->

<script>
var t = {
  de: {
    eyebrow:'CLICK\'N DEPLOY', lead:'Anwendungen einfach', accent:'bereitstellen',
    desc:'Der DHBW AppStore stellt vorkonfigurierte Anwendungen und Umgebungen für Lehre, Forschung und Verwaltung bereit.',
    btn:'Mit DHBW anmelden', help:'Kein Account? Wenden Sie sich an Ihren Administrator.',
    labelUser:'Benutzername', labelPw:'Passwort', forgot:'Passwort vergessen?',
    feat:['Vielfältige Anwendungen','Vorkonfigurierte Umgebungen','Sicher & Hochschulintern'],
    steps:['App konfigurieren','Umgebung bereitstellen','Direkt loslegen']
  },
  en: {
    eyebrow:'CLICK\'N DEPLOY', lead:'Deploy\napplications with', accent:'ease',
    desc:'The DHBW AppStore provides preconfigured applications and environments for teaching, research, and administration.',
    btn:'Sign in with DHBW', help:'No account? Contact your administrator.',
    labelUser:'Username', labelPw:'Password', forgot:'Forgot password?',
    feat:['Diverse Applications','Preconfigured Environments','Secure & University-Internal'],
    steps:['Configure app','Deploy environment','Get started']
  }
};

var lang = 'de';
try { var s = localStorage.getItem('kc-lang'); if (s==='en'||s==='de') lang=s; } catch(e){}

function setLang(l) {
  lang = l;
  try { localStorage.setItem('kc-lang', l); } catch(e) {}
  var d = t[l];
  document.getElementById('eyebrow').textContent      = d.eyebrow;

  // Split lead on \n — same logic as React's titleLeadLines.map()
  var h1 = document.getElementById('title-h1');
  // Remove old lead spans (all but last child which is title-accent)
  var accent = document.getElementById('title-accent');
  while (h1.firstChild !== accent) h1.removeChild(h1.firstChild);
  // Insert new lead spans before accent
  var lines = d.lead.split('\n');
  for (var i = lines.length - 1; i >= 0; i--) {
    var s = document.createElement('span');
    s.textContent = lines[i];
    h1.insertBefore(s, accent);
  }
  accent.textContent = d.accent;

  document.getElementById('desc').textContent         = d.desc;
  document.getElementById('btn-label').textContent    = d.btn;
  document.getElementById('help').textContent         = d.help;
  var lu = document.getElementById('label-username');
  if (lu) lu.textContent = d.labelUser;
  var lp = document.getElementById('label-password');
  if (lp) lp.textContent = d.labelPw;
  var lf = document.getElementById('link-forgot');
  if (lf) lf.textContent = d.forgot;
  for (var i=0; i<3; i++) {
    var f = document.getElementById('feat-'+i);
    if (f) f.textContent = d.feat[i];
    var s = document.getElementById('step-'+i);
    if (s) s.textContent = d.steps[i];
  }
  document.getElementById('btn-de').setAttribute('aria-pressed', l==='de'?'true':'false');
  document.getElementById('btn-en').setAttribute('aria-pressed', l==='en'?'true':'false');
  document.documentElement.lang = l;
}

setLang(lang);
</script>
</body>
</html>
