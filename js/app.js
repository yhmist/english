const DEFAULT_SLUG = 'introducing-yourself-and-others';
const PLAY_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z"/></svg>';

/** Project Pages live at /repo-name/; local / custom domain use ''. */
const BASE = (() => {
  if (!location.hostname.endsWith('github.io')) return '';
  const first = location.pathname.split('/').filter(Boolean)[0];
  return first ? `/${first}` : '';
})();

function url(path) {
  return `${BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

const catalogueEl = document.getElementById('catalogue');
const contentEl = document.getElementById('content');
const audioEl = document.getElementById('audio');
const menuBtn = document.getElementById('menu-btn');
const iconMenu = document.getElementById('icon-menu');
const iconClose = document.getElementById('icon-close');
const homeLink = document.getElementById('home-link');
const popupEl = document.getElementById('word-popup');
const popupWordEl = document.getElementById('word-popup-word');
const popupZhEl = document.getElementById('word-popup-zh');

let corpus = [];
let timings = {};
let usVoice = null;
const translationCache = new Map();

function stripBase(pathname) {
  if (BASE && pathname.startsWith(BASE)) {
    const rest = pathname.slice(BASE.length);
    return rest.startsWith('/') ? rest : `/${rest}`;
  }
  return pathname;
}

function getSlugFromPath() {
  const path = stripBase(window.location.pathname).replace(/\/+$/, '') || '/';
  return path === '/' ? DEFAULT_SLUG : path.slice(1).split('/')[0];
}

function findChapter(slug) {
  return corpus.find((c) => c.href === slug) ?? corpus[0];
}

function loadVoices() {
  const voices = speechSynthesis.getVoices();
  usVoice =
    voices.find((v) => v.lang === 'en-US' && /google|microsoft|samantha|aria|jenny/i.test(v.name)) ||
    voices.find((v) => v.lang === 'en-US') ||
    voices.find((v) => v.lang.startsWith('en')) ||
    null;
}

if ('speechSynthesis' in window) {
  loadVoices();
  speechSynthesis.addEventListener('voiceschanged', loadVoices);
}

function speakWord(word) {
  if (!('speechSynthesis' in window)) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(word);
  utter.lang = 'en-US';
  if (usVoice) utter.voice = usVoice;
  utter.rate = 0.95;
  speechSynthesis.speak(utter);
}

async function translateWord(word) {
  const key = word.toLowerCase();
  if (translationCache.has(key)) return translationCache.get(key);

  try {
    const res = await fetch(
      `https://api.mymemory.translated.net/get?q=${encodeURIComponent(key)}&langpair=en|zh-CN`
    );
    if (!res.ok) throw new Error('translate failed');
    const data = await res.json();
    const text = data?.responseData?.translatedText?.trim();
    const result = text && text.toLowerCase() !== key ? text : '暂无翻译';
    translationCache.set(key, result);
    return result;
  } catch {
    translationCache.set(key, '暂无翻译');
    return '暂无翻译';
  }
}

function positionPopup(anchor) {
  const rect = anchor.getBoundingClientRect();
  const pad = 8;
  popupEl.classList.remove('hidden');

  let left = rect.left;
  let top = rect.bottom + pad;
  const { width, height } = popupEl.getBoundingClientRect();

  if (left + width > window.innerWidth - pad) left = window.innerWidth - width - pad;
  if (left < pad) left = pad;
  if (top + height > window.innerHeight - pad) top = rect.top - height - pad;

  popupEl.style.left = `${left}px`;
  popupEl.style.top = `${top}px`;
}

function hidePopup() {
  popupEl.classList.add('hidden');
}

async function onWordClick(event, word) {
  event.stopPropagation();
  const cleaned = word.replace(/^[^a-zA-Z']+|[^a-zA-Z']+$/g, '');
  if (!cleaned) return;

  speakWord(cleaned);
  popupWordEl.textContent = cleaned;
  popupZhEl.textContent = '加载中…';
  positionPopup(event.currentTarget);

  const zh = await translateWord(cleaned);
  if (popupWordEl.textContent === cleaned) {
    popupZhEl.textContent = zh;
    positionPopup(event.currentTarget);
  }
}

function renderEnglishLine(text) {
  const p = document.createElement('p');
  p.className = 'en';

  const speakerMatch = text.match(/^([A-Z][A-Za-z. ]{0,30}?):\s*/);
  let rest = text;
  if (speakerMatch) {
    const speaker = document.createElement('span');
    speaker.className = 'speaker';
    speaker.textContent = speakerMatch[0];
    p.appendChild(speaker);
    rest = text.slice(speakerMatch[0].length);
  }

  for (const part of rest.split(/([a-zA-Z]+(?:['’][a-zA-Z]+)?)/)) {
    if (!part) continue;
    if (/^[a-zA-Z]/.test(part)) {
      const span = document.createElement('span');
      span.className = 'word';
      span.textContent = part;
      span.addEventListener('click', (e) => onWordClick(e, part));
      p.appendChild(span);
    } else {
      p.appendChild(document.createTextNode(part));
    }
  }

  return p;
}

function ensureAudio(title) {
  const path = url(`/pmp_audios/${title}.mp3`);
  if (audioEl.getAttribute('src') !== path) audioEl.src = path;
  audioEl.classList.add('visible');
}

function seekToSentence(title, index) {
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  ensureAudio(title);

  const starts = timings[title];
  const start =
    Array.isArray(starts) && Number.isFinite(starts[index])
      ? Math.max(0, starts[index] - 0.05)
      : 0;

  const doSeek = () => {
    if (!Number.isFinite(audioEl.duration) || audioEl.duration <= 0) return;
    audioEl.currentTime = Math.min(audioEl.duration - 0.05, start);
    audioEl.play().catch(() => {});
  };

  if (Number.isFinite(audioEl.duration) && audioEl.duration > 0) doSeek();
  else audioEl.addEventListener('loadedmetadata', doSeek, { once: true });
}

function setActiveLine(lineEl) {
  contentEl.querySelectorAll('.line.active').forEach((el) => el.classList.remove('active'));
  lineEl.classList.add('active');
}

function setMenuOpen(open) {
  catalogueEl.classList.toggle('open', open);
  menuBtn.setAttribute('aria-expanded', String(open));
  iconMenu.classList.toggle('hidden', open);
  iconClose.classList.toggle('hidden', !open);
}

function renderCatalogue(activeSlug) {
  const frag = document.createDocumentFragment();
  const heading = document.createElement('div');
  heading.className = 'catalogue-heading';
  heading.textContent = 'Catalogue';
  frag.appendChild(heading);

  for (const { topic, href } of corpus) {
    const a = document.createElement('a');
    a.href = url(`/${href}`);
    a.textContent = topic;
    if (href === activeSlug) a.classList.add('active');
    a.addEventListener('click', (e) => {
      e.preventDefault();
      navigate(url(`/${href}`));
      setMenuOpen(false);
    });
    frag.appendChild(a);
  }

  catalogueEl.replaceChildren(frag);
}

function renderContent(chapter) {
  const frag = document.createDocumentFragment();

  for (const { title, content } of chapter.conversation) {
    const playBtn = document.createElement('button');
    playBtn.type = 'button';
    playBtn.className = 'play-btn';
    playBtn.setAttribute('aria-label', `Play ${title}`);
    playBtn.innerHTML = PLAY_ICON;
    playBtn.addEventListener('click', () => {
      ensureAudio(title);
      audioEl.currentTime = 0;
      audioEl.play().catch(() => {});
    });

    const sectionTitle = document.createElement('div');
    sectionTitle.className = 'section-title';
    sectionTitle.textContent = title;

    const lines = document.createElement('div');
    lines.className = 'lines';

    let lineIndex = 0;
    for (const item of content) {
      if (item.sign) {
        const span = document.createElement('span');
        span.className = 'sign';
        span.textContent = item.text;
        lines.appendChild(span);
        continue;
      }

      const index = lineIndex++;
      const div = document.createElement('div');
      div.className = 'line';
      div.title = '点击单词查词发音；点击句子跳转录音';

      const en = renderEnglishLine(item.text);
      const zh = document.createElement('p');
      zh.className = 'zh';
      zh.textContent = item.Chinese;

      div.addEventListener('click', () => {
        setActiveLine(div);
        seekToSentence(title, index);
      });

      div.append(en, zh);
      lines.appendChild(div);
    }

    frag.append(playBtn, sectionTitle, lines);
  }

  contentEl.replaceChildren(frag);
  hidePopup();
}

function navigate(path) {
  history.pushState(null, '', path);
  render();
}

function render() {
  const slug = getSlugFromPath();
  const chapter = findChapter(slug);
  const activeSlug = chapter.href;
  const current = stripBase(window.location.pathname).replace(/\/+$/, '') || '/';

  if (
    (current === '/' || !corpus.some((c) => c.href === slug)) &&
    current !== `/${activeSlug}`
  ) {
    history.replaceState(null, '', url(`/${activeSlug}`));
  }

  renderCatalogue(activeSlug);
  renderContent(chapter);
  document.title = `${chapter.topic} · Practice Makes Perfect`;
}

menuBtn.addEventListener('click', () => {
  setMenuOpen(!catalogueEl.classList.contains('open'));
});

homeLink.addEventListener('click', (e) => {
  e.preventDefault();
  navigate(url(`/${DEFAULT_SLUG}`));
  setMenuOpen(false);
});

window.addEventListener('popstate', render);

document.addEventListener('click', (event) => {
  if (!popupEl.classList.contains('hidden') && !event.target.closest('.word')) hidePopup();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') hidePopup();
  if (event.key !== ' ') return;
  if (!audioEl.src) return;
  const tag = event.target?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || event.target?.isContentEditable) return;
  event.preventDefault();
  if (audioEl.paused) audioEl.play().catch(() => {});
  else audioEl.pause();
});

async function init() {
  const [corpusRes, timingsRes] = await Promise.all([
    fetch(url('/data/corpus.json')),
    fetch(url('/data/timings.json')),
  ]);
  corpus = await corpusRes.json();
  timings = timingsRes.ok ? await timingsRes.json() : {};
  render();
}

init();
