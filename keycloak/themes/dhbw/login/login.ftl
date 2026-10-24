<!DOCTYPE html>
<html lang="${(currentLanguageTag!'de')}" class="login-pf">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>DHBW AppStore – Login</title>
  <link rel="icon" href="${url.resourcesPath}/img/favicon.png" type="image/png">
  <style>
    /* ── Reset ──────────────────────────────────────────────────── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', ui-sans-serif, system-ui, sans-serif; }

    @font-face {
      font-family: 'Inter';
      src: url('${url.resourcesPath}/img/InterVariable.woff2') format('woff2');
      font-weight: 100 900;
      font-style: normal;
      font-display: swap;
    }

    /* ── T3 colour tokens ───────────────────────────────────────── */
    :root {
      --c-accent:        #e2001a;
      --c-accent-hover:  #940012;
      --c-muted:         #74788a;
      --c-surface:       #fafafa;
      --c-heading:       #10191f;
      --c-divider:       #e9e9ed;
      --c-icon:          #374151;
      --c-lang-border:   #e7e7eb;
      --c-lang-text:     #646b78;
      --c-lang-sel:      #f7e0e5;
      --c-lang-hover:    #f4e9ec;
      --c-card-bg:       rgba(255,255,255,.88);
      --c-card-border:   rgba(255,255,255,.25);
      --c-card-shadow:   rgba(23,32,43,.05);
      --c-card-text:     #39434b;
      --c-connector:     rgba(255,255,255,.44);
      --c-line:          rgba(255,255,255,.56);
      --c-status-ring:   #d8526a;
      --c-fold:          #eeeeef;
      --c-fold-mobile:   #f1f1f3;
    }

    /* ── Full-viewport shell ────────────────────────────────────── */
    .auth-page {
      position: relative;
      isolation: isolate;
      height: 100svh;
      overflow: clip;
      background: var(--c-surface);
      color: var(--c-heading);
      font-family: 'Inter', ui-sans-serif, system-ui, sans-serif;
    }

    /* ── Background photo ───────────────────────────────────────── */
    .auth-backdrop {
      position: absolute;
      inset: 0;
      width: 100%; height: 100%;
      background-image: url('${url.resourcesPath}/img/background.jpg');
      background-size: cover;
      background-position: left center;
      filter: saturate(.72) brightness(.97);
      z-index: -3;
      pointer-events: none;
    }

    /* ── SVG diagonal panel (white left section) ────────────────── */
    .auth-panel {
      position: absolute;
      inset: 0;
      width: 100%; height: 100%;
      z-index: -1;
      pointer-events: none;
    }
    .auth-panel-surface { fill: var(--c-surface); }
    .auth-fold-stop     { stop-color: var(--c-fold); }

    /* ── Viewport unit for proportional scaling ─────────────────── */
    /* reference design: 1672 × 941 px */
    .auth-page {
      --u: min(calc(100vw / 1672), calc(100svh / 941));
    }

    /* ── Left content column ────────────────────────────────────── */
    .auth-content {
      width:       calc(370 * var(--u));
      height:      100%;
      margin-left: 6.95%;
    }

    /* ── Header: logo + language switcher ───────────────────────── */
    .auth-header { padding-top: 9.7svh; }

    .auth-brand {
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      gap: calc(7 * var(--u));
      color: var(--c-muted);
      font-size: calc(14 * var(--u));
    }
    .auth-logo-mark {
      width:        calc(80 * var(--u));
      aspect-ratio: 182 / 151;
      background:   var(--c-accent);
      mask:         url('${url.resourcesPath}/img/logo.png') center / contain no-repeat;
      -webkit-mask: url('${url.resourcesPath}/img/logo.png') center / contain no-repeat;
    }

    .auth-language {
      position:     absolute;
      top:          4.4%;
      left:         32.1%;
      display:      flex;
      overflow:     hidden;
      border:       1px solid var(--c-lang-border);
      border-radius: calc(9 * var(--u));
    }
    .auth-language button {
      padding:      calc(6 * var(--u)) calc(12 * var(--u));
      font-family:  inherit;
      font-size:    calc(14 * var(--u));
      line-height:  1.35;
      color:        var(--c-lang-text);
      background:   none;
      border:       none;
      cursor:       pointer;
      transition:   background .15s;
    }
    .auth-language button[aria-pressed='true'] {
      color:       var(--c-accent);
      background:  var(--c-lang-sel);
    }
    .auth-language button:hover { background: var(--c-lang-hover); }

    /* ── Main: eyebrow + headline + form slot ───────────────────── */
    .auth-main {
      position: absolute;
      top:      27.3%;
      width:    inherit;
    }

    .auth-eyebrow {
      margin-bottom: calc(18 * var(--u));
      font-size:     calc(13 * var(--u));
      line-height:   1.3;
      letter-spacing: .23em;
      color:         var(--c-accent);
    }

    .auth-title {
      margin-bottom: calc(12 * var(--u));
      font-size:     calc(58 * var(--u));
      font-weight:   750;
      font-optical-sizing: none;
      line-height:   1.03;
      letter-spacing: -.005em;
    }
    .auth-title span { display: block; }
    .auth-title-accent { color: var(--c-accent); }

    /* ── Login form slot (replaces the React component) ────────── */
    .auth-login-description {
      margin-bottom: calc(32 * var(--u));
      color:    var(--c-muted);
      font-size: calc(17 * var(--u));
      line-height: 1.5;
    }

    /* Primary button */
    #kc-login, .kc-btn-primary {
      display:     flex;
      align-items: center;
      justify-content: center;
      gap:         8px;
      width:       100%;
      min-height:  calc(44 * var(--u));
      padding:     calc(11 * var(--u)) calc(18 * var(--u));
      font-family: inherit;
      font-size:   calc(14 * var(--u));
      font-weight: 600;
      color:       #fff;
      background:  var(--c-accent);
      border:      none;
      border-radius: calc(13 * var(--u));
      cursor:      pointer;
      transition:  background .15s;
      line-height: 1.5;
    }
    #kc-login:hover, .kc-btn-primary:hover { background: var(--c-accent-hover); }

    /* "No account" help line */
    .auth-login-help {
      margin-top: calc(20 * var(--u));
      color:      var(--c-muted);
      font-size:  calc(13 * var(--u));
      line-height: 1.5;
    }

    /* Hidden username/password form (used when direct keycloak form needed) */
    #kc-form-login { display: none; }

    /* Error / alert */
    .auth-alert {
      margin-bottom: calc(16 * var(--u));
      padding: calc(10 * var(--u)) calc(14 * var(--u));
      border-radius: calc(8 * var(--u));
      font-size: calc(13 * var(--u));
      line-height: 1.4;
    }
    .auth-alert--error   { background: #fde8e8; border: 1px solid #fbd5d5; color: #b91c1c; }
    .auth-alert--warning { background: #fef3c7; border: 1px solid #fde68a; color: #b45309; }
    .auth-alert--info    { background: #dbeafe; border: 1px solid #bfdbfe; color: #1d4ed8; }

    /* ── Feature strip (bottom) ─────────────────────────────────── */
    .auth-features {
      position: absolute;
      bottom:   8.7%;
      width:    inherit;
      display:  grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap:      calc(46 * var(--u));
      padding-top: calc(28 * var(--u));
      border-top: 1px solid var(--c-divider);
    }
    .auth-feature {
      display:        flex;
      flex-direction: column;
      gap:            calc(13 * var(--u));
      color:          var(--c-icon);
    }
    .auth-feature svg {
      width:  calc(23 * var(--u));
      height: calc(23 * var(--u));
      stroke-width: 1.5;
    }
    .auth-feature span {
      color:     var(--c-muted);
      font-size: calc(13 * var(--u));
      line-height: 1.35;
    }

    /* ── Workflow cards (decorative, right side) ────────────────── */
    .auth-workflow {
      position:  absolute;
      top:       36%;
      left:      60.9%;
      width:     calc(220 * var(--u));
      display:   grid;
      gap:       calc(30 * var(--u));
      transform: skewY(4deg);
    }
    .auth-workflow::after {
      content:      '';
      position:     absolute;
      z-index:      -1;
      right:        -24%;
      top:          -30%;
      bottom:       -20%;
      width:        75%;
      border:       1px solid var(--c-connector);
      border-left:  0;
      border-radius: 0 24px 24px 0;
    }
    .auth-step {
      position:    relative;
      display:     flex;
      align-items: center;
      gap:         calc(8 * var(--u));
      height:      calc(64 * var(--u));
      padding:     calc(16 * var(--u));
      border:      1px solid var(--c-card-border);
      border-radius: calc(13 * var(--u));
      background:  var(--c-card-bg);
      color:       var(--c-card-text);
      box-shadow:  0 12px 36px var(--c-card-shadow);
      backdrop-filter: blur(10px);
    }
    .auth-step::after {
      content:    '';
      position:   absolute;
      left:       100%;
      top:        50%;
      width:      24%;
      border-top: 1px solid var(--c-line);
    }
    .auth-step span {
      font-size:   calc(11.5 * var(--u));
      white-space: nowrap;
    }
    .auth-step svg {
      flex-shrink: 0;
      width:       calc(20 * var(--u));
      height:      calc(20 * var(--u));
      stroke-width: 1.5;
    }
    .auth-step-check {
      margin-left: auto;
      width:       calc(19 * var(--u)) !important;
    }
    .auth-step-circle {
      margin-left: auto;
      width:       calc(17 * var(--u));
      height:      calc(17 * var(--u));
      border:      1px solid var(--c-status-ring);
      border-radius: 50%;
      flex-shrink: 0;
    }

    /* ── Mobile / narrow viewport ───────────────────────────────── */
    @media (max-width: 1023px), (max-height: 650px) {
      .auth-page   { --u: 1px; height: auto; min-height: 100svh; }
      .auth-backdrop, .auth-workflow, .auth-panel { display: none; }
      .auth-page::before {
        content: '';
        position: absolute;
        z-index: -1;
        inset: 45% -50% -20%;
        background: linear-gradient(135deg, var(--c-fold-mobile), var(--c-surface));
        transform: rotate(-35deg);
      }
      .auth-content {
        width: 100%;
        max-width: 488px;
        min-height: 100svh;
        margin: 0 auto;
        padding: 32px 24px;
        display: flex;
        flex-direction: column;
      }
      .auth-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        padding: 0;
      }
      .auth-language {
        position: static;
        border-radius: 9px;
      }
      .auth-language button { min-height: 40px; min-width: 44px; }
      .auth-main {
        position: static;
        width: 100%;
        margin: 60px 0;
      }
      .auth-title {
        font-size: clamp(34px, 8.5vw, 58px);
        letter-spacing: -.035em;
      }
      .auth-login-description { font-size: 17px; }
      #kc-login, .kc-btn-primary { font-size: 15px; min-height: 44px; border-radius: 13px; }
      .auth-login-help { font-size: 13px; }
      .auth-features {
        position: static;
        width: 100%;
        margin-top: auto;
        gap: 16px;
      }
      .auth-feature span { font-size: 12px; overflow-wrap: anywhere; }
    }

    @media (prefers-reduced-motion: reduce) {
      .auth-language button, #kc-login { transition: none; }
    }
  </style>
</head>
<body>

<div class="auth-page">

  <!-- Background photo -->
  <div class="auth-backdrop" aria-hidden="true"></div>

  <!-- Diagonal white panel (SVG) -->
  <svg class="auth-panel" viewBox="0 0 1672 941" preserveAspectRatio="none" aria-hidden="true">
    <defs>
      <linearGradient id="auth-fold" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" class="auth-fold-stop" stop-opacity=".28"/>
        <stop offset="1" class="auth-fold-stop" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <path class="auth-panel-surface" d="M0 0H737L555 743Q548 765 568 781L800 941H0Z"/>
    <path fill="url(#auth-fold)"    d="M0 625L303 900Q317 914 320 941H0Z"/>
  </svg>

  <!-- Left content column -->
  <div class="auth-content">

    <header class="auth-header">
      <!-- Logo: colour mask like the React component -->
      <div class="auth-brand">
        <div class="auth-logo-mark" role="img" aria-label="T3 AppStore"></div>
        <span>AppStore</span>
      </div>

      <!-- Language switcher — DE / EN toggle -->
      <div class="auth-language" role="group" aria-label="Sprache / Language">
        <button type="button" lang="de" onclick="setLang('de')" id="btn-de">DE</button>
        <button type="button" lang="en" onclick="setLang('en')" id="btn-en">EN</button>
      </div>
    </header>

    <main class="auth-main">

      <p class="auth-eyebrow">CLICK'N DEPLOY</p>

      <h1 class="auth-title">
        <span id="title-lead">Anwendungen einfach</span>
        <span class="auth-title-accent" id="title-accent">bereitstellen</span>
      </h1>

      <!-- Alert / error messages from Keycloak -->
      <#if displayMessage?? && message?has_content>
        <div class="auth-alert auth-alert--${message.type}">
          ${kcSanitize(message.summary)?no_esc}
        </div>
      </#if>

      <p class="auth-login-description" id="desc">
        Der DHBW AppStore stellt vorkonfigurierte Anwendungen und Umgebungen für Lehre, Forschung und Verwaltung bereit.
      </p>

      <!-- The real Keycloak login form — visually hidden, triggered by button below -->
      <form id="kc-form-login" action="${url.loginAction}" method="post" style="display:none;">
        <input type="hidden" name="username" id="real-username"/>
        <input type="hidden" name="password" id="real-password"/>
        <#if usernameEditDisabled??>
          <input type="hidden" id="username" name="username" value="${login.username!''}"/>
        </#if>
        <input type="hidden" name="credentialId"
          <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
      </form>

      <!-- Visible primary button — redirects to Keycloak OIDC flow OR submits the form -->
      <#-- When realm requires direct login (no external IdP), show form inline -->
      <#if realm.password>
        <div id="direct-login-wrapper">
          <div id="inline-form" style="display:none; margin-bottom: calc(16 * var(--u));">
            <div style="margin-bottom: 14px;">
              <label for="username" style="display:block; font-size:0.875rem; font-weight:600; color:#1f2e44; margin-bottom:6px;">
                <#if !realm.loginWithEmailAllowed>Benutzername<#elseif !realm.registrationEmailAsUsername>Benutzername oder E-Mail<#else>E-Mail</#if>
              </label>
              <input type="text" id="username" name="username"
                value="${(login.username!'')}"
                autocomplete="username"
                autofocus
                style="width:100%; height:44px; padding:0 12px; font-family:inherit; font-size:0.9375rem; color:#0f1b30; background:#fff; border:1.5px solid #e4e9ef; border-radius:8px; outline:none; transition:border-color .15s, box-shadow .15s;"
                onfocus="this.style.borderColor='#e2001a'; this.style.boxShadow='0 0 0 3px rgba(226,0,26,.12)'"
                onblur="this.style.borderColor='#e4e9ef'; this.style.boxShadow='none'"
              />
            </div>
            <div style="margin-bottom: 6px;">
              <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px;">
                <label for="password" style="font-size:0.875rem; font-weight:600; color:#1f2e44;">Passwort</label>
                <#if realm.resetPasswordAllowed>
                  <a href="${url.loginResetCredentialsUrl}" style="font-size:0.8125rem; color:#e2001a; font-weight:500;">Passwort vergessen?</a>
                </#if>
              </div>
              <input type="password" id="password" name="password"
                autocomplete="current-password"
                style="width:100%; height:44px; padding:0 12px; font-family:inherit; font-size:0.9375rem; color:#0f1b30; background:#fff; border:1.5px solid #e4e9ef; border-radius:8px; outline:none; transition:border-color .15s, box-shadow .15s;"
                onfocus="this.style.borderColor='#e2001a'; this.style.boxShadow='0 0 0 3px rgba(226,0,26,.12)'"
                onblur="this.style.borderColor='#e4e9ef'; this.style.boxShadow='none'"
              />
            </div>
          </div>

          <button type="button" id="kc-login" onclick="handleLogin()">
            <!-- Arrow-right icon (inline SVG, no external dep) -->
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              aria-hidden="true">
              <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
              <polyline points="10 17 15 12 10 7"/>
              <line x1="15" y1="12" x2="3" y2="12"/>
            </svg>
            <span id="btn-label">Mit DHBW anmelden</span>
          </button>
        </div>
      </#if>

      <p class="auth-login-help" id="help-text">
        Kein Account? Wenden Sie sich an Ihren Administrator.
      </p>
    </main>

    <!-- Feature strip -->
    <footer class="auth-features" aria-hidden="true">
      <div class="auth-feature">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
        <span id="feat-diverse">Vielfältige Anwendungen</span>
      </div>
      <div class="auth-feature">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
        <span id="feat-preconfigured">Vorkonfigurierte Umgebungen</span>
      </div>
      <div class="auth-feature">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        <span id="feat-secure">Sicher &amp; Hochschulintern</span>
      </div>
    </footer>
  </div>

  <!-- Decorative workflow cards (right side, aria-hidden) -->
  <div class="auth-workflow" aria-hidden="true">
    <div class="auth-step">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/></svg>
      <span id="step-configure">App konfigurieren</span>
      <svg class="auth-step-check" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
    </div>
    <div class="auth-step">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
      <span id="step-deploy">Umgebung bereitstellen</span>
      <svg class="auth-step-check" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
    </div>
    <div class="auth-step">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      <span id="step-start">Direkt loslegen</span>
      <span class="auth-step-circle"></span>
    </div>
  </div>

</div><!-- .auth-page -->

<script>
  // ── Language switcher ─────────────────────────────────────────
  var i18n = {
    de: {
      eyebrow:    'CLICK\'N DEPLOY',
      titleLead:  'Anwendungen einfach',
      titleAccent:'bereitstellen',
      desc:       'Der DHBW AppStore stellt vorkonfigurierte Anwendungen und Umgebungen für Lehre, Forschung und Verwaltung bereit.',
      btnLabel:   'Mit DHBW anmelden',
      help:       'Kein Account? Wenden Sie sich an Ihren Administrator.',
      featDiverse:'Vielfältige Anwendungen',
      featPre:    'Vorkonfigurierte Umgebungen',
      featSecure: 'Sicher & Hochschulintern',
      stepConfig: 'App konfigurieren',
      stepDeploy: 'Umgebung bereitstellen',
      stepStart:  'Direkt loslegen',
    },
    en: {
      eyebrow:    'CLICK\'N DEPLOY',
      titleLead:  'Deploy applications',
      titleAccent:'with ease',
      desc:       'The DHBW AppStore provides preconfigured applications and environments for teaching, research and administration.',
      btnLabel:   'Sign in with DHBW',
      help:       'No account? Contact your administrator.',
      featDiverse:'Diverse Applications',
      featPre:    'Preconfigured Environments',
      featSecure: 'Secure & University-internal',
      stepConfig: 'Configure app',
      stepDeploy: 'Deploy environment',
      stepStart:  'Get started',
    }
  };

  var currentLang = (navigator.language || 'de').slice(0,2) === 'en' ? 'en' : 'de';
  try { var saved = localStorage.getItem('kc-lang'); if (saved) currentLang = saved; } catch(e){}

  function setLang(lang) {
    currentLang = lang;
    try { localStorage.setItem('kc-lang', lang); } catch(e){}
    var t = i18n[lang] || i18n['de'];
    document.querySelector('.auth-eyebrow').textContent = t.eyebrow;
    document.getElementById('title-lead').textContent   = t.titleLead;
    document.getElementById('title-accent').textContent = t.titleAccent;
    document.getElementById('desc').textContent         = t.desc;
    document.getElementById('btn-label').textContent    = t.btnLabel;
    document.getElementById('help-text').textContent    = t.help;
    document.getElementById('feat-diverse').textContent     = t.featDiverse;
    document.getElementById('feat-preconfigured').textContent = t.featPre;
    document.getElementById('feat-secure').textContent      = t.featSecure;
    document.getElementById('step-configure').textContent   = t.stepConfig;
    document.getElementById('step-deploy').textContent      = t.stepDeploy;
    document.getElementById('step-start').textContent       = t.stepStart;
    document.getElementById('btn-de').setAttribute('aria-pressed', lang === 'de' ? 'true' : 'false');
    document.getElementById('btn-en').setAttribute('aria-pressed', lang === 'en' ? 'true' : 'false');
    document.documentElement.lang = lang;
  }

  // init language on load
  setLang(currentLang);

  // ── Login handler ─────────────────────────────────────────────
  // Keycloak dev mode: realm has direct grant → show inline form on first
  // click, submit on second. If realm uses external IdP only, the form
  // action redirects straight away.
  var formVisible = false;
  function handleLogin() {
    var wrapper  = document.getElementById('inline-form');
    var form     = document.getElementById('kc-form-login');
    var username = document.getElementById('username');
    var password = document.getElementById('password');

    if (!formVisible) {
      wrapper.style.display = 'block';
      formVisible = true;
      if (username) username.focus();
      return;
    }
    // copy values into the hidden form and submit
    var hiddenUser = form.querySelector('#real-username') || form.querySelector('[name="username"]');
    var hiddenPass = form.querySelector('#real-password') || form.querySelector('[name="password"]');
    if (hiddenUser && username) hiddenUser.value = username.value;
    if (hiddenPass && password) hiddenPass.value = password.value;
    form.submit();
  }
</script>

</body>
</html>
