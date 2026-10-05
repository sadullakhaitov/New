/* Emir Food — Telegram Mini App */
(() => {
  'use strict';

  const tg = window.Telegram && window.Telegram.WebApp;
  const app = document.getElementById('app');
  const sheetRoot = document.getElementById('sheet-root');
  const toastEl = document.getElementById('toast');
  const LANGS = ['uz', 'cyr', 'ru'];
  const LANG_SHORT = { uz: "O'Z", cyr: 'ЎЗ', ru: 'RU' };
  const LANG_LABEL = { uz: "O'zbekcha", cyr: 'Ўзбекча', ru: 'Русский' };

  // ---------- yordamchilar ----------
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
    },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ } },
  };
  const fmt = (n) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  const haptic = (kind) => {
    try {
      if (!tg || !tg.HapticFeedback) return;
      if (kind === 'ok' || kind === 'error') tg.HapticFeedback.notificationOccurred(kind === 'ok' ? 'success' : 'error');
      else tg.HapticFeedback.impactOccurred(kind || 'light');
    } catch (e) { /* ignore */ }
  };
  const isPhoto = (src) => /^img\/p\//.test(src || '');

  function T(key, vars) {
    const dict = window.I18N[state.lang] || window.I18N.uz;
    let s = dict[key] != null ? dict[key] : (window.I18N.uz[key] != null ? window.I18N.uz[key] : key);
    if (vars) Object.keys(vars).forEach((k) => { s = s.split('{' + k + '}').join(vars[k]); });
    return s;
  }
  const money = (n) => fmt(n) + ' ' + T('cur');

  function initialLang() {
    const q = new URLSearchParams(location.search).get('lang');
    if (LANGS.includes(q)) return q;
    const saved = store.get('ef_lang', null);
    if (LANGS.includes(saved)) return saved;
    const code = tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.language_code;
    return code && code.startsWith('ru') ? 'ru' : 'uz';
  }

  function initialTheme() {
    const saved = store.get('ef_theme', null);
    if (saved === 'light' || saved === 'dark') return saved;
    return tg && tg.colorScheme === 'light' ? 'light' : 'dark';
  }

  // ---------- holat ----------
  const state = {
    lang: initialLang(),
    shop: null,
    categories: [],
    products: new Map(),
    cart: store.get('ef_cart', []),
    kind: store.get('ef_kind', 'delivery'),
    payment: store.get('ef_payment', 'cash'),
    form: { name: '', phone: '', address: store.get('ef_address', ''), comment: '', lat: null, lon: null },
    view: 'home',
    activeCat: null,
    sheet: null,
    lastOrder: null,
    orders: null,
    sending: false,
    closedShown: false,
    verifiedPhone: '',
    phoneWaiting: false,
    banners: [],
    bannerIndex: 0,
    theme: initialTheme(),
    upsellAsked: false,
    errors: {},
  };

  // ---------- API ----------
  async function api(path, opts) {
    opts = opts || {};
    const headers = { 'Content-Type': 'application/json' };
    if (tg && tg.initData) headers.Authorization = 'tma ' + tg.initData;
    try {
      const res = await fetch(path, {
        method: opts.method || 'GET', headers, body: opts.body ? JSON.stringify(opts.body) : undefined,
      });
      const data = await res.json().catch(() => ({ ok: false, error: 'network' }));
      if (!res.ok && data.ok !== false) return { ok: false, error: 'network' };
      return data;
    } catch (e) {
      return { ok: false, error: 'network' };
    }
  }

  async function loadMenu() {
    const data = await api('api/menu?lang=' + state.lang);
    if (!data.ok) return false;
    state.shop = data.shop;
    state.categories = data.categories;
    state.banners = data.banners || [];
    state.products = new Map();
    data.categories.forEach((c) => c.products.forEach((p) => state.products.set(p.id, Object.assign({ cat: c.id }, p))));
    if (!state.activeCat && data.categories.length) state.activeCat = data.categories[0].id;
    // Savatdan mavjud bo'lmagan taomlarni olib tashlash
    state.cart = state.cart.filter((l) => {
      const p = state.products.get(l.id);
      return p && p.available && (l.size !== 'large' || p.price_large != null);
    });
    saveCart();
    return true;
  }

  async function loadMe() {
    if (!tg || !tg.initData) return;
    const data = await api('api/me', { method: 'POST', body: {} });
    if (data.ok) {
      state.form.name = state.form.name || data.user.name || '';
      state.verifiedPhone = data.user.verified_phone || '';
      state.form.phone = state.verifiedPhone || state.form.phone || data.user.phone || '';
      if (!new URLSearchParams(location.search).get('lang') && !store.get('ef_lang', null) && LANGS.includes(data.user.lang)) {
        state.lang = data.user.lang;
      }
    }
  }

  // ---------- savat ----------
  function saveCart() { store.set('ef_cart', state.cart); }
  const unitPrice = (p, size) => (size === 'large' ? p.price_large : p.price);
  function cartLines() {
    return state.cart.map((l) => {
      const p = state.products.get(l.id);
      return p ? { line: l, p, price: unitPrice(p, l.size), sum: unitPrice(p, l.size) * l.qty } : null;
    }).filter(Boolean);
  }
  const cartTotal = () => cartLines().reduce((s, x) => s + x.sum, 0);
  const cartCount = () => state.cart.reduce((s, l) => s + l.qty, 0);
  const qtyOf = (id) => state.cart.filter((l) => l.id === id).reduce((s, l) => s + l.qty, 0);

  function addToCart(id, size, qty) {
    const p = state.products.get(id);
    if (!p || !p.available) return;
    size = p.price_large != null ? (size || 'small') : 'small';
    const found = state.cart.find((l) => l.id === id && l.size === size);
    if (found) found.qty = Math.min(found.qty + qty, 50);
    else state.cart.push({ id, size, qty });
    saveCart();
    haptic('light');
  }
  function changeQty(index, delta) {
    const l = state.cart[index];
    if (!l) return;
    l.qty += delta;
    if (l.qty <= 0) state.cart.splice(index, 1);
    if (l.qty > 50) l.qty = 50;
    saveCart();
    haptic('light');
  }

  // ---------- umumiy bo'laklar ----------
  // Font Awesome yuklanmasa (internet yoki kit sozlamasi), oddiy belgilar ko'rsatiladi.
  const ICON_FALLBACK = {
    plus: '+', minus: '−', 'trash-can': '×', xmark: '×', check: '✓', 'circle-check': '✓', 'chevron-left': '‹',
    'arrow-right': '→', receipt: '≡', globe: '◍', 'rotate-right': '↻', copy: '⧉', moon: '☾', fire: '★',
    'location-dot': '•', sun: '☀',  'location-crosshairs': '◎', 'paper-plane': '➤', spinner: '…', 'person-walking': '',
    'truck-fast': '', phone: '☎', clock: '◷', store: '⌂', handshake: '',
  };
  const icon = (name, extra) => '<i class="fa-solid fa-' + name + (extra ? ' ' + extra : '') + '" data-fb="' +
    (ICON_FALLBACK[name] || '') + '" aria-hidden="true"></i>';
  function checkIcons() {
    const probe = document.createElement('i');
    probe.className = 'fa-solid fa-plus';
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    document.body.appendChild(probe);
    const before = getComputedStyle(probe, '::before').content;
    const ok = document.documentElement.classList.contains('fontawesome-i2svg-active') ||
      (before && before !== 'none' && before !== 'normal' && before !== '""');
    probe.remove();
    document.documentElement.classList.toggle('no-fa', !ok);
  }
  const img = (src, cls) => '<img src="' + esc(src) + '" alt="" loading="lazy" class="' + (isPhoto(src) ? 'photo ' : '') + (cls || '') + '">';

  function priceLabel(p) {
    if (!p.available) return '<span class="soon-label">' + T('soon') + '</span>';
    if (p.price_large != null) return '<span class="price">' + fmt(p.price) + ' <small>' + T('from') + '</small></span>';
    return '<span class="price">' + money(p.price) + '</span>';
  }
  function sizeNote(p) {
    if (!p.available) return T('price_soon');
    if (p.price_large != null) return T('small') + ' · ' + T('large');
    return esc(p.desc || '');
  }

  function backHeader(title, right) {
    return '<header class="page-head"><button class="back-btn" data-action="back" aria-label="' + T('back') + '">' +
      icon('chevron-left') + '</button><h1 class="display">' + title + '</h1>' + (right || '') + '</header>';
  }

  // ---------- ko'rinishlar ----------
  function renderHome() {
    const shop = state.shop;
    const open = shop.open;
    let html = '<header class="top"><div class="brand"><div class="logo"><img src="static/img/logo.webp" alt="Emir Food"></div><div>' +
      '<div class="brand-name">EMIR <span>FOOD</span></div><div class="brand-sub">' + icon('location-dot') + '<span>Peshku ·</span>' +
      (open ? '<span class="is-open">' + T('open_247') + '</span>' : '<span class="is-closed">' + T('closed_short') + '</span>') +
      '</div></div></div><div class="top-actions">' +
      '<button class="icon-btn" data-action="orders" aria-label="' + T('my_orders') + '">' + icon('receipt') + '</button>' +
      '<button class="icon-btn" data-action="theme" aria-label="' + T(state.theme === 'dark' ? 'theme_light' : 'theme_dark') + '">' +
      icon(state.theme === 'dark' ? 'sun' : 'moon') + '</button>' +
      '<button class="icon-btn" data-action="lang" aria-label="' + T('language') + '">' + LANG_SHORT[state.lang] + '</button>' +
      '</div></header>';

    html += '<section class="hero"><h1 class="display">' + T('hero_title') + '</h1><p>' + T('hero_sub') + '</p></section>';
    html += kindSwitch();
    html += renderBanners();

    html += '<div class="chips-wrap"><nav class="chips" aria-label="' + T('categories') + '">' + state.categories.map((c) =>
      '<button class="chip" data-action="cat" data-id="' + c.id + '" aria-current="' + (c.id === state.activeCat) + '">' +
      img(c.img) + esc(c.name) + '</button>').join('') + '</nav></div>';

    html += state.categories.map((c) => '<section class="section" id="cat-' + c.id + '" data-cat="' + c.id + '">' +
      '<div class="section-head"><h2 class="display">' + esc(c.name) + '</h2><span>' + T('n_items', { n: c.products.length }) + '</span></div>' +
      '<div class="grid">' + c.products.map(renderCard).join('') + '</div></section>').join('');

    html += '<div class="foot-info">' +
      '<div>' + icon('phone') + '<a href="tel:' + esc(shop.phone.replace(/\s/g, '')) + '">' + esc(shop.phone) + '</a></div>' +
      '<div>' + icon('location-dot') + '<span>' + esc(shop.address) + '</span></div>' +
      '<div>' + icon('truck-fast') + '<span>' + esc(shop.zone) + ' · ' + T('free_from', { min: fmt(shop.min_order) }) + '</span></div></div>';

    if (cartCount() > 0) {
      html += '<div class="bottom-bar' + (state.barShown ? '' : ' appear') + '" id="cart-bar"><button class="cta cart-bar" data-action="cart"><span class="info"><span>' +
        T('in_cart', { n: cartCount() }) + '</span><b>' + money(cartTotal()) + '</b></span><span class="go">' + T('cart') + ' ' +
        icon('arrow-right') + '</span></button></div>';
    }
    state.barShown = cartCount() > 0;
    return html;
  }

  // "Qazi xot-dog (katta)" -> nom + o'lcham belgisi
  const SIZE_WORDS = { kichik: 'small', 'кичик': 'small', 'маленький': 'small', katta: 'large', 'катта': 'large', 'большой': 'large' };
  function splitSize(name) {
    const m = /^(.*\S)\s*\(([^)]+)\)$/.exec(name || '');
    const kind = m && SIZE_WORDS[m[2].toLowerCase()];
    return kind ? { base: m[1], label: m[2], kind } : { base: name, label: '', kind: '' };
  }
  const sizeTag = (sz) => (sz.kind ? ' <span class="size-tag ' + sz.kind + '">' + esc(sz.label) + '</span>' : '');

  // ---------- banner karuseli ----------
  const SLIDE_MS = 5000;
  function renderBanners() {
    const list = state.banners;
    if (!list.length) return '';
    if (state.bannerIndex >= list.length) state.bannerIndex = 0;
    const slides = list.map((b, i) =>
      '<div class="slide ' + esc(b.theme) + (i === state.bannerIndex ? ' active' : '') + '" data-action="banner" data-i="' + i + '"' +
      ' role="group" aria-roledescription="slide" aria-label="' + (i + 1) + ' / ' + list.length + '">' +
      (b.img ? img(b.img) : '') +
      (b.tag ? '<span class="tag">' + esc(b.tag) + '</span>' : '') +
      '<div class="title">' + esc(b.title) + '</div>' +
      (b.text ? '<div class="sub">' + esc(b.text) + '</div>' : '') +
      (b.product_id ? '<span class="go">' + T('order_now') + ' ' + icon('arrow-right') + '</span>' : '') +
      '</div>').join('');
    const dots = list.length > 1 ? '<div class="dots" role="tablist">' + list.map((b, i) =>
      '<button class="timing" data-action="banner-dot" data-i="' + i + '" aria-label="' + (i + 1) + '" aria-current="' + (i === state.bannerIndex) + '"></button>').join('') + '</div>' : '';
    return '<section class="carousel" aria-roledescription="carousel" aria-label="' + T('news') + '"><div class="track" id="banner-track">' +
      slides + '</div>' + dots + '</section>';
  }

  let bannerTimer = null;
  let bannerPausedUntil = 0;
  let scrollTimer = null;
  function slideWidth(track) {
    const first = track.firstElementChild;
    return first ? first.getBoundingClientRect().width + 12 : track.clientWidth;
  }
  function setActiveSlide(i) {
    state.bannerIndex = i;
    document.querySelectorAll('#banner-track .slide').forEach((el, j) => el.classList.toggle('active', j === i));
    document.querySelectorAll('.dots button').forEach((el, j) => {
      el.setAttribute('aria-current', String(j === i));
      el.classList.remove('timing');
      if (j === i && Date.now() >= bannerPausedUntil) { void el.offsetWidth; el.classList.add('timing'); }
    });
  }
  function goSlide(i, smooth) {
    const track = document.getElementById('banner-track');
    if (!track) return;
    const n = state.banners.length;
    i = ((i % n) + n) % n;
    track.scrollTo({ left: i * slideWidth(track), behavior: smooth && !reducedMotion() ? 'smooth' : 'auto' });
    setActiveSlide(i);
  }
  function setupCarousel() {
    const track = document.getElementById('banner-track');
    if (!track) return;
    document.documentElement.style.setProperty('--slide-ms', SLIDE_MS + 'ms');
    track.scrollLeft = state.bannerIndex * slideWidth(track);
    const pause = () => {
      bannerPausedUntil = Date.now() + 7000;
      document.querySelectorAll('.dots button').forEach((el) => el.classList.remove('timing'));
    };
    track.addEventListener('pointerdown', pause, { passive: true });
    track.addEventListener('touchstart', pause, { passive: true });
    track.addEventListener('scroll', () => {
      clearTimeout(scrollTimer);
      scrollTimer = setTimeout(() => {
        const i = Math.round(track.scrollLeft / slideWidth(track));
        if (i !== state.bannerIndex) setActiveSlide(i);
      }, 90);
    }, { passive: true });
    clearInterval(bannerTimer);
    if (state.banners.length > 1) {
      bannerTimer = setInterval(() => {
        if (document.hidden || state.sheet || Date.now() < bannerPausedUntil) return;
        if (!document.getElementById('banner-track')) return;
        goSlide(state.bannerIndex + 1, true);
      }, SLIDE_MS);
    }
  }

  function renderCard(p) {
    const sz = splitSize(p.name);
    const q = qtyOf(p.id);
    return '<div class="card' + (p.available ? '' : ' soon') + (sz.kind === 'small' ? ' is-small' : '') + '" data-action="open" data-id="' + p.id + '" role="button" tabindex="0" aria-label="' + esc(p.name) + '">' +
      '<div class="card-img">' + img(p.img) +
      (p.hit ? '<span class="badge-hit">' + icon('fire') + ' HIT</span>' : '') +
      (q ? '<span class="badge-qty">' + q + '</span>' : '') + '</div>' +
      '<div class="card-name">' + esc(sz.base) + sizeTag(sz) + '</div><div class="card-note">' + sizeNote(p) + '</div>' +
      '<div class="card-foot">' + priceLabel(p) +
      (p.available ? '<button class="add-btn" data-action="quick-add" data-id="' + p.id + '" aria-label="' + T('add') + '">' + icon('plus') + '</button>' : '') +
      '</div></div>';
  }

  function kindSwitch() {
    return '<div class="seg" role="group" aria-label="' + T('order_type') + '">' +
      '<button data-action="kind" data-kind="delivery" aria-pressed="' + (state.kind === 'delivery') + '">' + icon('truck-fast') + ' ' + T('delivery') + '</button>' +
      '<button data-action="kind" data-kind="pickup" aria-pressed="' + (state.kind === 'pickup') + '">' + icon('person-walking') + ' ' + T('pickup') + '</button></div>';
  }

  function minInfo(total) {
    const min = state.shop.min_order;
    if (state.kind !== 'delivery' || !min) return '';
    if (total >= min) return '<div class="min-ok">' + icon('circle-check') + ' ' + T('min_ok', { min: fmt(min) }) + '</div>';
    const pct = Math.max(4, Math.round(total / min * 100));
    return '<div class="min-need"><span>' + T('min_need', { min: fmt(min), left: fmt(min - total) }) + '</span>' +
      '<div class="progress"><div style="width:' + pct + '%"></div></div></div>';
  }
  const minMet = (total) => state.kind !== 'delivery' || total >= state.shop.min_order;

  function renderCart() {
    const lines = cartLines();
    if (!lines.length) {
      return backHeader(T('cart')) + '<div class="empty"><img src="static/img/hotdog-classic.svg" alt=""><h2 class="display">' +
        T('cart_empty') + '</h2><p>' + T('cart_empty_sub') + '</p></div>' +
        '<div class="bottom-bar"><button class="cta" data-action="home">' + T('to_menu') + '</button></div>';
    }
    const total = cartTotal();
    let html = backHeader(T('cart'), '<button class="text-btn" data-action="clear">' + T('clear') + '</button>');
    html += '<div class="lines">' + lines.map((x, i) =>
      '<div class="line"><div class="line-img">' + img(x.p.img) + '</div><div class="line-info"><b>' + esc(x.p.name) + '</b><span>' +
      (x.p.price_large != null ? T(x.line.size === 'large' ? 'large' : 'small') + ' · ' : '') + money(x.price) + '</span><em>' + money(x.sum) + '</em></div>' +
      '<div class="stepper"><button data-action="dec" data-i="' + i + '" aria-label="' + T('less') + '">' + icon(x.line.qty === 1 ? 'trash-can' : 'minus') + '</button>' +
      '<output>' + x.line.qty + '</output><button class="plus" data-action="inc" data-i="' + i + '" aria-label="' + T('more') + '">' + icon('plus') + '</button></div></div>'
    ).join('') + '</div>';

    const inCart = new Set(state.cart.map((l) => l.id));
    const ups = Array.from(state.products.values()).filter((p) => p.available && !inCart.has(p.id))
      .sort((a, b) => (b.hit - a.hit) || (a.price - b.price)).slice(0, 8);
    if (ups.length) {
      html += '<div class="upsell"><h2>' + T('upsell_title') + '</h2><div class="upsell-row">' + ups.map((p) =>
        '<button class="mini" data-action="open" data-id="' + p.id + '">' + img(p.img) + '<b>' + esc(p.name) + '</b><div class="row"><span>' +
        fmt(p.price) + (p.price_large != null ? '+' : '') + '</span>' + icon('plus') + '</div></button>').join('') + '</div></div>';
    }

    html += kindSwitch();
    html += '<div class="summary"><div class="row"><span>' + T('items_n', { n: cartCount() }) + '</span><b>' + money(total) + '</b></div>' +
      '<div class="row"><span>' + T(state.kind === 'delivery' ? 'delivery' : 'pickup') + '</span><span class="free">' + T('free') + '</span></div>' +
      minInfo(total) + '<hr><div class="total"><span>' + T('total') + '</span><b>' + money(total) + '</b></div></div>';

    const closed = !state.shop.open;
    const ok = minMet(total) && !closed;
    html += '<div class="bottom-bar"><button class="cta" data-action="checkout"' + (ok ? '' : ' disabled') + '>' +
      (closed ? icon('moon') + ' ' + T('closed_short') : T('checkout') + ' ' + icon('arrow-right')) + '</button></div>';
    return html;
  }

  function renderCheckout() {
    const f = state.form;
    const er = state.errors;
    const total = cartTotal();
    let html = backHeader(T('checkout'));
    html += kindSwitch();
    html += '<div class="stack"><label class="field">' + T('your_name') +
      '<input class="input' + (er.name ? ' invalid' : '') + '" id="f-name" data-field="name" autocomplete="name" maxlength="64" value="' + esc(f.name) + '" placeholder="' + T('name_ph') + '"></label>' +
      phoneField(er) + '</div>';

    if (state.kind === 'delivery') {
      const hasLoc = f.lat != null;
      html += '<div class="stack"><span class="label">' + T('address_title') + '</span>' +
        '<button class="loc-btn' + (hasLoc ? ' done' : '') + '" data-action="location">' +
        icon(hasLoc ? 'circle-check' : 'location-crosshairs') + ' ' + T(hasLoc ? 'location_ok' : 'send_location') + '</button>' +
        '<textarea class="input' + (er.address ? ' invalid' : '') + '" rows="2" data-field="address" maxlength="300" aria-label="' + T('address_title') + '" placeholder="' + T('address_ph') + '">' + esc(f.address) + '</textarea>' +
        zoneHint() + '</div>';
    } else {
      html += '<div class="pickup-card"><div class="ico">' + icon('store') + '</div><div><b>Emir Food</b><span>' + esc(state.shop.address) + '</span></div></div>';
    }

    html += '<div class="stack"><span class="label">' + T('payment') + '</span>' +
      payBtn('cash', 'money-bill-wave', T('cash'), T('cash_sub')) +
      payBtn('card', 'credit-card', T('card'), T('card_sub')) +
      payBtn('later', 'handshake', T('later'), T('later_sub')) + '</div>';
    html += '<label class="field">' + T('comment') + '<input class="input" data-field="comment" maxlength="300" value="' + esc(f.comment) + '" placeholder="' + T('comment_ph') + '"></label>';
    html += '<div class="summary"><div class="row"><span>' + T('items_n', { n: cartCount() }) + '</span><b>' + money(total) + '</b></div>' +
      minInfo(total) + '</div>';

    const ok = minMet(total) && state.shop.open && total > 0 && !outOfZone();
    html += '<div class="bottom-bar"><button class="cta split" data-action="submit"' + (ok && !state.sending ? '' : ' disabled') + '><span>' +
      (state.sending ? icon('spinner', 'spin') + ' ' + T('sending') : T('place_order')) + '</span><span>' + money(total) + '</span></button></div>';
    return html;
  }

  // Telefon: Telegram'ning "kontaktni ulashish" oynasi orqali — shunda raqam haqiqiy bo'ladi.
  function zoneHint() {
    const z = zoneDistance();
    if (z && z.dist > z.radius) {
      return '<span class="hint bad">' + icon('triangle-exclamation') + ' ' +
        T('err_out_of_zone', { dist: z.dist.toFixed(1), radius: z.radius }) + '</span>';
    }
    if (z) return '<span class="hint good">' + icon('circle-check') + ' ' + T('zone_ok', { dist: z.dist.toFixed(1) }) + '</span>';
    return '<span class="hint">' + icon('circle-info') + ' ' + esc(state.shop.zone) + ' · ' + T('free') + '</span>';
  }

  function phoneField(er) {
    const label = '<span class="label">' + T('phone') + '</span>';
    if (!canRequestContact()) {
      return '<label class="field" for="f-phone">' + T('phone') + '</label>' +
        '<input class="input' + (er.phone ? ' invalid' : '') + '" id="f-phone" data-field="phone" type="tel" inputmode="tel" autocomplete="tel" maxlength="20" value="' + esc(state.form.phone) + '" placeholder="+998 __ ___ __ __">';
    }
    if (state.phoneWaiting) {
      return label + '<div class="phone-box">' + icon('spinner', 'spin') + '<span>' + T('waiting_phone') + '</span></div>';
    }
    if (state.verifiedPhone) {
      return label + '<div class="phone-box verified">' + icon('circle-check') + '<span><b>' + esc(state.verifiedPhone) + '</b><small>' +
        T('phone_verified') + '</small></span><button class="text-btn" data-action="contact">' + T('change') + '</button></div>';
    }
    return label + '<button class="loc-btn' + (er.phone ? ' invalid' : '') + '" data-action="contact">' + icon('paper-plane') + ' ' + T('share_phone') + '</button>' +
      '<span class="hint">' + T('share_phone_hint') + '</span>';
  }

  function zoneDistance() {
    const z = state.shop && state.shop.zone_area;
    const f = state.form;
    if (!z || f.lat == null) return null;
    const rad = (d) => d * Math.PI / 180;
    const a = Math.sin(rad(f.lat - z.lat) / 2) ** 2 + Math.cos(rad(z.lat)) * Math.cos(rad(f.lat)) * Math.sin(rad(f.lon - z.lon) / 2) ** 2;
    return { dist: 2 * 6371 * Math.asin(Math.sqrt(a)), radius: z.radius_km };
  }
  const outOfZone = () => {
    const z = zoneDistance();
    return state.kind === 'delivery' && !!z && z.dist > z.radius;
  };

  function payBtn(id, ico, title, sub) {
    return '<button class="pay" data-action="pay" data-pay="' + id + '" aria-pressed="' + (state.payment === id) + '"><span class="dot"></span>' +
      '<span class="txt"><b>' + title + '</b><span>' + sub + '</span></span>' + icon(ico) + '</button>';
  }

  function orderItems(o) {
    return o.items.map((i) => i.name + (i.size ? ' (' + T(i.size) + ')' : '') + ' ×' + i.qty).join(', ');
  }
  function orderDate(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + ' · ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function renderOrderList() {
    if (state.orders == null) return '<p class="hint">' + icon('spinner', 'spin') + ' ' + T('loading') + '</p>';
    if (!state.orders.length) return '<p class="hint">' + T('no_orders') + '</p>';
    return '<div class="lines">' + state.orders.map((o) =>
      '<div class="order"><div class="info"><div class="top-line"><b>№ ' + o.id + '</b><small>' + orderDate(o.created_at) + '</small>' +
      '<span class="status st-' + esc(o.status || 'new') + '">' + T('st_' + (o.status || 'new')) + '</span></div>' +
      '<span>' + esc(orderItems(o)) + '</span><em>' + money(o.total) + '</em></div>' +
      '<div class="order-btns">' +
      ((o.status || 'new') === 'new' ? '<button class="repeat-btn cancel" data-action="cancel-order" data-id="' + o.id + '">' + icon('xmark') + ' ' + T('cancel_order') + '</button>' : '') +
      '<button class="repeat-btn" data-action="repeat" data-id="' + o.id + '">' + icon('rotate-right') + ' ' + T('repeat') + '</button></div></div>'
    ).join('') + '</div>';
  }

  function renderSuccess() {
    const o = state.lastOrder;
    let html = '<div class="success"><div class="check"><div>' + icon('check') + '</div></div>' +
      '<h1 class="display">' + T('order_ok') + '</h1><p>' + T('order_no') + ' <b>№ ' + o.id + '</b> · ' + T('order_ok_sub') + '</p></div>';
    if ((o.payment === 'card' || o.payment === 'later') && state.shop.card_number) {
      const later = o.payment === 'later';
      html += '<div class="card-pay"><div class="head"><span>' + T(later ? 'pay_later_head' : 'pay_by_card') + '</span><b>' + money(o.total) + '</b></div>' +
        '<div class="card-num"><div><b>' + esc(state.shop.card_number) + '</b>' + (state.shop.card_owner ? '<span>' + esc(state.shop.card_owner) + '</span>' : '') + '</div>' +
        '<button class="copy-btn" data-action="copy">' + icon('copy') + ' ' + T('copy') + '</button></div>' +
        '<span class="hint">' + T(later ? 'later_hint' : 'send_receipt') + '</span></div>';
    }
    html += '<h2 class="display h2">' + T('my_orders') + '</h2>' + renderOrderList();
    html += '<div class="bottom-bar"><button class="cta" data-action="home">' + T('to_menu') + '</button></div>';
    return html;
  }

  function renderOrders() {
    return backHeader(T('my_orders')) + renderOrderList();
  }

  // ---------- pastki oynalar (sheet) ----------
  // animate=true — oyna birinchi marta ochilganda; keyingi qayta chizishlarda animatsiya takrorlanmaydi.
  function renderSheet(animate) {
    const s = state.sheet;
    if (!s) { sheetRoot.innerHTML = ''; return; }
    sheetRoot.className = animate ? '' : 'static';
    let inner = '';
    if (s.type === 'product') inner = productSheet(s);
    else if (s.type === 'lang') inner = langSheet();
    else if (s.type === 'closed') inner = closedSheet();
    else if (s.type === 'upsell') inner = upsellSheet();
    sheetRoot.innerHTML = '<div class="overlay" data-action="close-sheet"></div>' + inner;
  }

  function productSheet(s) {
    const p = state.products.get(s.id);
    if (!p) return '';
    const word = (p.name.split(' ')[0] || '').slice(0, 10);
    let html = '<div class="sheet" role="dialog" aria-modal="true" aria-label="' + esc(p.name) + '">' +
      '<div class="sheet-hero"><span class="word" aria-hidden="true">' + esc(word) + ' ' + esc(word) + '</span>' + img(p.img) +
      '<button class="sheet-close" data-action="close-sheet" aria-label="' + T('close') + '">' + icon('xmark') + '</button></div>' +
      '<div class="sheet-body">' +
      (p.hit ? '<div><span class="badge-hit" style="position:static;display:inline-flex">' + icon('fire') + ' HIT</span></div>' : '') +
      '<h2 class="display">' + esc(p.name) + '</h2>' + (p.desc ? '<p class="desc">' + esc(p.desc) + '</p>' : '');
    if (!p.available) {
      html += '<p class="desc">' + T('price_soon_long') + '</p></div></div>';
      return html;
    }
    if (p.price_large != null) {
      html += '<div class="stack"><span class="label">' + T('choose_size').toUpperCase() + '</span><div class="sizes">' +
        ['small', 'large'].map((sz) => '<button class="size" data-action="size" data-size="' + sz + '" aria-pressed="' + (s.size === sz) + '"><b>' +
          T(sz) + '</b><span>' + money(unitPrice(p, sz)) + '</span></button>').join('') + '</div></div>';
    }
    html += '<div class="qty-row"><span>' + T('qty') + '</span><div class="stepper">' +
      '<button data-action="sheet-dec" aria-label="' + T('less') + '">' + icon('minus') + '</button><output>' + s.qty + '</output>' +
      '<button class="plus" data-action="sheet-inc" aria-label="' + T('more') + '">' + icon('plus') + '</button></div></div>';

    const total = unitPrice(p, s.size) * s.qty;
    html += '</div></div><div class="bottom-bar sheet-bar"><button class="cta" data-action="sheet-add">' + T('add_to_cart') + ' · ' + money(total) + '</button></div>';
    return html;
  }

  function upsellProduct() {
    const up = state.shop && state.shop.upsell_id && state.products.get(state.shop.upsell_id);
    return up && up.available ? up : null;
  }

  function upsellSheet() {
    const up = upsellProduct();
    if (!up) return '';
    return '<div class="sheet small" role="dialog" aria-modal="true" aria-label="' + esc(T('upsell_q', { name: up.name })) + '"><div class="grabber"></div>' +
      '<div class="upsell-art">' + img(up.img) + '</div>' +
      '<h2 class="display">' + esc(T('upsell_q', { name: up.name })) + '</h2>' +
      '<div class="pill"><em>+' + money(up.price) + '</em></div>' +
      '<button class="cta" data-action="upsell-yes">' + icon('plus') + ' ' + T('upsell_yes') + '</button>' +
      '<button class="cta-outline" data-action="upsell-no">' + T('upsell_no') + '</button></div>';
  }

  function langSheet() {
    return '<div class="sheet small" role="dialog" aria-modal="true" aria-label="' + T('language') + '"><div class="grabber"></div>' +
      '<h2 class="display">' + T('language') + '</h2><div class="lang-list">' + LANGS.map((l) =>
        '<button data-action="set-lang" data-lang="' + l + '" aria-pressed="' + (l === state.lang) + '">' + LANG_LABEL[l] +
        (l === state.lang ? icon('check') : '') + '</button>').join('') + '</div></div>';
  }

  function closedSheet() {
    const until = state.shop.until;
    return '<div class="sheet small" role="dialog" aria-modal="true" aria-label="' + T('closed_title') + '"><div class="grabber"></div>' +
      '<div class="big-ico">' + icon('moon') + '</div><h2 class="display">' + T('closed_title') + '</h2>' +
      (until ? '<div class="pill">' + icon('clock') + '<span>' + T('until', { t: '<em>' + esc(until) + '</em>' }) + '</span></div>' : '') +
      '<p>' + T('closed_text') + '</p>' +
      '<button class="cta" data-action="close-sheet">' + T('see_menu') + '</button>' +
      '<a class="link-btn" href="tel:' + esc(state.shop.phone.replace(/\s/g, '')) + '">' + icon('phone') + ' ' + esc(state.shop.phone) + '</a></div>';
  }

  let closingTimer = null;
  function openSheet(sheet) {
    clearTimeout(closingTimer);
    state.sheet = sheet;
    renderSheet(true);
    document.body.style.overflow = 'hidden';
    syncBackButton();
    updateToTop();
  }
  function closeSheet(after) {
    state.sheet = null;
    document.body.style.overflow = '';
    syncBackButton();
    updateToTop();
    if (!sheetRoot.firstChild || reducedMotion()) {
      sheetRoot.innerHTML = '';
      if (after) after();
      return;
    }
    sheetRoot.className = 'closing';
    clearTimeout(closingTimer);
    closingTimer = setTimeout(() => {
      if (!state.sheet) { sheetRoot.innerHTML = ''; sheetRoot.className = ''; }
      if (after) after();
    }, 220);
  }
  const reducedMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------- render va navigatsiya ----------
  function render() {
    document.documentElement.lang = state.lang === 'ru' ? 'ru' : 'uz';
    const views = { home: renderHome, cart: renderCart, checkout: renderCheckout, success: renderSuccess, orders: renderOrders };
    app.innerHTML = (views[state.view] || renderHome)();
    syncBackButton();
    if (state.view === 'home') { observeSections(); setupCarousel(); }
    updateToTop();
  }

  // ---------- «Tepaga» tugmasi: pastga tushganda chiqadi, bosilsa boshiga qaytaradi ----------
  const toTop = document.getElementById('to-top');
  function updateToTop() {
    if (!toTop) return;
    const show = window.scrollY > Math.max(480, window.innerHeight * 0.8) && !state.sheet;
    toTop.classList.toggle('show', show);
    toTop.tabIndex = show ? 0 : -1;
    toTop.setAttribute('aria-label', T('to_top'));
    // Pastda savat/tugma paneli bo'lsa, uning ustida turadi
    toTop.classList.toggle('lifted', !!app.querySelector(':scope > .bottom-bar'));
  }
  let toTopRaf = 0;
  window.addEventListener('scroll', () => {
    if (toTopRaf) return;
    toTopRaf = requestAnimationFrame(() => { toTopRaf = 0; updateToTop(); });
  }, { passive: true });
  if (toTop) {
    toTop.addEventListener('click', () => {
      haptic('light');
      window.scrollTo({ top: 0, behavior: reducedMotion() ? 'auto' : 'smooth' });
    });
  }

  function go(view, isBack) {
    state.view = view;
    state.errors = {};
    app.classList.remove('enter-fwd', 'enter-back');
    render();
    window.scrollTo(0, 0);
    void app.offsetWidth; // animatsiyani qayta ishga tushirish
    app.classList.add(isBack ? 'enter-back' : 'enter-fwd');
  }

  function back() {
    if (state.sheet) return closeSheet();
    if (state.view === 'checkout') return go('cart', true);
    if (state.view !== 'home') return go('home', true);
  }

  function syncBackButton() {
    if (!tg || !tg.BackButton) return;
    if (state.sheet || state.view !== 'home') tg.BackButton.show(); else tg.BackButton.hide();
  }

  let sectionObserver = null;
  function observeSections() {
    if (sectionObserver) sectionObserver.disconnect();
    if (!('IntersectionObserver' in window)) return;
    sectionObserver = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        const id = Number(e.target.dataset.cat);
        if (id === state.activeCat) return;
        state.activeCat = id;
        document.querySelectorAll('.chip').forEach((c) => {
          const on = Number(c.dataset.id) === id;
          c.setAttribute('aria-current', String(on));
          if (on) c.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
        });
      });
    }, { rootMargin: '-80px 0px -65% 0px' });
    document.querySelectorAll('.section').forEach((s) => sectionObserver.observe(s));
  }

  let toastTimer = null;
  function toast(text, isError) {
    toastEl.textContent = text;
    toastEl.className = 'show' + (isError ? ' error' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.className = ''; }, 2600);
  }

  function popBadge(id) {
    const badge = document.querySelector('.card[data-id="' + id + '"] .badge-qty');
    if (badge) badge.classList.add('pop');
  }

  function bumpCart() {
    const bar = document.getElementById('cart-bar');
    if (bar) { bar.classList.remove('bump'); void bar.offsetWidth; bar.classList.add('bump'); }
  }

  // ---------- Telegram imkoniyatlari ----------
  function canRequestContact() {
    return !!(tg && tg.requestContact && tg.isVersionAtLeast && tg.isVersionAtLeast('6.9'));
  }

  function requestContact() {
    tg.requestContact((ok) => {
      if (!ok) { toast(T('err_phone_share'), true); return; }
      // Raqam botga kontakt sifatida keladi; server uni saqlaguncha kutamiz.
      state.phoneWaiting = true;
      render();
      waitVerifiedPhone(0);
    });
  }

  async function waitVerifiedPhone(attempt) {
    const data = await api('api/me', { method: 'POST', body: {} });
    const phone = data.ok && data.user.verified_phone;
    if (phone && (phone !== state.verifiedPhone || attempt >= 3)) {
      state.verifiedPhone = phone;
      state.form.phone = phone;
      state.phoneWaiting = false;
      state.errors.phone = false;
      haptic('ok');
      render();
      return;
    }
    if (attempt < 14) { setTimeout(() => waitVerifiedPhone(attempt + 1), 700); return; }
    state.phoneWaiting = false;
    render();
    toast(T('err_phone_wait'), true);
  }

  function setLocation(lat, lon) {
    state.form.lat = lat;
    state.form.lon = lon;
    state.errors.address = false;
    haptic('ok');
    render();
  }

  function browserLocation() {
    if (!navigator.geolocation) { toast(T('location_fail'), true); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => setLocation(pos.coords.latitude, pos.coords.longitude),
      () => toast(T('location_fail'), true),
      { enableHighAccuracy: true, timeout: 15000 }
    );
  }

  function requestLocation() {
    const lm = tg && tg.LocationManager;
    if (lm && tg.isVersionAtLeast && tg.isVersionAtLeast('8.0')) {
      const ask = () => {
        if (!lm.isLocationAvailable) { browserLocation(); return; }
        lm.getLocation((data) => {
          if (data) setLocation(data.latitude, data.longitude);
          else if (!lm.isAccessGranted && lm.openSettings) { toast(T('location_denied'), true); lm.openSettings(); }
          else toast(T('location_fail'), true);
        });
      };
      if (lm.isInited) ask(); else lm.init(ask);
      return;
    }
    browserLocation();
  }

  function copyCard() {
    const value = (state.shop.card_number || '').replace(/\s/g, '');
    const done = () => { toast(T('copied')); haptic('ok'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(done, () => fallbackCopy(value, done));
    } else fallbackCopy(value, done);
  }
  function fallbackCopy(value, done) {
    const ta = document.createElement('textarea');
    ta.value = value;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch (e) { toast(value); }
    ta.remove();
  }

  // ---------- buyurtma yuborish ----------
  function validate() {
    const f = state.form;
    const errors = {};
    if (!f.name.trim()) errors.name = T('err_name');
    if (canRequestContact()) {
      if (!state.verifiedPhone) errors.phone = T('err_phone_share');
    } else if (f.phone.replace(/\D/g, '').length < 9) errors.phone = T('err_phone');
    if (state.kind === 'delivery' && !f.address.trim() && f.lat == null) errors.address = T('err_address');
    state.errors = errors;
    return Object.values(errors)[0] || null;
  }

  async function submitOrder() {
    if (state.sending) return;
    if (!tg || !tg.initData) { toast(T('open_in_tg'), true); return; }
    const err = validate();
    if (err) { render(); toast(err, true); haptic('error'); return; }
    // Savatda fri bo'lmasa — buyurtmadan oldin bir marta taklif qilinadi.
    const up = upsellProduct();
    if (up && !state.upsellAsked && !state.cart.some((l) => l.id === up.id)) {
      state.upsellAsked = true;
      openSheet({ type: 'upsell' });
      return;
    }
    state.sending = true;
    render();
    const f = state.form;
    const res = await api('api/order', {
      method: 'POST',
      body: {
        lang: state.lang, kind: state.kind, payment: state.payment,
        name: f.name.trim(), phone: canRequestContact() ? state.verifiedPhone : f.phone.trim(),
        contact_supported: canRequestContact(),
        address: state.kind === 'delivery' ? f.address.trim() : '',
        lat: state.kind === 'delivery' ? f.lat : null, lon: state.kind === 'delivery' ? f.lon : null,
        comment: f.comment.trim(),
        items: state.cart.map((l) => ({ id: l.id, size: l.size, qty: l.qty })),
      },
    });
    state.sending = false;
    if (res.ok) {
      state.lastOrder = res.order;
      state.upsellAsked = false;
      state.cart = [];
      saveCart();
      store.set('ef_address', f.address);
      f.comment = '';
      haptic('ok');
      state.orders = null;
      go('success');
      loadOrders();
      return;
    }
    haptic('error');
    if (res.error === 'closed') { await loadMenu(); state.shop.open = false; }
    if (res.error === 'unavailable') { await loadMenu(); }
    render();
    toast(errorText(res), true);
  }

  function errorText(res) {
    switch (res.error) {
      case 'closed': return T('err_closed');
      case 'min_order': return T('min_need', { min: fmt(res.min_order || 0), left: fmt((res.min_order || 0) - cartTotal()) });
      case 'unavailable': return T('err_unavailable');
      case 'phone_invalid': return T('err_phone');
      case 'phone_unverified': state.verifiedPhone = ''; return T('err_phone_share');
      case 'out_of_zone': return T('err_out_of_zone', { dist: Number(res.distance_km).toFixed(1), radius: res.radius_km });
      case 'name_required': return T('err_name');
      case 'address_required': return T('err_address');
      case 'too_fast': return T('err_too_fast');
      case 'auth': return T('open_in_tg');
      case 'network': return T('err_network');
      default: return T('err_generic');
    }
  }

  async function loadOrders() {
    if (!tg || !tg.initData) { state.orders = []; render(); return; }
    const res = await api('api/orders?lang=' + state.lang);
    state.orders = res.ok ? res.orders : [];
    if (state.view === 'orders' || state.view === 'success') render();
  }

  function repeatOrder(id) {
    const o = (state.orders || []).find((x) => x.id === id);
    if (!o) return;
    let added = 0;
    o.items.forEach((i) => {
      const p = state.products.get(i.id);
      const sizeOk = i.size !== 'large' || (p && p.price_large != null);
      if (p && p.available && sizeOk) { addToCart(i.id, i.size === 'large' ? 'large' : 'small', i.qty); added += 1; }
    });
    if (added < o.items.length) toast(T('repeat_partial'));
    go('cart');
  }

  function confirmDialog(text, cb) {
    if (tg && tg.showConfirm && tg.isVersionAtLeast && tg.isVersionAtLeast('6.2')) tg.showConfirm(text, cb);
    else cb(window.confirm(text));
  }

  function askCancel(id) {
    confirmDialog(T('cancel_confirm', { id }), async (yes) => {
      if (!yes) return;
      const res = await api('api/orders/' + id + '/cancel?lang=' + state.lang, { method: 'POST', body: {} });
      const fresh = res.order;
      if (fresh && state.orders) state.orders = state.orders.map((o) => (o.id === fresh.id ? fresh : o));
      if (state.lastOrder && fresh && state.lastOrder.id === fresh.id) state.lastOrder = fresh;
      render();
      if (res.ok) { haptic('ok'); toast(T('canceled_ok')); }
      else if (res.error === 'cannot_cancel' && fresh && fresh.status === 'accepted') {
        haptic('error'); toast(T('err_cannot_cancel', { phone: state.shop.phone }), true);
      } else if (res.error !== 'cannot_cancel') { toast(errorText(res), true); }
    });
  }

  async function setLang(lang) {
    if (!LANGS.includes(lang)) return;
    state.lang = lang;
    store.set('ef_lang', lang);
    closeSheet();
    if (tg && tg.initData) api('api/lang', { method: 'POST', body: { lang } });
    await loadMenu();
    state.orders = null;
    render();
  }

  // ---------- hodisalar ----------
  function handleAction(el) {
    const action = el.dataset.action;
    const id = el.dataset.id ? Number(el.dataset.id) : null;
    switch (action) {
      case 'back': back(); break;
      case 'home': go('home', true); break;
      case 'cart': go('cart'); break;
      case 'orders': state.orders = null; go('orders'); loadOrders(); break;
      case 'lang': openSheet({ type: 'lang' }); break;
      case 'theme':
        state.theme = state.theme === 'dark' ? 'light' : 'dark';
        store.set('ef_theme', state.theme);
        applyTheme();
        haptic('light');
        render();
        break;
      case 'banner': {
        const b = state.banners[Number(el.dataset.i)];
        const p = b && b.product_id && state.products.get(b.product_id);
        if (p) openSheet({ type: 'product', id: p.id, size: p.price_large != null ? 'large' : 'small', qty: 1 });
        break;
      }
      case 'banner-dot':
        bannerPausedUntil = Date.now() + 7000;
        goSlide(Number(el.dataset.i), true);
        break;
      case 'set-lang': setLang(el.dataset.lang); break;
      case 'close-sheet': closeSheet(); break;
      case 'kind':
        state.kind = el.dataset.kind;
        store.set('ef_kind', state.kind);
        haptic('light');
        render();
        break;
      case 'cat': {
        const sec = document.getElementById('cat-' + id);
        if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
        break;
      }
      case 'open': {
        const p = state.products.get(id);
        if (p) openSheet({ type: 'product', id, size: p.price_large != null ? 'large' : 'small', qty: 1 });
        break;
      }
      case 'quick-add': {
        const p = state.products.get(id);
        if (!p) break;
        if (p.price_large != null) { openSheet({ type: 'product', id, size: 'large', qty: 1 }); break; }
        addToCart(id, 'small', 1);
        render();
        bumpCart();
        popBadge(id);
        toast(T('added', { name: p.name }));
        break;
      }
      case 'size': state.sheet.size = el.dataset.size; haptic('light'); renderSheet(false); break;
      case 'sheet-inc': state.sheet.qty = Math.min(state.sheet.qty + 1, 50); haptic('light'); renderSheet(false); break;
      case 'sheet-dec': state.sheet.qty = Math.max(state.sheet.qty - 1, 1); haptic('light'); renderSheet(false); break;
      case 'sheet-add': {
        const s = state.sheet;
        const p = state.products.get(s.id);
        addToCart(s.id, s.size, s.qty);
        closeSheet();
        render();
        bumpCart();
        popBadge(s.id);
        toast(T('added', { name: p ? p.name : '' }));
        break;
      }
      case 'inc': changeQty(Number(el.dataset.i), 1); render(); break;
      case 'dec': changeQty(Number(el.dataset.i), -1); render(); break;
      case 'clear': state.cart = []; saveCart(); render(); break;
      case 'checkout': go('checkout'); break;
      case 'pay': state.payment = el.dataset.pay; store.set('ef_payment', state.payment); render(); break;
      case 'contact': requestContact(); break;
      case 'location': requestLocation(); break;
      case 'submit': submitOrder(); break;
      case 'upsell-yes': {
        const up = upsellProduct();
        if (up) addToCart(up.id, 'small', 1);
        closeSheet(() => { render(); submitOrder(); });
        break;
      }
      case 'upsell-no': closeSheet(() => submitOrder()); break;
      case 'copy': copyCard(); break;
      case 'repeat': repeatOrder(id); break;
      case 'cancel-order': askCancel(id); break;
      default: break;
    }
  }

  function onClick(e) {
    const el = e.target.closest('[data-action]');
    if (!el || el.disabled) return;
    if (el.dataset.action === 'open' && e.target.closest('[data-action="quick-add"]')) return;
    e.preventDefault();
    handleAction(el);
  }
  app.addEventListener('click', onClick);
  sheetRoot.addEventListener('click', onClick);
  app.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.card[data-action]')) { e.preventDefault(); handleAction(e.target); }
  });
  app.addEventListener('input', (e) => {
    const field = e.target.dataset && e.target.dataset.field;
    if (!field) return;
    state.form[field] = e.target.value;
    if (state.errors[field]) { state.errors[field] = false; e.target.classList.remove('invalid'); }
  });

  // ---------- kunduzgi / tungi rejim ----------
  function applyTheme() {
    document.documentElement.setAttribute('data-theme', state.theme);
    const bg = state.theme === 'light' ? '#F7F2EA' : '#121110';
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', bg);
    if (!tg) return;
    try {
      tg.setHeaderColor(bg);
      tg.setBackgroundColor(bg);
      if (tg.isVersionAtLeast('7.10')) tg.setBottomBarColor(bg);
    } catch (e) { /* eski versiyalar */ }
  }

  // ---------- ishga tushirish ----------
  async function boot() {
    applyTheme();
    if (tg) {
      tg.ready();
      tg.expand();
      try {
        if (tg.isVersionAtLeast('7.7')) tg.disableVerticalSwipes();
      } catch (e) { /* eski versiyalar */ }
      tg.BackButton.onClick(back);
    }
    await loadMe();
    const ok = await loadMenu();
    if (!ok) {
      app.innerHTML = '<div class="empty"><img class="empty-logo" src="static/img/logo.webp" alt="Emir Food"><h2 class="display">' + T('err_network') +
        '</h2><button class="cta" style="max-width:260px" onclick="location.reload()">' + T('retry') + '</button></div>';
      return;
    }
    render();
    setTimeout(checkIcons, 2500);
    if (!state.shop.open && !state.closedShown) {
      state.closedShown = true;
      openSheet({ type: 'closed' });
    }
  }

  boot();
})();
