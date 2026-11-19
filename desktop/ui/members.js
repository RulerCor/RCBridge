let peopleData = null, peopleDirty = false, refreshBusy = false;
let admins = new Set(), friendChanges = new Map();
const memberEl = id => document.getElementById(id);

async function peopleRequest(path, data) {
  const r = await fetch(path, data === undefined ? undefined : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data),
  });
  const result = await r.json();
  if (!r.ok || result.ok === false) throw Error(result.error || '操作失败');
  return result;
}

function switchMembersTab(name) {
  if (name !== 'groups' && !peopleData?.astrbot_available) name = 'groups';
  document.querySelectorAll('#page-members .seg').forEach(b => b.classList.toggle('active', b.dataset.sub === name));
  document.querySelectorAll('#page-members .members-sub').forEach(p => p.classList.toggle('active', p.id === 'sub-' + name));
  memberEl('peopleSaveBar').hidden = name === 'groups';
  history.replaceState(null, '', '#members/' + name);
}

function loadPeopleData(d) {
  if (peopleDirty && peopleData) {
    peopleData.groups = d.groups;
  } else {
    peopleData = d;
    admins = new Set(d.admins);
    friendChanges.clear();
    memberEl('fw_enable').checked = d.id_whitelist_enable;
    document.querySelectorAll('#page-members .seg:not([data-sub="groups"])').forEach(el => { el.hidden = !d.astrbot_available; });
    memberEl('membersBadge').textContent = d.astrbot_available ? 'AstrBot 权限' : d.astrbot_enabled ? 'AstrBot 配置不可用' : '群回复即时生效';
    renderFriends(); renderAdmins();
  }
  memberEl('btnImportGroupNames').hidden = memberEl('btnSyncGroupNames').hidden = !d.group_name_import;
  renderGroups();
}

async function switchTabMembers() {
  try {
    loadPeopleData(await peopleRequest('/api/people'));
    const sub = location.hash.split('/')[1];
    switchMembersTab(['friends', 'admins'].includes(sub) ? sub : 'groups');
    await refreshPeople();
  } catch (e) { memberEl('membersBadge').textContent = e.message; }
}

async function refreshPeople() {
  if (refreshBusy) return;
  refreshBusy = true;
  const btn = memberEl('btnRefreshPeople'), notice = memberEl('groupNotice');
  btn.disabled = true; btn.textContent = '刷新中…';
  notice.textContent = '';
  try {
    let failure;
    try { await peopleRequest('/api/refresh-people', {}); } catch (e) { failure = e; }
    loadPeopleData(await peopleRequest('/api/people'));
    if (failure) throw failure;
  } catch (e) {
    notice.textContent = '刷新失败：' + e.message;
  } finally {
    refreshBusy = false; btn.disabled = false; btn.textContent = '刷新名单';
  }
}

async function syncGroupNames() {
  const btn = memberEl('btnSyncGroupNames'), notice = memberEl('groupNotice');
  btn.disabled = true;
  notice.textContent = '正在从 WeRC 同步群名…';
  try {
    const d = await peopleRequest('/api/group-names/sync', {});
    loadPeopleData(await peopleRequest('/api/people'));
    notice.textContent = d.imported ? `已同步 ${d.imported} 个群名。` : 'WeRC 暂无可同步的群名，已保留已有名称。';
  } catch (e) { notice.textContent = '同步失败：' + e.message; }
  finally { btn.disabled = false; }
}

async function importGroupNames(input) {
  const file = input.files[0];
  input.value = '';
  if (!file) return;
  const btn = memberEl('btnImportGroupNames');
  btn.disabled = true;
  try {
    if (!file.size || file.size > 32 * 1024 * 1024) throw Error('请选择不超过 32 MB 的通讯录 JSON。');
    const r = await fetch('/api/group-names/import', {method:'POST', headers:{'Content-Type':'application/json'}, body:file});
    const d = await r.json();
    if (!r.ok || !d.ok) throw Error(d.error || '导入失败');
    loadPeopleData(await peopleRequest('/api/people'));
    toast(`已导入 ${d.imported} 个群名。`, 'success');
  } catch (e) { toast(e.message, 'error'); }
  finally { btn.disabled = false; }
}

function renderGroups() {
  if (!peopleData) return;
  const query = memberEl('groupSearch').value.trim().toLowerCase();
  const groups = peopleData.groups;
  memberEl('groupNameHint').hidden = memberEl('btnImportGroupNames').hidden || !groups.some(g => g.name === g.session);
  const shown = groups.filter(g => [g.name, g.session, g.gid].some(v => String(v).toLowerCase().includes(query)));
  memberEl('groupCount').textContent = query ? `${shown.length} / ${groups.length} 个已知群` : `${groups.length} 个已知群`;
  memberEl('groupsBody').innerHTML = shown.map(g => '<tr>'
    + '<td><input type="checkbox" aria-label="允许回复" data-session="' + esc(g.session) + '"' + (g.muted ? '' : ' checked') + ' onchange="toggleMute(this)"></td>'
    + '<td title="' + esc(g.session) + '">' + (g.name === g.session ? '未获取群名<br><small>' + esc(g.session) + '</small>' : esc(g.name))
    + '</td><td>' + esc(g.gid) + '</td></tr>').join('')
    || '<tr><td colspan="3">' + (query ? '没有匹配的群。' : '暂无已知群。让群成员发一条新消息，再刷新名单。') + '</td></tr>';
}

async function toggleMute(el) {
  const muted = !el.checked, session = el.dataset.session;
  el.disabled = true;
  try {
    await peopleRequest('/api/session-toggle', {session, muted});
    const group = peopleData.groups.find(g => g.session === session);
    if (group) group.muted = muted;
    renderGroups();
  } catch (e) { el.checked = muted; toast(e.message, 'error'); }
  finally { el.disabled = false; }
}

function matchesPerson(p, search) {
  const q = memberEl(search).value.trim().toLowerCase();
  return [p.name, p.wxid, p.uid].some(v => String(v).toLowerCase().includes(q));
}

function friendId(entry) {
  const fields = String(entry).split(':');
  if (fields.length === 1) return fields[0];
  return fields[1] === 'FriendMessage' ? fields.at(-1) : '';
}

function renderFriends() {
  const enabled = new Set(peopleData.id_whitelist.map(friendId));
  memberEl('fw_friends').innerHTML = peopleData.persons.filter(p => p.uid != null && matchesPerson(p, 'fwSearch')).map(p => {
    const uid = String(p.uid), checked = friendChanges.get(uid) ?? enabled.has(uid);
    return '<label class="chip"><input type="checkbox" data-uid="' + esc(uid) + '"' + (checked ? ' checked' : '')
      + ' onchange="friendChanges.set(this.dataset.uid, this.checked);markDirty()">' + esc(p.name) + '</label>';
  }).join('') || '<p>没有可显示的好友。</p>';
}

function renderAdmins() {
  memberEl('peopleList').innerHTML = peopleData.persons.filter(p => matchesPerson(p, 'memberSearch')).map(p =>
    '<label class="chip"><input type="checkbox" data-wxid="' + esc(p.wxid) + '"' + (admins.has(p.wxid) ? ' checked' : '')
      + ' onchange="changeAdmin(this)">' + esc(p.name) + '</label>').join('') || '<p>没有可显示的好友。</p>';
}

function changeAdmin(el) {
  if (el.checked) admins.add(el.dataset.wxid);
  else admins.delete(el.dataset.wxid);
  markDirty();
}

function markDirty() {
  peopleDirty = true;
  memberEl('abSaveBtn').disabled = false;
  memberEl('abStatus').textContent = '有未保存的更改';
}

async function saveAll() {
  memberEl('abSaveBtn').disabled = true;
  try {
    const current = new Set(peopleData.admins);
    if (admins.size !== current.size || [...admins].some(id => !current.has(id))) {
      const result = await peopleRequest('/api/admins', {wxids:[...admins]});
      if (!result.synced) throw Error('桥接已保存，AstrBot 同步失败：' + result.message);
    }
    const enabled = memberEl('fw_enable').checked;
    if (friendChanges.size || enabled !== peopleData.id_whitelist_enable) {
      const data = {id_whitelist_enable:enabled};
      if (friendChanges.size) {
        data.id_whitelist = peopleData.id_whitelist.filter(entry => !friendChanges.has(friendId(entry)));
        for (const [id, checked] of friendChanges) if (checked) data.id_whitelist.push(id);
      }
      await peopleRequest('/api/astrbot', data);
    }
    const latest = await peopleRequest('/api/people');
    peopleDirty = false;
    loadPeopleData(latest);
    memberEl('abStatus').textContent = '已保存，重启 AstrBot 后生效';
  } catch (e) { toast(e.message, 'error'); memberEl('abSaveBtn').disabled = false; }
}

async function restartAstrbot() {
  if (peopleDirty || !confirm('重启期间机器人会暂停回复。现在重启 AstrBot？')) {
    if (peopleDirty) toast('请先保存权限。', 'error');
    return;
  }
  const btn = memberEl('abRestartBtn'), status = memberEl('abStatus');
  btn.disabled = true;
  try {
    await peopleRequest('/api/astrbot-restart', {});
    const poll = async () => {
      try {
        const d = await peopleRequest('/api/astrbot-status');
        status.textContent = d.message || '正在重启…';
        if (d.running) setTimeout(poll, 1200);
        else btn.disabled = false;
      } catch (e) { btn.disabled = false; status.textContent = e.message; }
    };
    await poll();
  } catch (e) { btn.disabled = false; status.textContent = e.message; }
}
