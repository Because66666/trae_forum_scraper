const state = {
  posts: [],
  orderedIds: [],
  currentIndex: 0,
  enteredAt: 0,
  lastActivityAt: performance.now(),
  interactions: loadInteractions(),
  activeTagFilter: null,
  recommendationCursor: 0,
  randomCursor: 0,
  shownIds: new Set(),
  historyIds: [],
  historyPointer: -1,
  lastRecommendation: null,
  isTransitioning: false,
};

const feed = document.querySelector('#feed');
const template = document.querySelector('#postTemplate');
const nextBtn = document.querySelector('#nextBtn');
const prevBtn = document.querySelector('#prevBtn');
const resetBtn = document.querySelector('#resetBtn');

init();

async function init() {
  try {
    const response = await fetch('data/posts.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`无法读取 data/posts.json：${response.status}`);
    state.posts = await response.json();
  } catch (error) {
    renderEmpty(`还没有可展示的数据。请先运行爬虫，再执行 python build_app_data.py。${error.message}`);
    return;
  }

  if (!Array.isArray(state.posts) || state.posts.length === 0) {
    renderEmpty('posts.json 为空。请先抓取一些产品帖。');
    return;
  }

  reorderFeed();
  const firstIndex = randomInteger(state.posts.length);
  state.currentIndex = firstIndex;
  showPost(firstIndex, { reason: 'initial_random', direction: 1, sequence: 1 });
  bindEvents();
}

function bindEvents() {
  nextBtn.addEventListener('click', () => move(1, 'manual_next'));
  prevBtn.addEventListener('click', () => move(-1, 'manual_prev'));
  resetBtn.addEventListener('click', resetProfile);
  feed.addEventListener('wheel', handleWheel, { passive: false });
  feed.addEventListener('keydown', handleKeys);
  for (const eventName of ['pointerdown', 'keydown', 'wheel', 'touchstart']) {
    window.addEventListener(eventName, markActivity, { passive: true });
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) commitDwell('hidden');
    else markActivity();
  });
  bindTouch();
}

let wheelLock = false;
function handleWheel(event) {
  event.preventDefault();
  if (wheelLock) return;
  wheelLock = true;
  move(event.deltaY > 0 ? 1 : -1, 'wheel');
  setTimeout(() => { wheelLock = false; }, 720);
}

function handleKeys(event) {
  if (['ArrowDown', 'PageDown', ' '].includes(event.key)) {
    event.preventDefault();
    move(1, 'keyboard');
  }
  if (['ArrowUp', 'PageUp'].includes(event.key)) {
    event.preventDefault();
    move(-1, 'keyboard');
  }
}

function bindTouch() {
  let startY = 0;
  feed.addEventListener('touchstart', event => {
    startY = event.touches[0].clientY;
  }, { passive: true });
  feed.addEventListener('touchend', event => {
    const endY = event.changedTouches[0].clientY;
    const delta = startY - endY;
    if (Math.abs(delta) > 48) move(delta > 0 ? 1 : -1, 'touch');
  }, { passive: true });
}

function move(direction, source) {
  if (!state.orderedIds.length || state.isTransitioning) return;
  markActivity();
  commitDwell(source);
  const next = direction > 0 ? pickNextRecommendation() : pickHistoryPrevious();
  if (!next) return;
  transitionToPost(next.index, { ...next, direction, source });
}

function transitionToPost(index, detail) {
  const current = feed.querySelector('.post-card');
  if (!current) {
    showPost(index, detail);
    return;
  }
  state.isTransitioning = true;
  current.classList.remove('enter');
  current.classList.add(detail.direction > 0 ? 'exit-up' : 'exit-down');
  window.setTimeout(() => {
    showPost(index, detail);
    state.isTransitioning = false;
  }, 260);
}

function showPost(index, detail = {}) {
  state.currentIndex = clamp(index, 0, state.posts.length - 1);
  state.enteredAt = performance.now();
  state.lastActivityAt = state.enteredAt;
  const post = getCurrentPost();
  feed.innerHTML = '';
  const node = template.content.firstElementChild.cloneNode(true);
  fillPost(node, post);
  feed.appendChild(node);
  requestAnimationFrame(() => node.classList.add('enter'));
  feed.focus({ preventScroll: true });
  state.shownIds.add(post.topic_id);
  logRecommendation(post, detail);
  preloadNextImage();
}

function fillPost(node, post) {
  const imageStage = node.querySelector('.image-stage');
  const image = pickImage(post);
  if (image) {
    const img = document.createElement('img');
    img.src = image;
    img.alt = post.title || '项目截图';
    img.width = 1280;
    img.height = 720;
    img.decoding = 'async';
    img.fetchPriority = 'high';
    imageStage.appendChild(img);
  } else {
    imageStage.classList.add('no-image');
    imageStage.dataset.initial = String(post.title || 'PD').slice(0, 2);
  }

  const tagRow = node.querySelector('.tag-row');
  const tags = buildDisplayTags(post);
  tagRow.innerHTML = tags.map(tag => `<span>${escapeHtml(tag)}</span>`).join('');
  const title = node.querySelector('h2');
  title.textContent = post.title || '未命名项目';
  title.title = post.title || '未命名项目';
  node.querySelector('.meta').textContent = `${post.author || '匿名'} · ${formatDate(post.created_at)} · #${post.topic_id}`;
  node.querySelector('.summary').textContent = compactText(extractDemoIntro(post), 260);
  node.querySelector('.stat-row').innerHTML = [
    `浏览 ${formatNumber(post.views || 0)}`,
    `点赞 ${formatNumber(post.like_count || 0)}`,
    `投票 ${formatNumber(post.vote_count || 0)}`,
    `回复 ${formatNumber(post.reply_count || 0)}`,
  ].map(item => `<span>${item}</span>`).join('');

  const openLink = node.querySelector('.open-link');
  openLink.href = post.url;
  openLink.addEventListener('click', () => {
    recordAction(post, 'open', 30, { forceActive: true });
    commitDwell('open_link', { forceActive: true });
    pushLog(`跳转查看：${post.title}`);
  });

  node.querySelector('.interest-btn').addEventListener('click', () => {
    recordAction(post, 'like', 18, { forceActive: true });
    pushLog(`喜欢：${post.title}`);
    reorderFeed({ keepCurrent: true });
    preloadNextImage();
  });
}

function pickNextRecommendation() {
  reorderFeed({ keepCurrent: true });
  const sequence = state.shownIds.size + 1;
  const useRandom = shouldUseRandomRecommendation(sequence);
  const index = useRandom ? pickRandomIndex() : pickInterestIndex();
  return {
    index,
    reason: useRandom ? 'random' : 'interest',
    sequence,
  };
}

function pickHistoryPrevious() {
  if (state.historyPointer <= 0) return null;
  state.historyPointer -= 1;
  const topicId = state.historyIds[state.historyPointer];
  return {
    index: getPostIndexById(topicId),
    reason: 'history_previous',
    sequence: state.historyPointer + 1,
  };
}

function shouldUseRandomRecommendation(sequence) {
  if (sequence <= 20) return true;
  return sequence % 10 === 0;
}

function pickInterestIndex() {
  const index = state.recommendationCursor % state.orderedIds.length;
  state.recommendationCursor += 1;
  return getPostIndexById(state.orderedIds[index]);
}

function pickRandomIndex() {
  const unseen = state.posts.map((post, index) => ({ post, index })).filter(item => !state.shownIds.has(item.post.topic_id));
  if (!unseen.length) return randomInteger(state.posts.length);
  return unseen[randomInteger(unseen.length)].index;
}

function preloadNextImage() {
  const next = peekNextRecommendation();
  const post = state.posts[next.index];
  const src = post ? pickImage(post) : null;
  if (!src) return;
  const image = new Image();
  image.decoding = 'async';
  image.src = src;
  state.lastRecommendation = next;
}

function peekNextRecommendation() {
  const sequence = state.shownIds.size + 1;
  const useRandom = shouldUseRandomRecommendation(sequence);
  if (useRandom) {
    const unseen = state.posts.map((post, index) => ({ post, index })).filter(item => !state.shownIds.has(item.post.topic_id));
    return { index: unseen.length ? unseen[0].index : randomInteger(state.posts.length), reason: 'random_preview', sequence };
  }
  if (!state.orderedIds.length) {
    return { index: randomInteger(state.posts.length), reason: 'fallback_preview', sequence };
  }
  const visCursor = state.recommendationCursor % state.orderedIds.length;
  return { index: getPostIndexById(state.orderedIds[visCursor]), reason: 'interest_preview', sequence };
}

function logRecommendation(post, detail) {
  rememberHistory(post, detail);
  const globalIndex = state.posts.findIndex(item => item.topic_id === post.topic_id);
  const interestRank = state.orderedIds.indexOf(post.topic_id);
  const payload = {
    mode: detail.reason || 'unknown',
    source: detail.source || 'init',
    sequence: detail.sequence || state.shownIds.size,
    topicId: post.topic_id,
    globalIndex,
    internalNo: globalIndex + 1,
    interestRank: interestRank >= 0 ? interestRank + 1 : null,
    total: state.posts.length,
    title: post.title,
  };
  console.info('[ProjectDrift 推荐]', payload);
}

function rememberHistory(post, detail) {
  if (detail.reason === 'history_previous') return;
  if (state.historyPointer < state.historyIds.length - 1) {
    state.historyIds = state.historyIds.slice(0, state.historyPointer + 1);
  }
  if (state.historyIds[state.historyIds.length - 1] !== post.topic_id) {
    state.historyIds.push(post.topic_id);
  }
  state.historyPointer = state.historyIds.length - 1;
}

function commitDwell(source, options = {}) {
  const post = getCurrentPost();
  if (!post || !state.enteredAt) return;
  const now = performance.now();
  const seconds = Math.max(0, (now - state.enteredAt) / 1000);
  const activeSeconds = Math.max(0, (state.lastActivityAt - state.enteredAt) / 1000);
  if (!options.forceActive && (seconds > 75 || activeSeconds < Math.min(seconds, 3))) {
    state.enteredAt = now;
    return;
  }
  const cappedSeconds = Math.min(seconds, 45);
  const weight = dwellPreferenceScore(cappedSeconds);
  const entry = ensureInteraction(post.topic_id);
  entry.views += 1;
  entry.dwell += cappedSeconds;
  entry.score += weight;
  entry.lastSeenAt = Date.now();
  entry.sources[source] = (entry.sources[source] || 0) + 1;
  addPreferenceScores(post, weight);
  saveInteractions();
}

function recordAction(post, action, score, options = {}) {
  if (options.forceActive) markActivity();
  const entry = ensureInteraction(post.topic_id);
  entry[action] = (entry[action] || 0) + 1;
  entry.score += score;
  entry.lastSeenAt = Date.now();
  addPreferenceScores(post, score);
  saveInteractions();
}

function dwellPreferenceScore(seconds) {
  if (seconds < 2) return -2;
  const center = 18;
  const spread = 13;
  const fitted = Math.exp(-Math.pow(seconds - center, 2) / (2 * spread * spread));
  return Math.round((fitted * 22 + Math.log1p(seconds) * 2) * 10) / 10;
}

function markActivity() {
  state.lastActivityAt = performance.now();
}

function addPreferenceScores(post, delta) {
  const keys = buildPreferenceKeys(post);
  for (const key of keys) {
    state.interactions.tags[key] = (state.interactions.tags[key] || 0) + delta;
  }
}

function reorderFeed(options = {}) {
  const currentId = getCurrentPost()?.topic_id;
  const scored = state.posts.map(post => ({ post, score: recommendationScore(post) }));
  scored.sort((a, b) => b.score - a.score || String(a.post.created_at || '').localeCompare(String(b.post.created_at || '')) * -1);
  const ordered = scored.map(item => item.post.topic_id);
  const unseen = ordered.filter(id => !state.shownIds.has(id));
  state.orderedIds = unseen.length > 0 ? unseen : ordered;
  if (options.keepCurrent && currentId) {
    const nextIndex = state.orderedIds.indexOf(currentId);
    if (nextIndex >= 0) state.currentIndex = getPostIndexById(state.orderedIds[nextIndex]);
  }
}

function recommendationScore(post) {
  const entry = state.interactions.posts[post.topic_id] || { score: 0, dwell: 0, views: 0, open: 0, like: 0 };
  const preferenceBoost = buildPreferenceKeys(post).reduce((sum, key) => sum + Math.max(0, state.interactions.tags[key] || 0), 0);
  const novelty = entry.views ? -Math.min(18, entry.views * 4) : 16;
  const explicitIntent = (entry.open || 0) * 24 + (entry.like || 0) * 16;
  const quality = Math.log1p((post.vote_count || 0) * 2 + (post.like_count || 0) + (post.reply_count || 0));
  return entry.score + explicitIntent + preferenceBoost * 0.84 + novelty + quality;
}

function pushLog(text) {
  console.info(compactText(text, 80));
}

function ensureInteraction(topicId) {
  const key = String(topicId);
  if (!state.interactions.posts[key]) {
    state.interactions.posts[key] = { views: 0, dwell: 0, score: 0, open: 0, like: 0, skip: 0, sources: {}, lastSeenAt: 0 };
  }
  return state.interactions.posts[key];
}

function loadInteractions() {
  try {
    const stored = JSON.parse(localStorage.getItem('project-drift-profile') || '{}');
    return { posts: stored.posts || {}, tags: stored.tags || {} };
  } catch {
    return { posts: {}, tags: {} };
  }
}

function saveInteractions() {
  localStorage.setItem('project-drift-profile', JSON.stringify(state.interactions));
}

function resetProfile() {
  localStorage.removeItem('project-drift-profile');
  state.interactions = { posts: {}, tags: {} };
  state.activeTagFilter = null;
  state.shownIds.clear();
  state.recommendationCursor = 0;
  state.historyIds = [];
  state.historyPointer = -1;
  reorderFeed();
  const index = randomInteger(state.posts.length);
  transitionToPost(index, { reason: 'reset_random', direction: 1, sequence: 1, source: 'reset' });
  pushLog('已重置本地兴趣画像');
}

function getCurrentPost() {
  return state.posts[state.currentIndex];
}

function getPostIndexById(topicId) {
  const index = state.posts.findIndex(post => post.topic_id === topicId);
  return index >= 0 ? index : 0;
}

function topTag() {
  return Object.entries(state.interactions.tags).sort((a, b) => b[1] - a[1])[0];
}

function buildDisplayTags(post) {
  const keys = buildPreferenceKeys(post).filter(key => key.length <= 8);
  return keys.length ? keys.slice(0, 5) : ['未标记'];
}

function buildPreferenceKeys(post) {
  const source = [post.title, ...(post.tags || [])].join(' ');
  const cleaned = normalizeKeywordText(source);
  const parts = cleaned.match(/[\u4e00-\u9fa5a-zA-Z0-9]{2,}/g) || [];
  const stopWords = new Set(['赛道', '学习工作', '生活娱乐', '社会服务', '社会公益', '硬件交互', '初赛', '复赛', '决赛', '作品', '报名', '专区', '大赛', 'demo', 'Demo', 'TRAE', 'AI', '一个', '基于', '使用', '通过', '项目', '产品', '工具']);
  const counts = new Map();
  for (const part of parts) {
    const key = part.trim();
    if (key.length < 2 || stopWords.has(key)) continue;
    if (/^\d+$/.test(key)) continue;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || b[0].length - a[0].length).map(([key]) => key).slice(0, 8);
}

function normalizeKeywordText(value) {
  return String(value || '')
    .replace(/【[^】]*(赛道|大赛|报名专区)[^】]*】/g, ' ')
    .replace(/[\[\]【】（）()《》<>#:_·—\-+|,，。！？!?.、/\\]/g, ' ')
    .replace(/\b(demo|trae|ai)\b/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function pickImage(post) {
  const image = (post.images || []).find(item => item.src && !item.src.includes('/emoji/'));
  return image?.src || null;
}

function extractDemoIntro(post) {
  const text = String(post.text || post.summary || '');
  const match = text.match(/(?:\d+|[一二三四五六七八九十]+)?[.、．\s]*Demo\s*简介[：:\s\n]*([\s\S]*?)(?=\n\s*(?:(?:\d+|[一二三四五六七八九十]+)[.、．\s]*)?(?:Demo\s*创作思路|创作思路|Demo\s*体验地址|体验地址|TRAE\s*实践过程|实践过程|Session\s*ID|$))/i);
  if (match?.[1]?.trim()) return match[1].trim();
  const fallback = text.replace(/^【[^\n]+】[^\n]*\n?/, '').replace(/^.*?Demo\s*/i, '').trim();
  return fallback || post.summary || text;
}

function compactText(text, max) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max)}…` : clean;
}

function formatDate(value) {
  if (!value) return '未知时间';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未知时间';
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(date);
}

function formatNumber(value) {
  return new Intl.NumberFormat('zh-CN').format(value);
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
}

function randomInteger(max) {
  return Math.floor(Math.random() * max);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function renderEmpty(message) {
  feed.innerHTML = `<div class="empty-state"><p>${escapeHtml(message)}</p></div>`;
}
