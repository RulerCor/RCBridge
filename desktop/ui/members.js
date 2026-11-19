let peopleData = null, peopleDirty = false, refreshBusy = false;
let admins = new Set(), friendChanges = new Map();
let directoryRows = null, directoryBusy = false, membersSub = 'groups';
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
  if (name === 'directory' ? !peopleData?.friend_directory
      : name !== 'groups' && !peopleData?.astrbot_available) name = 'groups';
  membersSub = name;
  document.querySelectorAll('#page-members .seg').forEach(b => b.classList.toggle('active', b.dataset.sub === name));
  document.querySelectorAll('#page-members .members-sub').forEach(p => p.classList.toggle('active', p.id === 'sub-' + name));
  memberEl('peopleSaveBar').hidden = !['friends', 'admins'].includes(name);
  updateMembersActions();
  history.replaceState(null, '', '#members/' + name);
  if (name === 'directory' && directoryRows === null) refreshDirectory();
}

function updateMembersActions() {
  const isDirectory = membersSub === 'directory';
  memberEl('btnImportGroupNames').hidden = memberEl('btnSyncGroupNames').hidden = isDirectory || !peopleData?.group_name_import;
  const busy = isDirectory ? directoryBusy : refreshBusy;
  const btn = memberEl('btnRefreshPeople');
  btn.disabled = busy;
  btn.textContent = busy ? '刷新中…' : '刷新名单';
}

function loadPeopleData(d) {
  if (peopleDirty && peopleData) {
    peopleData.groups = d.groups;
  } else {
    peopleData = d;
    admins = new Set(d.admins);
    friendChanges.clear();
    memberEl('fw_enable').checked = d.id_whitelist_enable;
    document.querySelectorAll('#page-members .seg[data-sub="friends"], #page-members .seg[data-sub="admins"]').forEach(el => { el.hidden = !d.astrbot_available; });
    memberEl('membersBadge').textContent = d.astrbot_available ? 'AstrBot 权限' : d.astrbot_enabled ? 'AstrBot 配置不可用' : '群回复即时生效';
    renderFriends(); renderAdmins();
  }
  document.querySelector('#page-members .seg[data-sub="directory"]').hidden = !d.friend_directory;
  updateMembersActions();
  renderGroups();
}

async function switchTabMembers() {
  try {
    loadPeopleData(await peopleRequest('/api/people'));
    const sub = location.hash.split('/')[1];
    switchMembersTab(['directory', 'friends', 'admins'].includes(sub) ? sub : 'groups');
    if (membersSub !== 'directory') await refreshPeople();
  } catch (e) { memberEl('membersBadge').textContent = e.message; }
}

function refreshMembersView() {
  return membersSub === 'directory' ? refreshDirectory() : refreshPeople();
}

async function refreshDirectory() {
  if (directoryBusy) return;
  directoryBusy = true;
  updateMembersActions();
  const notice = memberEl('directoryNotice');
  notice.textContent = '正在读取 WeRC 好友目录…';
  try {
    const data = await peopleRequest('/api/friend-directory');
    directoryRows = data.friends;
    notice.textContent = '来自 WeRC 的好友目录，仅供查看。';
  } catch (e) {
    directoryRows = null;
    notice.textContent = e.message;
  } finally {
    directoryBusy = false;
    updateMembersActions();
    renderDirectory();
  }
}

function renderDirectory() {
  const body = memberEl('directoryBody'), count = memberEl('directoryCount');
  if (directoryRows === null) {
    body.innerHTML = '';
    count.textContent = '';
    return;
  }
  const query = memberEl('directorySearch').value.trim().toLowerCase();
  const rows = directoryRows.filter(f => [f.nickname, f.remark, f.user_id].some(v => String(v).toLowerCase().includes(query)));
  count.textContent = query ? `${rows.length} / ${directoryRows.length} 位好友` : `${rows.length} 位好友`;
  body.innerHTML = rows.map(f => `<tr><td>${esc(f.nickname || '—')}</td><td>${esc(f.remark || '—')}</td><td>${esc(f.user_id)}</td></tr>`).join('')
    || `<tr><td colspan="3">${query ? '没有匹配的好友。' : 'WeRC 本地通讯录没有可显示的好友。'}</td></tr>`;
}

async function refreshPeople() {
  if (refreshBusy) return;
  refreshBusy = true;
  const notice = memberEl('groupNotice');
  updateMembersActions();
  notice.textContent = '';
  try {
    let failure;
    try { await peopleRequest('/api/refresh-people', {}); } catch (e) { failure = e; }
    loadPeopleData(await peopleRequest('/api/people'));
    if (failure) throw failure;
  } catch (e) {
    notice.textContent = '刷新失败：' + e.message;
  } finally {
    refreshBusy = false;
    updateMembersActions();
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
