// ===== 成员与权限（2026-10-07 重设计：子页签 + 统一保存） =====
//
// 页面结构：三个子页签（群聊 / 私聊 / 管理员）+ 底部统一保存条。
// 保存语义只有一条规则：「回复」开关立即生效（桥接侧），其余全部
// 走右下「💾 保存」写入 AstrBot 配置，再「🔄 重启 AstrBot」生效。
var peopleData = null;
var peopleDirty = false;          // 有未保存修改（刷新名单前要确认）
var currentArBlacklist = [];      // 插话黑名单（服务端最近一次值）
var arOverrides = {};             // gid → 「插嘴」勾选（仅记录用户改动过的行）

// 当前私聊白名单（uid / UMO 混合）缓存：搜索、「只看已勾」触发局部重渲染
// 时用它，避免把「面板拉到的旧值」当成「用户正在编辑的新值」丢掉勾选。
var currentWhitelist = [];
var humanizerStyleOverrides = {};   // umo → style（当前服务端值）
var humanizerStyleDirty = false;    // 用户是否改过会话风格

// ---- 子页签 ----
function switchMembersTab(name) {
  document.querySelectorAll('#page-members .seg').forEach(function(b){
    b.classList.toggle('active', b.getAttribute('data-sub') === name);
  });
  document.querySelectorAll('#page-members .members-sub').forEach(function(p){
    p.classList.toggle('active', p.id === 'sub-' + name);
  });
  try { history.replaceState(null, '', '#members/' + name); } catch (e) {}
}

// ---- 数据加载 ----
function switchTabMembers() {
  document.getElementById('membersBadge').textContent = '加载中...';
  // 先用缓存立即渲染；再静默补拉一遍 WeFlow 联系人（bot 新进的群/新好友），
  // 拉到新东西且用户没在编辑时自动重渲染一次。
  // ⚠️ 不能先等 refresh 再渲染：WeFlow 没起时 refresh 要等 10s 超时，
  // 整个页签会白屏卡住。
  fetch('/api/people').then(function(r){return r.json()})
    .then(loadPeopleData)
    .catch(function(e){
      document.getElementById('membersBadge').textContent = '加载失败: ' + e.message;
    });
  fetch('/api/refresh-people', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})
    .then(function(r){return r.json()})
    .then(function(res){
      if (res && res.ok && res.new > 0 && !peopleDirty) {
        fetch('/api/people').then(function(r){return r.json()}).then(loadPeopleData);
      }
    })
    .catch(function(){ /* WeFlow 不可用时静默忽略，缓存照常显示 */ });
}

function loadPeopleData(d) {
  peopleData = d;
  document.getElementById('page-members').classList.toggle('generic',!d.astrbot_enabled);
  if(!d.astrbot_enabled) switchMembersTab('groups');
  peopleDirty = false;
  arOverrides = {};
  updateDirtyHint();
  document.getElementById('membersBadge').textContent = d.astrbot_available
    ? (d.persons.length + ' 人 · ' + d.groups.length + ' 群 · AstrBot 已连接')
    : (d.astrbot_enabled ? '未找到 AstrBot 配置: ' + d.astrbot_path : '通用模式 · 群回复开关立即生效');
  currentArBlacklist = (d.ar_blacklist || []).map(function(x){return String(x).trim()});
  var h = d.humanizer || {};
  humanizerStyleOverrides = {};
  humanizerStyleDirty = false;
  Object.keys(h.overrides || {}).forEach(function(k){
    humanizerStyleOverrides[String(k)] = String(h.overrides[k]);
  });
  var gs = document.getElementById('hsGlobalStyle');
  if (gs) gs.value = h.global_style || '-';
  renderHumanizerStyles();
  renderPeople();
  renderGroups(true);
  fillAstrbotForm(d);
}

// 手动刷新名单：POST /api/refresh-people（后端拉 WeFlow contacts，
// 群成员名册在后台线程补）→ 重新读 /api/people → 整页重渲染。
function refreshPeople() {
  if (peopleDirty && !confirm('有未保存的修改，刷新会丢弃它们。继续？')) return;
  var btn = document.getElementById('btnRefreshPeople');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 刷新中…'; }
  fetch('/api/refresh-people', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})
    .then(function(r){return r.json()})
    .catch(function(e){ return {ok:false, error:String(e)}; })
    .then(function(res){
      return fetch('/api/people').then(function(r){return r.json()}).then(function(d){
        loadPeopleData(d);
        if (btn) { btn.disabled = false; btn.textContent = '🔄 刷新名单'; }
        if (res && res.error) toast('⚠️ WeFlow 联系人拉取失败：' + res.error + '（已按缓存显示）', 'error');
        else if (res && res.new > 0) toast('✅ 已刷新：新增 ' + res.new + ' 条，现在共 ' + d.groups.length + ' 个群', 'success');
        else toast('✅ 名单已是最新（' + d.groups.length + ' 个群）', 'info');
      });
    })
    .catch(function(e){
      if (btn) { btn.disabled = false; btn.textContent = '🔄 刷新名单'; }
      toast('❌ 刷新失败: ' + e.message, 'error');
    });
}

// ---- 未保存提示 ----
function markDirty() {
  peopleDirty = true;
  updateDirtyHint();
}

function updateDirtyHint() {
  var dot = document.getElementById('dirtyDot');
  if (dot) dot.classList.toggle('show', !!peopleDirty);
}

function copyText(text) {
  if (navigator.clipboard) { navigator.clipboard.writeText(text); }
  else {
    var ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
  }
  toast('已复制: ' + text, 'info');
}

// ---- 管理员子页 ----
function renderPeople() {
  if (!peopleData) return;
  var kw = (document.getElementById('memberSearch').value || '').toLowerCase();
  var admins = peopleData.admins;
  var rows = '';
  peopleData.persons.forEach(function(p){
    if (kw && p.name.toLowerCase().indexOf(kw) < 0 && p.wxid.toLowerCase().indexOf(kw) < 0) return;
    var isAdmin = admins.indexOf(p.wxid) >= 0;
    rows += '<tr>'
      + '<td class="center"><input type="checkbox" data-wxid="' + esc(p.wxid) + '"' + (isAdmin ? ' checked' : '') + ' onchange="markDirty()"></td>'
      + '<td>' + esc(p.name) + (isAdmin ? '<span class="admin-badge">管理员</span>' : '') + '</td>'
      + '<td class="wxid">' + esc(p.wxid) + '</td>'
      + '<td class="uid">' + esc(p.uid) + '</td>'
      + '</tr>';
  });
  document.getElementById('peopleBody').innerHTML = rows || '<tr><td colspan="4" style="color:#7d838c">没有匹配的成员（名册随消息与「刷新名单」更新）</td></tr>';
  var cnt = document.getElementById('peopleCount');
  if (cnt) cnt.textContent = peopleData.persons.length;
}

function scanAdminChecks() {
  // 把当前表格里的勾选状态并回 peopleData.admins（被搜索过滤掉的成员不受影响）
  var checked = {};
  document.querySelectorAll('#peopleBody input[type=checkbox]').forEach(function(cb){
    checked[cb.getAttribute('data-wxid')] = cb.checked;
  });
  peopleData.persons.forEach(function(p){
    if (!(p.wxid in checked)) return;
    var i = peopleData.admins.indexOf(p.wxid);
    if (checked[p.wxid] && i < 0) peopleData.admins.push(p.wxid);
    if (!checked[p.wxid] && i >= 0) peopleData.admins.splice(i, 1);
  });
}

// ---- 群聊子页 ----
// 群总表：「回复」开关立即生效；「插嘴」写 arOverrides，随统一保存提交。
// reset=true  → 忽略 DOM 现状，按服务端黑名单渲染（刚加载数据时）；
// reset=false → 保住用户未保存的勾选（搜索筛选触发重渲染时）。
function renderGroups(reset) {
  if (!peopleData) return;
  if (reset) arOverrides = {};
  var kw = ((document.getElementById('groupSearch') || {}).value || '').toLowerCase().trim();
  var rows = '', shown = 0;
  peopleData.groups.forEach(function(g){
    if (kw && g.name.toLowerCase().indexOf(kw) < 0
        && String(g.gid).indexOf(kw) < 0
        && String(g.session).toLowerCase().indexOf(kw) < 0) return;
    shown++;
    var blOn = arOverrides.hasOwnProperty(String(g.gid))
      ? arOverrides[String(g.gid)] : !inArBlacklist(g);
    rows += '<tr>'
      + '<td class="center" title="关闭 = 完全不理这个群（@ 也不理），立即生效">'
      +   '<label class="switch"><input type="checkbox" data-mute="' + esc(g.session) + '"'
      +   (g.muted ? '' : ' checked') + ' onchange="toggleMute(this)"><span class="sl"></span></label></td>'
      + '<td class="center" title="允许它在没人 @ 时自己插嘴（点右下保存 + 重启 AstrBot 生效）">'
      +   '<input type="checkbox" data-bl="' + esc(g.gid) + '"' + (blOn ? ' checked' : '')
      +   ' onchange="onArChange(this)"></td>'
      + '<td class="gname">' + esc(g.name) + '</td>'
      + '<td><span class="copy-chip" data-v="' + esc(g.gid) + '" onclick="copyText(this.dataset.v)" title="点击复制群 ID">' + esc(g.gid) + ' 📋</span> '
      +   '<span class="copy-chip" data-v="' + esc(g.umo) + '" onclick="copyText(this.dataset.v)" title="点击复制完整 UMO">UMO 📋</span></td>'
      + '</tr>';
  });
  document.getElementById('groupsBody').innerHTML = rows
    || '<tr><td colspan="4" style="color:#7d838c">'
    + (kw ? '没有匹配的群' : '暂无已知群 —— bot 被拉进群后点上方「🔄 刷新名单」') + '</td></tr>';
  var cnt = document.getElementById('groupCount');
  if (cnt) cnt.textContent = kw ? (shown + ' / ' + peopleData.groups.length + ' 个群')
                                : (peopleData.groups.length + ' 个群');
}

function onArChange(cb) {
  arOverrides[cb.getAttribute('data-bl')] = cb.checked;
  markDirty();
}

function inArBlacklist(g) {
  var bl = currentArBlacklist || [];
  return bl.indexOf(String(g.gid)) >= 0 || bl.indexOf(g.umo) >= 0 || bl.indexOf(g.session) >= 0;
}

function toggleMute(cb) {
  var session = cb.getAttribute('data-mute');
  var muted = !cb.checked;
  fetch('/api/session-toggle', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session: session, muted: muted}),
  }).then(function(r){return r.json()}).then(function(res){
    if (res.ok) {
      toast(muted ? '🔇 已关闭该群回复（立即生效）' : '🔊 已恢复该群回复（立即生效）', 'success');
      // 同步进 peopleData，避免搜索重渲染把开关弹回旧状态
      peopleData.groups.forEach(function(g){ if (g.session === session) g.muted = muted; });
    } else {
      toast('❌ 操作失败: ' + res.error, 'error');
      cb.checked = !muted;
    }
  }).catch(function(e){
    toast('❌ 操作失败: ' + e.message, 'error');
    cb.checked = !muted;
  });
}

// ---- 私聊白名单（好友 chip） ----
// 私聊与群白名单是**同一份** id_whitelist —— 保存时统一收集器会把
// 「好友勾选 + 群勾选」合并后整表覆盖（见 collectFriendWhitelist）。

// 白名单条目 → 私聊 UID（好友勾选状态用）。
//
// ⚠️ 存储层存的是**完整 UMO**（`wechat_bridge:FriendMessage:719415740`），
// 因为 AstrBot 私聊只认完整 UMO；裸数字在私聊里永远匹配不上。
// 但 chip 的 data-uid 是纯数字，两者直接比会**永远不相等** →
// 表现就是「设置好的白名单在面板上不见了、重进又得重勾」。
// 所以这里统一抽成 UID 再比。
function wlEntryToUid(x) {
  x = String(x == null ? '' : x).trim();
  if (!x) return '';
  var parts = x.split(':');
  // 形如 platform:MessageType:id → 取最后一段（仅私聊；群 ID 也走这里但不会被好友列表用）
  if (parts.length >= 3) {
    if (parts[1] === 'GroupMessage') return '';   // 群条目不算好友勾选
    return parts[parts.length - 1].trim();
  }
  return x;  // 裸 ID（历史数据 / 群 ID）
}

// 好友 UID 集合（由白名单算出），供勾选判断与保存使用
function wlUidSet(list) {
  var s = {};
  (list || []).forEach(function(x){ var u = wlEntryToUid(x); if (u) s[u] = 1; });
  return s;
}

function fwMatches(p) {
  var kw = (document.getElementById('fwSearch').value || '').toLowerCase().trim();
  if (!kw) return true;
  return p.name.toLowerCase().indexOf(kw) >= 0
      || String(p.wxid || '').toLowerCase().indexOf(kw) >= 0
      || String(p.uid || '').toLowerCase().indexOf(kw) >= 0;
}

function renderFriendList(chipId, values) {
  // 搜索 / 只看已勾 会触发**局部重渲染**，此时不能丢用户已勾的项 ——
  // 所以进函数先把「当前实际勾选」并入 values 快照。
  var live = [];
  document.querySelectorAll('#' + chipId + ' input[type=checkbox]:checked').forEach(function(cb){
    live.push(cb.getAttribute('data-uid'));
  });
  var merged = [];
  (values || []).forEach(function(x){
    x = String(x).trim();
    if (x && merged.indexOf(x) < 0) merged.push(x);
  });
  live.forEach(function(x){ if (merged.indexOf(x) < 0) merged.push(x); });
  currentWhitelist = merged;

  var onlySel = document.getElementById('fwOnlySel') && document.getElementById('fwOnlySel').checked;
  var host = document.getElementById(chipId);
  var selSet = wlUidSet(merged);
  var html = '', shown = 0, selCount = 0;
  peopleData.persons.forEach(function(p){
    if (!p.uid && p.uid !== 0) return;
    var hit = !!selSet[String(p.uid)];
    if (hit) selCount++;
    if (onlySel && !hit) return;
    if (!fwMatches(p)) return;
    shown++;
    html += '<label class="chip' + (hit ? ' on' : '') + '">'
      + '<input type="checkbox" data-uid="' + esc(p.uid) + '"' + (hit ? ' checked' : '')
      + ' onchange="this.parentNode.classList.toggle(\'on\', this.checked);markDirty()"><span class="dot"></span>'
      + esc(p.name) + '</label>';
  });
  if (!shown) {
    var kw = kw0();
    html = '<span style="color:#7d838c;font-size:12px">'
         + (kw ? '没有匹配「' + esc(kw) + '」的好友（换个关键词试试）'
               : '暂无已知好友 —— 让对方先给你发一条消息，再点「🔄 刷新名单」')
         + '</span>';
  }
  host.innerHTML = html;
  var cnt = document.getElementById('fwCount');
  if (cnt) cnt.textContent = '已勾 ' + selCount + ' / 共 ' + peopleData.persons.length + ' 人' + (onlySel ? '（只看已勾）' : '');
}

function kw0(){
  var e = document.getElementById('fwSearch');
  return e ? e.value.trim() : '';
}

// 收集私聊白名单：好友勾选 + （群视图里勾的、不是已知好友 UID 的条目也要保住）
//
// ⚠️ 关键：搜索框会把不匹配的好友**从 DOM 里移除**。若只看 DOM 里的 checked，
// 被筛掉的那些已勾好友就会在保存时静默丢失。所以以 currentWhitelist（缓存）
// 为基准，再用 DOM 里的勾选状态**同步**：当前可见的按可见的来，不可见的保留缓存。
function collectFriendWhitelist() {
  // 以缓存为基准，但**剔除**好友视图管辖的条目（裸 UID 与私聊 UMO），
  // 好友勾选一律重新生成 —— 否则会同时留下旧 UMO 和新勾的裸 ID 两份重复项。
  var base = (currentWhitelist || []).filter(function(x){
    var s = String(x).trim();
    if (!s) return false;
    if (s.indexOf(':') >= 0) return s.split(':')[1] === 'GroupMessage';  // 只留群 UMO
    // 裸 ID：已知群保留；其余视为好友旧条目，丢弃后重建
    return peopleData.groups.some(function(g){ return String(g.gid) === s; });
  });
  var out = base.slice();
  var seen = wlUidSet(out);
  function push(v) { v = String(v == null ? '' : v).trim(); if (v && !seen[v]) { seen[v] = 1; out.push(v); } }

  // 1) 当前可见 chip：以 DOM 勾选为准（含取消勾选）
  document.querySelectorAll('#fw_friends input[type=checkbox]').forEach(function(cb){
    var uid = String(cb.getAttribute('data-uid') || '').trim();
    if (!uid) return;
    if (cb.checked) push(uid);
    else {  // 取消勾选：把该好友的旧条目（裸 ID 或 UMO）都移除
      for (var i = out.length - 1; i >= 0; i--) {
        if (wlEntryToUid(out[i]) === uid && String(out[i]).indexOf(':') >= 0) out.splice(i, 1);
      }
    }
  });
  // 2) 缓存里已勾但当前不可见（被搜索框筛掉）的好友：保留
  (currentWhitelist || []).forEach(function(x){
    var u = wlEntryToUid(x);
    if (!u) return;
    var isGroup = peopleData.groups.some(function(g){ return String(g.gid) === u; });
    if (!isGroup) push(u);
  });
  return out;
}

// 私聊白名单开关
function syncWlEnable(el) {
  markDirty();
}

// ---- 会话检索风格 ----
function styleOptionHtml(style, current) {
  var selected = style === current ? ' selected' : '';
  return '<option value="' + esc(style) + '"' + selected + '>' + esc(style) + '</option>';
}

function renderHumanizerStyles() {
  if (!peopleData) return;
  var h = peopleData.humanizer || {};
  var styles = h.styles || [];
  var kw = ((document.getElementById('hsSearch') || {}).value || '').toLowerCase().trim();
  var onlyCustom = document.getElementById('hsOnlyCustom') && document.getElementById('hsOnlyCustom').checked;
  var rows = '', custom = 0;
  (h.sessions || []).forEach(function(item){
    var cur = humanizerStyleOverrides.hasOwnProperty(item.umo)
      ? humanizerStyleOverrides[item.umo] : '__global__';
    if (cur !== '__global__') custom++;
    if (onlyCustom && cur === '__global__') return;
    if (kw && item.name.toLowerCase().indexOf(kw) < 0
        && item.umo.toLowerCase().indexOf(kw) < 0) return;
    var opts = '<option value="__global__"' + (cur === '__global__' ? ' selected' : '') + '>跟随全局（' + esc(h.global_style || '-') + '）</option>';
    styles.forEach(function(style){ opts += styleOptionHtml(style, cur); });
    rows += '<tr>'
      + '<td><span class="set-note">' + (item.kind === 'group' ? '群' : '私聊') + '</span> ' + esc(item.name) + '</td>'
      + '<td><select data-umo="' + esc(item.umo) + '" onchange="onHumanizerStyleChange(this)" style="width:100%">' + opts + '</select></td>'
      + '<td><span class="copy-chip" data-v="' + esc(item.umo) + '" onclick="copyText(this.dataset.v)" title="点击复制完整 UMO">' + esc(item.umo) + ' 📋</span></td>'
      + '</tr>';
  });
  document.getElementById('hsBody').innerHTML = rows
    || '<tr><td colspan="3" style="color:#7d838c">' + (kw ? '没有匹配的会话' : '暂无可用风格或会话') + '</td></tr>';
  var cnt = document.getElementById('hsCount');
  if (cnt) cnt.textContent = (h.available ? (custom + ' 个自定义 / ' + (h.sessions || []).length + ' 个会话') : '未找到人类风格插件配置');
}

function onHumanizerStyleChange(sel) {
  var umo = sel.getAttribute('data-umo');
  var val = sel.value;
  if (val === '__global__') delete humanizerStyleOverrides[umo];
  else humanizerStyleOverrides[umo] = val;
  humanizerStyleDirty = true;
  markDirty();
  var cnt = document.getElementById('hsCount');
  if (cnt) cnt.textContent = Object.keys(humanizerStyleOverrides).length + ' 个自定义 / ' + ((peopleData.humanizer || {}).sessions || []).length + ' 个会话';
}

// ---- 统一保存 ----
// 一次写入：管理员（/api/admins）+ 私聊/群白名单 + 随机插话（/api/astrbot）。
// 「插嘴」列取 arOverrides（用户改过的行）∪ 服务端黑名单（没改过的行），
// 保证被搜索筛掉的群不会被静默改状态。
function saveAll() {
  if (!peopleData) { toast('数据还没加载完，稍等一下再保存', 'error'); return; }
  scanAdminChecks();
  var bl = [];
  peopleData.groups.forEach(function(g){
    var on = arOverrides.hasOwnProperty(String(g.gid))
      ? arOverrides[String(g.gid)] : !inArBlacklist(g);
    if (!on) bl.push(String(g.gid));
  });
  var body = {
    id_whitelist_enable: document.getElementById('fw_enable').value === '1',
    // ⚠️ 私聊与群共用同一份 id_whitelist：统一收集器会合并两边勾选，
    // 并把好友规整成完整 UMO（裸 UID 在私聊里永远匹配不上）。
    id_whitelist: collectFriendWhitelist(),
    ar_enable: document.getElementById('ab_ar_enable').value === '1',
    ar_possibility: parseFloat(document.getElementById('ab_ar_poss').value),
    ar_blacklist: bl,
  };
  // Do not let an unavailable/misconfigured humanizer block unrelated saves.
  // Only submit this field when the user changed it. Unchanged stale data must
  // not block unrelated settings when a style profile was deleted externally.
  var savedHumanizerStyles = humanizerStyleDirty;
  if (savedHumanizerStyles) {
    body.humanizer_style_overrides = humanizerStyleOverrides;
  }
  var btn = document.getElementById('abSaveBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 保存中…'; }
  Promise.all([
    fetch('/api/admins', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({wxids: peopleData.admins.slice()})}).then(function(r){return r.json()}),
    fetch('/api/astrbot', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)}).then(function(r){return r.json()}),
  ]).then(function(res){
    if (btn) { btn.disabled = false; btn.textContent = '💾 保存'; }
    var a = res[0] || {}, c = res[1] || {};
    if (a.ok && c.ok) {
      peopleDirty = false;
      arOverrides = {};
      currentArBlacklist = bl.slice();
      updateDirtyHint();
      if (a.admins) { peopleData.admins = a.admins; renderPeople(); }
      humanizerStyleDirty = false;
      if (savedHumanizerStyles && peopleData.humanizer) {
        peopleData.humanizer.overrides = JSON.parse(JSON.stringify(humanizerStyleOverrides));
        renderHumanizerStyles();
      }
      showMsg('abMsg', '✅ 已保存');
      if (a.synced === false) {
        toast('⚠️ 已保存，但管理员写入 AstrBot 失败：' + (a.message || '?'), 'error');
      } else if (savedHumanizerStyles) {
        toast('✅ 已保存 —— 会话风格立即生效，其余项重启 AstrBot 后生效', 'success');
      } else {
        toast('✅ 已保存 —— 重启 AstrBot 后生效', 'success');
      }
      showRestartNeeded();
    } else {
      var errs = [a.error, c.error].filter(Boolean).join('；');
      showMsg('abMsg', '❌ 保存失败');
      toast('❌ 保存失败: ' + (errs || '未知错误'), 'error');
    }
  }).catch(function(e){
    if (btn) { btn.disabled = false; btn.textContent = '💾 保存'; }
    showMsg('abMsg', '❌ 保存失败');
    toast('❌ 保存失败: ' + e.message, 'error');
  });
}

// ---- 重启 AstrBot ----
// 后端后台线程干活，这里轮询状态显示进度。
// 重启期间桥接会自动断开再重连 AstrBot（ob_client.py 有重连循环），无需干预。
var _restartTimer = null;

function restartAstrbot() {
  var btn = document.getElementById('abRestartBtn');
  if (btn && btn.disabled) return;
  if (!confirm('确定重启 AstrBot 吗？\n\n约需 10-25 秒，期间机器人暂时不回复消息。')) return;
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 重启中…'; }
  pollRestartState();

  fetch('/api/astrbot-restart', {
    method:'POST', headers:{'Content-Type':'application/json'}, body: '{}',
  }).then(function(r){return r.json()}).then(function(res){
    if (!res.ok) {
      toast('❌ 重启失败: ' + res.error, 'error');
      endRestartPoller();
    } else {
      toast('🔄 已开始重启 AstrBot，约 10-25 秒', 'info');
      if (!_restartTimer) _restartTimer = setInterval(pollRestartState, 1200);
    }
  }).catch(function(e){
    toast('❌ 请求失败: ' + e, 'error');
    endRestartPoller();
  });
}

function pollRestartState() {
  fetch('/api/astrbot-status').then(function(r){return r.json()}).then(function(s){
    var el = document.getElementById('abRestartState');
    var btn = document.getElementById('abRestartBtn');
    if (el) {
      el.textContent = (s.message || '') + (s.listening ? '（端口 ' + s.port + ' 在线）' : '');
      el.style.color = s.phase === 'failed' ? '#b5524a'
                     : s.phase === 'done' ? '#5f8f5f' : '#464b52';
    }
    if (s.phase === 'done' || s.phase === 'failed') {
      if (btn) { btn.disabled = false; btn.textContent = '🔄 重启 AstrBot'; }
      if (s.phase === 'done') {
        toast('✅ AstrBot 已重启完成', 'success');
        hideRestartNeeded();
      } else {
        toast('❌ 重启失败：' + (s.message || '看 astrbot_run.log'), 'error');
      }
      endRestartPoller();
    } else if (btn && s.running) {
      btn.disabled = true;
      btn.textContent = '⏳ 重启中…';
    }
  }).catch(function(){ /* 重启中面板自身不受影响，忽略瞬时错误 */ });
}

function endRestartPoller() {
  if (_restartTimer) { clearInterval(_restartTimer); _restartTimer = null; }
}

function showRestartNeeded() {
  var el = document.getElementById('wlRestartWarn');
  if (el) el.classList.add('show');
  var btn = document.getElementById('abRestartBtn');
  if (btn) btn.classList.add('need-restart');
}

function hideRestartNeeded() {
  var el = document.getElementById('wlRestartWarn');
  if (el) el.classList.remove('show');
  var btn = document.getElementById('abRestartBtn');
  if (btn) btn.classList.remove('need-restart');
}

// ---- 表单回填（白名单 / 随机插话） ----
function fillAstrbotForm(d) {
  document.getElementById('fw_enable').value = d.id_whitelist_enable ? '1' : '0';
  // 用服务端值重置缓存（重新拉取时旧编辑作废），再渲染好友 chip
  currentWhitelist = (d.id_whitelist || []).map(function(x){ return String(x).trim(); });
  renderFriendList('fw_friends', currentWhitelist);
  document.getElementById('ab_ar_enable').value = d.ar_enable ? '1' : '0';
  document.getElementById('ab_ar_poss').value = d.ar_possibility;
}

// ===== 自动获取机器人身份 =====
var detectBusy = false;

function detectBot(auto) {
  if (detectBusy) return;
  var msgEl = document.getElementById('detectMsg');
  var btn = document.getElementById('btnDetectBot');
  if (!msgEl) return;
  detectBusy = true;
  if (btn) btn.disabled = true;
  msgEl.textContent = '🔍 正在从微信读取…';

  fetch('/api/detect-bot').then(function(r){return r.json()}).then(function(d){
    detectBusy = false;
    if (btn) btn.disabled = false;
    if (!d.ok) {
      msgEl.textContent = '❌ ' + (d.error || '获取失败，请确认 WeFlow 已登录');
      return;
    }
    var wxEl = document.getElementById('cfg_bot_wxid');
    var nnEl = document.getElementById('cfg_bot_nicknames');
    var notes = [];
    if (d.wxid) {
      var cur = wxEl ? wxEl.value.trim() : '';
      if (!cur) { wxEl.value = d.wxid; notes.push('wxid 已填入 ' + d.wxid); }
      else if (cur !== d.wxid) {
        notes.push('检测到 ' + d.wxid + '（当前填的是 ' + cur + '）');
        if (!auto) { wxEl.value = d.wxid; notes.push('已替换为检测值'); }
      }
    }
    if (d.nicknames && d.nicknames.length) {
      var curNn = nnEl ? nnEl.value.trim() : '';
      if (!curNn) { nnEl.value = d.nicknames.join(', '); notes.push('昵称已填入 ' + d.nicknames.join('、')); }
      else if (!auto) { nnEl.value = d.nicknames.join(', '); notes.push('昵称已替换为 ' + d.nicknames.join('、')); }
    }
    msgEl.textContent = notes.length ? ('✅ ' + notes.join('；') + '。记得点保存') : '✅ 没找到更合适的值';
  }).catch(function(e){
    detectBusy = false;
    if (btn) btn.disabled = false;
    msgEl.textContent = '❌ 请求失败: ' + e.message;
  });
}

