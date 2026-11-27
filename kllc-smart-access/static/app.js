/**
 * KLLC Smart Access Lite - Frontend Client
 * สำนักการเรียนรู้ตลอดชีวิต (KLLC) สจล.
 */

// Application State
const state = {
  currentTab: 'live',
  ws: null,
  soundEnabled: false,
  isPaused: false,
  audioCtx: null,
  historyPage: 0,
  historyLimit: 25,
  historyTotal: 0,
  personnelData: [],
  filters: {
    startDate: '',
    endDate: '',
    search: '',
    channelId: '',
    libraryName: '',
    collapseUnknowns: false
  }
};

// Initialize Application on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initClock();
  initDatePresets();
  initAudio();
  initWebSocket();
  loadSystemStatus();
  loadDailyStats();
  loadAccessEvents(0);
  loadPersonnel();

  // Load sound preference from localStorage
  const savedSound = localStorage.getItem('kllc_sound_enabled');
  if (savedSound === 'true') {
    enableSound();
  }
});

// --- CLOCK & TIMERS ---
function initClock() {
  function updateTime() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('th-TH', { hour12: false });
    const dateStr = now.toLocaleDateString('th-TH', { day: '2-digit', month: '2-digit', year: 'numeric' });
    
    const clockEl = document.getElementById('live-clock');
    const clockMob = document.getElementById('clock-mobile');
    const dateEl = document.getElementById('live-date');
    if (clockEl) clockEl.textContent = timeStr;
    if (clockMob) clockMob.textContent = timeStr;
    if (dateEl) dateEl.textContent = dateStr;
  }
  updateTime();
  setInterval(updateTime, 1000);
}

// --- TAB SWITCHING ---
function switchTab(tabName) {
  state.currentTab = tabName;
  const tabs = ['live', 'history', 'personnel'];
  
  tabs.forEach(t => {
    const btn = document.getElementById(`tab-btn-${t}`);
    const sec = document.getElementById(`section-${t}`);
    if (t === tabName) {
      sec.classList.remove('hidden');
      btn.classList.add('bg-gradient-to-r', 'from-cyan-600', 'to-emerald-600', 'text-white', 'shadow');
      btn.classList.remove('text-slate-400');
    } else {
      sec.classList.add('hidden');
      btn.classList.remove('bg-gradient-to-r', 'from-cyan-600', 'to-emerald-600', 'text-white', 'shadow');
      btn.classList.add('text-slate-400');
    }
  });

  if (tabName === 'history') {
    loadDailyStats();
    loadAccessEvents(state.historyPage);
  } else if (tabName === 'personnel') {
    loadPersonnel();
  }
}

// --- WEBAUDIO CHIME SYNTHESIZER ---
function initAudio() {
  // AudioContext will be instantiated on user gesture
}

function enableSound() {
  state.soundEnabled = true;
  localStorage.setItem('kllc_sound_enabled', 'true');
  const icon = document.getElementById('sound-icon');
  const label = document.getElementById('sound-label');
  if (icon) icon.textContent = '🔊';
  if (label) label.textContent = 'ปิดเสียง';
}

function disableSound() {
  state.soundEnabled = false;
  localStorage.setItem('kllc_sound_enabled', 'false');
  const icon = document.getElementById('sound-icon');
  const label = document.getElementById('sound-label');
  if (icon) icon.textContent = '🔇';
  if (label) label.textContent = 'เปิดเสียงแจ้งเตือน';
}

function toggleSound() {
  if (!state.audioCtx) {
    state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (state.soundEnabled) {
    disableSound();
    showToast('ปิดเสียงแจ้งเตือนแล้ว', 'info');
  } else {
    enableSound();
    playChime('MATCHED');
    showToast('เปิดเสียงแจ้งเตือนแล้ว', 'success');
  }
}

function playChime(type) {
  if (!state.soundEnabled) return;
  try {
    if (!state.audioCtx) {
      state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (state.audioCtx.state === 'suspended') {
      state.audioCtx.resume();
    }

    const now = state.audioCtx.currentTime;
    const osc = state.audioCtx.createOscillator();
    const gain = state.audioCtx.createGain();

    osc.connect(gain);
    gain.connect(state.audioCtx.destination);

    if (type === 'MATCHED') {
      // Pleasant high double beep
      osc.type = 'sine';
      osc.frequency.setValueAtTime(587.33, now); // D5
      osc.frequency.setValueAtTime(880.00, now + 0.1); // A5
      gain.gain.setValueAtTime(0.15, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc.start(now);
      osc.stop(now + 0.35);
    } else {
      // Soft single lower tone
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(329.63, now); // E4
      gain.gain.setValueAtTime(0.1, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
      osc.start(now);
      osc.stop(now + 0.25);
    }
  } catch (e) {
    console.warn("Audio chime error:", e);
  }
}

// --- WEBSOCKET CLIENT ---
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    console.log("WebSocket connected to KLLC backend.");
    updateNvrStatusBadge(true, "เชื่อมต่อเซิร์ฟเวอร์แล้ว (Listening)");
  };

  state.ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleIncomingMessage(msg);
    } catch (e) {
      console.error("WS Parse error:", e);
    }
  };

  state.ws.onclose = () => {
    console.warn("WebSocket closed. Reconnecting in 3s...");
    updateNvrStatusBadge(false, "กำลังต่อเชื่อมเซิร์ฟเวอร์ใหม่...");
    setTimeout(initWebSocket, 3000);
  };

  state.ws.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

function handleIncomingMessage(msg) {
  if (msg.type === 'CONNECTION_INIT' || msg.type === 'NVR_STATUS') {
    const isConn = msg.data.connected;
    const text = msg.data.message || (isConn ? "เชื่อมต่อ NVR เรียบร้อย" : "ขาดการเชื่อมต่อ NVR");
    updateNvrStatusBadge(isConn, text);
  } else if (msg.type === 'ACCESS_EVENT') {
    const ev = msg.data;
    if (!state.isPaused) {
      appendLiveFeedCard(ev);
      playChime(ev.match_status);
      updateCameraLastActivity(ev.channel_id, ev.event_time);
    }
    // Update daily stats live if on history tab
    if (state.currentTab === 'history') {
      loadDailyStats();
    }
  }
}

function updateNvrStatusBadge(isConnected, message) {
  const badge = document.getElementById('nvr-status-badge');
  const dot = document.getElementById('nvr-dot');
  const text = document.getElementById('nvr-status-text');

  if (!badge || !dot || !text) return;

  if (isConnected) {
    dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-400";
    badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-emerald-950/60 border border-emerald-800/80 text-xs text-emerald-300";
    text.textContent = message || "NVR เชื่อมต่อปกติ";
  } else {
    dot.className = "w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse";
    badge.className = "flex items-center space-x-2 px-3 py-1.5 rounded-full bg-amber-950/60 border border-amber-800/80 text-xs text-amber-300";
    text.textContent = message || "กำลังเชื่อมต่อ NVR...";
  }
}

function updateCameraLastActivity(chId, timeStr) {
  const el = document.getElementById(`cam-last-${chId}`);
  if (el) {
    const t = timeStr.includes(' ') ? timeStr.split(' ')[1] : timeStr;
    el.textContent = t;
    el.classList.add('text-emerald-400');
    setTimeout(() => el.classList.remove('text-emerald-400'), 3000);
  }
}

// --- LIVE FEED CARDS RENDERING ---
function togglePauseStream() {
  state.isPaused = !state.isPaused;
  const icon = document.getElementById('pause-icon');
  const label = document.getElementById('pause-label');
  if (state.isPaused) {
    icon.textContent = '▶️';
    label.textContent = 'ทำงานต่อ';
    showToast('หยุดแสดงผลสดชั่วคราว', 'info');
  } else {
    icon.textContent = '⏸️';
    label.textContent = 'หยุดชั่วคราว';
    showToast('เปิดแสดงผลสดต่อเนื่อง', 'success');
  }
}

function appendLiveFeedCard(ev) {
  const feedList = document.getElementById('live-feed-list');
  const emptyState = document.getElementById('feed-empty-state');
  if (emptyState) emptyState.remove();

  const isMatched = ev.match_status === 'MATCHED';
  const card = document.createElement('div');
  
  if (isMatched) {
    card.className = "bg-gradient-to-r from-[#0c1c20] via-[#0d1f27] to-[#0f172a] border border-emerald-500/40 hover:border-emerald-400/80 rounded-xl p-3.5 transition-all shadow-md shadow-emerald-950/20 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-fade-in";
    
    card.innerHTML = `
      <div class="flex items-center space-x-3.5">
        <!-- Avatar / Snapshot preview -->
        <div class="relative w-12 h-12 rounded-xl bg-emerald-950 border border-emerald-500/50 flex items-center justify-center overflow-hidden flex-shrink-0">
          ${ev.snapshot_url 
            ? `<img src="/api/snapshot/proxy?url=${encodeURIComponent(ev.snapshot_url)}" alt="snap" class="w-full h-full object-cover" />`
            : `<svg class="w-6 h-6 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>`
          }
          <div class="absolute bottom-0 right-0 w-3.5 h-3.5 bg-emerald-500 rounded-full border-2 border-[#0c1c20]"></div>
        </div>

        <!-- Person Information -->
        <div>
          <div class="flex items-center space-x-2">
            <span class="font-bold text-sm text-white">${ev.full_name || 'เจ้าหน้าที่ KLLC'}</span>
            <span class="text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-700/60 font-semibold">${ev.person_code || '-'}</span>
            <span class="text-[10px] px-2 py-0.5 rounded-full ${ev.library_name === 'KLLC STAFF' ? 'bg-cyan-950 text-cyan-300 border border-cyan-800' : 'bg-purple-950 text-purple-300 border border-purple-800'}">${ev.library_name || 'KLLC'}</span>
          </div>
          
          <div class="flex items-center space-x-3 text-xs text-slate-400 mt-1">
            <span class="flex items-center text-slate-300">
              <span class="w-1.5 h-1.5 rounded-full bg-cyan-400 mr-1.5"></span>
              ${ev.camera_name || 'D' + ev.channel_id}
            </span>
            <span>•</span>
            <span class="font-mono text-slate-400">${ev.event_time}</span>
            <span>•</span>
            <span class="text-xs font-semibold ${ev.direction === 'IN' ? 'text-emerald-400' : 'text-amber-400'}">
              ${ev.direction === 'IN' ? '↓ เข้า (IN)' : '↑ ออก (OUT)'}
            </span>
          </div>
        </div>
      </div>

      <!-- Similarity Badge -->
      <div class="flex sm:flex-col items-center sm:items-end justify-between w-full sm:w-auto border-t sm:border-t-0 pt-2 sm:pt-0 border-slate-800">
        <div class="text-[11px] text-slate-400 sm:text-right">ความเหมือน AI</div>
        <div class="font-mono font-bold text-sm text-emerald-400 bg-emerald-950/60 px-2.5 py-0.5 rounded border border-emerald-800/60">${ev.similarity ? ev.similarity.toFixed(1) : '95.0'}%</div>
      </div>
    `;
  } else {
    // UNKNOWN Person Card
    card.className = "bg-[#111827] border border-slate-700/70 hover:border-slate-600 rounded-xl p-3.5 transition-all shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-fade-in";
    
    card.innerHTML = `
      <div class="flex items-center space-x-3.5">
        <div class="w-12 h-12 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center flex-shrink-0">
          <svg class="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
        </div>

        <div>
          <div class="flex items-center space-x-2">
            <span class="font-semibold text-sm text-slate-300">ไม่ทราบตัวตน (Unknown Face)</span>
            <span class="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">บุคคลภายนอก</span>
          </div>

          <div class="flex items-center space-x-3 text-xs text-slate-400 mt-1">
            <span class="flex items-center text-slate-300">
              <span class="w-1.5 h-1.5 rounded-full bg-slate-500 mr-1.5"></span>
              ${ev.camera_name || 'D' + ev.channel_id}
            </span>
            <span>•</span>
            <span class="font-mono text-slate-400">${ev.event_time}</span>
            <span>•</span>
            <span class="text-xs ${ev.direction === 'IN' ? 'text-emerald-400' : 'text-amber-400'}">
              ${ev.direction === 'IN' ? '↓ เข้า (IN)' : '↑ ออก (OUT)'}
            </span>
          </div>
        </div>
      </div>

      <div class="flex sm:flex-col items-center sm:items-end justify-between w-full sm:w-auto border-t sm:border-t-0 pt-2 sm:pt-0 border-slate-800 text-xs text-slate-500">
        <span>ไม่พบในคลัง</span>
        <span class="font-mono text-slate-400">-</span>
      </div>
    `;
  }

  feedList.insertBefore(card, feedList.firstChild);

  // Keep max 50 items to prevent excessive DOM growth
  while (feedList.children.length > 50) {
    feedList.removeChild(feedList.lastChild);
  }
}

// --- TEST SIMULATION TRIGGER ---
async function simulateTestEvent(status) {
  try {
    const ch = Math.random() > 0.5 ? 2 : 3;
    const res = await fetch(`/api/test/simulate-event?match_status=${status}&channel_id=${ch}`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(`จำลองเหตุการณ์ ${status} สำเร็จ`, 'success');
    }
  } catch (e) {
    console.error("Simulate error:", e);
    showToast("เกิดข้อผิดพลาดในการจำลอง", "error");
  }
}

// --- TAB 2: ACCESS HISTORY & STATS ---
function initDatePresets() {
  const today = new Date().toISOString().split('T')[0];
  document.getElementById('filter-start-date').value = today;
  document.getElementById('filter-end-date').value = today;
  state.filters.startDate = today;
  state.filters.endDate = today;
}

function setDatePreset(type) {
  const today = new Date();
  let start = new Date();
  let end = new Date();

  document.querySelectorAll('.date-preset-btn').forEach(b => {
    b.classList.remove('bg-cyan-600', 'text-white');
    b.classList.add('bg-slate-800', 'text-slate-400');
  });

  const btn = document.getElementById(`btn-date-${type}`);
  if (btn) {
    btn.classList.add('bg-cyan-600', 'text-white');
    btn.classList.remove('bg-slate-800', 'text-slate-400');
  }

  if (type === 'today') {
    // start & end = today
  } else if (type === 'yesterday') {
    start.setDate(today.getDate() - 1);
    end.setDate(today.getDate() - 1);
  } else if (type === '7days') {
    start.setDate(today.getDate() - 6);
  }

  const startStr = start.toISOString().split('T')[0];
  const endStr = end.toISOString().split('T')[0];

  document.getElementById('filter-start-date').value = startStr;
  document.getElementById('filter-end-date').value = endStr;
  state.filters.startDate = startStr;
  state.filters.endDate = endStr;

  loadDailyStats(startStr);
  loadAccessEvents(0);
}

async function loadDailyStats(dateStr) {
  try {
    const url = dateStr ? `/api/stats/daily?date=${dateStr}` : '/api/stats/daily';
    const res = await fetch(url);
    const data = await res.json();

    document.getElementById('stat-total').textContent = data.total_events.toLocaleString();
    document.getElementById('stat-matched').textContent = data.matched_count.toLocaleString();
    document.getElementById('stat-unknown').textContent = data.unknown_count.toLocaleString();
    document.getElementById('stat-unique-persons').textContent = `บุคลากรไม่ซ้ำ: ${data.unique_persons} คน`;
    document.getElementById('stat-match-rate').textContent = `${data.match_rate_percentage}%`;
    document.getElementById('stat-in').textContent = `IN ${data.in_count}`;
    document.getElementById('stat-out').textContent = `OUT ${data.out_count}`;
  } catch (e) {
    console.error("Error loading stats:", e);
  }
}

async function loadAccessEvents(page = 0) {
  state.historyPage = page;
  const tbody = document.getElementById('history-table-body');
  tbody.innerHTML = `<tr><td colspan="8" class="py-12 text-center text-slate-500">กำลังโหลดข้อมูล...</td></tr>`;

  // Read filters
  const startDate = document.getElementById('filter-start-date').value;
  const endDate = document.getElementById('filter-end-date').value;
  const search = document.getElementById('filter-search').value.trim();
  const channelId = document.getElementById('filter-channel').value;
  const libraryName = document.getElementById('filter-library').value;
  const collapseUnknowns = document.getElementById('toggle-collapse-unknowns').checked;

  // Visual slider state
  const sliderBg = document.getElementById('collapse-slider-bg');
  const sliderDot = document.getElementById('collapse-slider-dot');
  if (collapseUnknowns) {
    sliderBg.classList.add('bg-cyan-600');
    sliderBg.classList.remove('bg-slate-800');
    sliderDot.style.transform = 'translateX(16px)';
  } else {
    sliderBg.classList.remove('bg-cyan-600');
    sliderBg.classList.add('bg-slate-800');
    sliderDot.style.transform = 'translateX(0px)';
  }

  const offset = page * state.historyLimit;
  const params = new URLSearchParams({
    limit: state.historyLimit,
    offset: offset,
    collapse_unknowns: collapseUnknowns
  });

  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  if (search) params.append('search', search);
  if (channelId) params.append('channel_id', channelId);
  if (libraryName) {
    if (libraryName === 'UNKNOWN') {
      params.append('match_status', 'UNKNOWN');
    } else {
      params.append('library_name', libraryName);
    }
  }

  try {
    const res = await fetch(`/api/events?${params.toString()}`);
    const data = await res.json();
    state.historyTotal = data.total;

    renderHistoryTable(data.items, offset, data.total);
    updatePaginationControls(offset, data.items.length, data.total);
  } catch (e) {
    console.error("Load events error:", e);
    tbody.innerHTML = `<tr><td colspan="8" class="py-8 text-center text-rose-400">เกิดข้อผิดพลาดในการโหลดข้อมูล</td></tr>`;
  }
}

function renderHistoryTable(items, offset, total) {
  const tbody = document.getElementById('history-table-body');
  if (!items || items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="py-12 text-center text-slate-500">ไม่พบประวัติการเข้า-ออกตามเงื่อนไขที่เลือก</td></tr>`;
    return;
  }

  tbody.innerHTML = items.map((it, idx) => {
    const isMatched = it.match_status === 'MATCHED';
    return `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-3 px-3 font-mono text-slate-300">${it.event_time}</td>
        <td class="py-3 px-3">
          <span class="font-mono text-xs px-2 py-0.5 rounded bg-slate-800 text-cyan-300 border border-slate-700">D${it.channel_id}</span>
          <span class="text-slate-400 ml-1.5">${it.camera_name}</span>
        </td>
        <td class="py-3 px-3">
          ${isMatched
            ? `<span class="px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800 font-semibold text-[11px]">MATCHED</span>`
            : `<span class="px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700 text-[11px]">UNKNOWN</span>`
          }
        </td>
        <td class="py-3 px-3 font-mono ${isMatched ? 'text-emerald-300 font-semibold' : 'text-slate-500'}">
          ${it.person_code || '-'}
        </td>
        <td class="py-3 px-3 font-medium ${isMatched ? 'text-white' : 'text-slate-400'}">
          ${it.full_name || 'บุคคลไม่ทราบตัวตน'}
        </td>
        <td class="py-3 px-3">
          ${it.library_name 
            ? `<span class="px-2 py-0.5 rounded text-[11px] ${it.library_name === 'KLLC STAFF' ? 'bg-cyan-950 text-cyan-300 border border-cyan-800' : 'bg-purple-950 text-purple-300 border border-purple-800'}">${it.library_name}</span>`
            : `<span class="text-slate-600">-</span>`
          }
        </td>
        <td class="py-3 px-3 text-center font-mono ${isMatched ? 'text-emerald-400 font-bold' : 'text-slate-600'}">
          ${isMatched ? `${it.similarity.toFixed(1)}%` : '-'}
        </td>
        <td class="py-3 px-3 text-center font-semibold text-xs ${it.direction === 'IN' ? 'text-emerald-400' : 'text-amber-400'}">
          ${it.direction === 'IN' ? 'เข้า (IN)' : 'ออก (OUT)'}
        </td>
      </tr>
    `;
  }).join('');
}

function updatePaginationControls(offset, count, total) {
  const startEl = document.getElementById('page-showing-start');
  const endEl = document.getElementById('page-showing-end');
  const totalEl = document.getElementById('page-showing-total');
  const pageNumEl = document.getElementById('page-current-num');
  const btnPrev = document.getElementById('btn-prev-page');
  const btnNext = document.getElementById('btn-next-page');

  const start = total === 0 ? 0 : offset + 1;
  const end = offset + count;

  if (startEl) startEl.textContent = start.toLocaleString();
  if (endEl) endEl.textContent = end.toLocaleString();
  if (totalEl) totalEl.textContent = total.toLocaleString();
  if (pageNumEl) pageNumEl.textContent = state.historyPage + 1;

  if (btnPrev) btnPrev.disabled = state.historyPage === 0;
  if (btnNext) btnNext.disabled = end >= total;
}

function changePage(delta) {
  const newPage = state.historyPage + delta;
  if (newPage >= 0) {
    loadAccessEvents(newPage);
  }
}

function resetFilters() {
  document.getElementById('filter-search').value = '';
  document.getElementById('filter-channel').value = '';
  document.getElementById('filter-library').value = '';
  document.getElementById('toggle-collapse-unknowns').checked = false;
  setDatePreset('today');
}

function exportData(type) {
  const startDate = document.getElementById('filter-start-date').value;
  const endDate = document.getElementById('filter-end-date').value;
  const search = document.getElementById('filter-search').value.trim();
  const channelId = document.getElementById('filter-channel').value;
  const libraryName = document.getElementById('filter-library').value;
  const collapseUnknowns = document.getElementById('toggle-collapse-unknowns').checked;

  const params = new URLSearchParams({ collapse_unknowns: collapseUnknowns });
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  if (search) params.append('search', search);
  if (channelId) params.append('channel_id', channelId);
  if (libraryName) {
    if (libraryName === 'UNKNOWN') params.append('match_status', 'UNKNOWN');
    else params.append('library_name', libraryName);
  }

  const endpoint = type === 'excel' ? '/api/export/excel' : '/api/export/csv';
  window.open(`${endpoint}?${params.toString()}`, '_blank');
}

// --- TAB 3: PERSONNEL SYNC ---
async function loadPersonnel() {
  const tbody = document.getElementById('personnel-table-body');
  tbody.innerHTML = `<tr><td colspan="5" class="py-12 text-center text-slate-500">กำลังโหลดรายชื่อ...</td></tr>`;

  try {
    const res = await fetch('/api/persons?limit=1000');
    const data = await res.json();
    state.personnelData = data.items;
    renderPersonnelTable(data.items);
  } catch (e) {
    console.error("Error loading personnel:", e);
    tbody.innerHTML = `<tr><td colspan="5" class="py-8 text-center text-rose-400">เกิดข้อผิดพลาดในการโหลดรายชื่อ</td></tr>`;
  }
}

function renderPersonnelTable(list) {
  const tbody = document.getElementById('personnel-table-body');
  const countEl = document.getElementById('personnel-total-count');
  if (countEl) countEl.textContent = list.length.toLocaleString();

  if (!list || list.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="py-12 text-center text-slate-500">ยังไม่มีรายชื่อบุคลากรในระบบ กรุณากดปุ่ม "ซิงก์รายชื่อจาก NVR"</td></tr>`;
    return;
  }

  tbody.innerHTML = list.map(p => `
    <tr class="hover:bg-slate-800/40 transition">
      <td class="py-3 px-3 font-mono font-bold text-emerald-400">${p.person_code}</td>
      <td class="py-3 px-3 font-medium text-white">${p.full_name}</td>
      <td class="py-3 px-3">
        <span class="px-2 py-0.5 rounded text-xs ${p.library_name === 'KLLC STAFF' ? 'bg-cyan-950 text-cyan-300 border border-cyan-800' : 'bg-purple-950 text-purple-300 border border-purple-800'}">
          ${p.library_name}
        </span>
      </td>
      <td class="py-3 px-3 text-center">
        <span class="px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800 text-[11px] font-semibold">
          ✓ ${p.consent_status || 'CONSENTED'}
        </span>
      </td>
      <td class="py-3 px-3 text-right font-mono text-xs text-slate-400">${p.updated_at || '-'}</td>
    </tr>
  `).join('');
}

function filterPersonnelList() {
  const query = document.getElementById('personnel-search-input').value.trim().toLowerCase();
  if (!query) {
    renderPersonnelTable(state.personnelData);
    return;
  }
  const filtered = state.personnelData.filter(p => 
    (p.person_code && p.person_code.toLowerCase().includes(query)) ||
    (p.full_name && p.full_name.toLowerCase().includes(query))
  );
  renderPersonnelTable(filtered);
}

async function triggerPersonnelSync() {
  const btn = document.getElementById('btn-sync-nvr');
  const icon = document.getElementById('sync-icon');
  const label = document.getElementById('sync-btn-label');

  btn.disabled = true;
  icon.classList.add('animate-spin');
  label.textContent = "กำลังซิงก์จาก NVR...";

  try {
    const res = await fetch('/api/persons/sync', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      await loadPersonnel();
    } else {
      showToast("ซิงก์ไม่สำเร็จ: " + (data.detail || "ข้อผิดพลาด"), 'error');
    }
  } catch (e) {
    console.error("Sync error:", e);
    showToast("เกิดข้อผิดพลาดในการเชื่อมต่อซิงก์ NVR", 'error');
  } finally {
    btn.disabled = false;
    icon.classList.remove('animate-spin');
    label.textContent = "ซิงก์รายชื่อจาก NVR";
  }
}

async function loadSystemStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    if (data.nvr) {
      updateNvrStatusBadge(data.nvr.connected, data.nvr.connected ? "NVR เชื่อมต่อปกติ" : "กำลังรอการเชื่อมต่อ NVR...");
    }
  } catch (e) {
    console.warn("Status check:", e);
  }
}

// --- TOAST NOTIFICATIONS ---
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  const colorMap = {
    success: 'bg-emerald-950/95 border-emerald-600 text-emerald-200',
    error: 'bg-rose-950/95 border-rose-600 text-rose-200',
    info: 'bg-slate-900/95 border-slate-700 text-slate-200'
  };

  toast.className = `px-4 py-2.5 rounded-xl border shadow-xl text-xs font-medium backdrop-blur-md pointer-events-auto transition-all transform duration-300 translate-y-2 opacity-0 ${colorMap[type] || colorMap.info}`;
  toast.textContent = message;

  container.appendChild(toast);

  // Trigger animation
  setTimeout(() => {
    toast.classList.remove('translate-y-2', 'opacity-0');
  }, 10);

  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// --- NVR SETTINGS MODAL ---
async function openSettingsModal() {
  const modal = document.getElementById('settings-modal');
  const statusBox = document.getElementById('settings-status-box');
  if (statusBox) statusBox.classList.add('hidden');

  try {
    const res = await fetch('/api/settings');
    const data = await res.json();
    document.getElementById('set-nvr-ip').value = data.nvr_ip || '192.168.1.100';
    document.getElementById('set-nvr-port').value = data.nvr_port || 80;
    document.getElementById('set-nvr-user').value = data.nvr_user || 'admin';
    document.getElementById('set-nvr-pass').value = '';
  } catch (e) {
    console.error("Failed to load settings:", e);
  }

  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeSettingsModal() {
  const modal = document.getElementById('settings-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

async function saveNvrSettings(event) {
  event.preventDefault();
  const btn = document.getElementById('btn-save-settings');
  const statusBox = document.getElementById('settings-status-box');

  const payload = {
    nvr_ip: document.getElementById('set-nvr-ip').value.trim(),
    nvr_port: parseInt(document.getElementById('set-nvr-port').value, 10) || 80,
    nvr_user: document.getElementById('set-nvr-user').value.trim(),
    nvr_pass: document.getElementById('set-nvr-pass').value
  };

  btn.disabled = true;
  btn.textContent = 'กำลังบันทึกและทดสอบ...';
  statusBox.classList.add('hidden');

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    statusBox.classList.remove('hidden');
    if (data.connected) {
      statusBox.className = 'rounded-xl p-3 text-xs border bg-emerald-950/70 border-emerald-700 text-emerald-300';
      statusBox.textContent = '✅ ' + data.message;
      showToast(data.message, 'success');
      updateNvrStatusBadge(true, 'NVR เชื่อมต่อปกติ');
    } else {
      statusBox.className = 'rounded-xl p-3 text-xs border bg-amber-950/70 border-amber-700 text-amber-300';
      statusBox.textContent = '⚠️ ' + (data.message || 'บันทึกค่าแล้ว แต่ยังเชื่อมต่อ NVR ไม่ได้');
      showToast('บันทึกการตั้งค่าแล้ว', 'info');
    }
  } catch (e) {
    statusBox.classList.remove('hidden');
    statusBox.className = 'rounded-xl p-3 text-xs border bg-rose-950/70 border-rose-700 text-rose-300';
    statusBox.textContent = '❌ เกิดข้อผิดพลาดในการบันทึกการตั้งค่า';
  } finally {
    btn.disabled = false;
    btn.textContent = 'บันทึก & เชื่อมต่อ NVR';
  }
}

