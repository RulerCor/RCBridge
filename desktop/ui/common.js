function toast(msg, type) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type + ' show';
  setTimeout(function(){t.className='toast'}, 2500);
}

function showMsg(id, text) {
  var el = document.getElementById(id);
  el.textContent = text;
  el.className = 'save-msg show';
  setTimeout(function(){el.className='save-msg'}, 3000);
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ===== Tab 切换 =====
function switchTab(name) {
  if(typeof peopleDirty!=='undefined' && peopleDirty && name!=='members' && document.getElementById('page-members').classList.contains('active') && !confirm('成员与权限有未保存的修改，仍要离开？'))return;
  document.querySelectorAll('.tab-page').forEach(function(p){p.classList.remove('active')});
  document.getElementById('page-' + name).classList.add('active');
  document.querySelectorAll('.nav-item').forEach(function(n){n.classList.remove('active')});
  document.querySelector('[data-tab="' + name + '"]').classList.add('active');
  if (name === 'settings') loadConfig();
  if (name === 'members') switchTabMembers();
}

// ===== 面板刷新 =====
var modeMap = {'mention':'标准模式','all':'标准模式','batch':'批处理'};

// 退出归因：显示「上次是怎么退的」，并区分崩溃 / 主动 / 被强杀
function loadExitReason() {
  fetch('/api/exit-reason').then(function(r){return r.json()}).then(function(d){
    if (!d.ok) {
      document.getElementById('erLast').textContent = '读取失败: ' + (d.error || '?');
      return;
    }
    var cur = d.current || {};
    document.getElementById('erUptime').textContent = cur.uptime || '-';
    document.getElementById('erPhase').textContent = cur.phase || '-';

    var el = document.getElementById('erLast');
    var txt = d.last_exit || '（无记录）';
    el.textContent = txt;
    el.style.color = d.forced ? '#b5524a'
                   : (/未捕获异常/.test(txt) ? '#b9802b' : '#5f8f5f');
    if (d.forced) {
      el.textContent = '⚠️ ' + txt + '（上次进程被强杀，未留下任何清理记录）';
    }

    var h = document.getElementById('erHistory');
    h.textContent = (d.history && d.history.length)
      ? d.history.join('\n') : '（暂无记录）';
  }).catch(function(e){
    document.getElementById('erLast').textContent = '请求失败: ' + e;
  });
}

