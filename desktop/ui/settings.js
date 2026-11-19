var CFG_GROUPS = [
  {tier:'common',icon:'',title:'WeRC 授权',sub:'在 WeRC 桌面端授权当前 Bot；不会自动连接微信。',fields:[{key:'werc_base_url',label:'本机服务地址',type:'text'},{key:'werc_account_id',label:'授权账号 ID',type:'text'},{key:'werc_token',label:'Bot 令牌',type:'password'}]},
  {tier:'common', icon:'🔗', title:'消息链路', sub:'读微信消息的后端 + 回微信消息的方式（改完保存并重新打开桌面端生效）', fields:[
    {key:'message_source', label:'接收端（读微信消息用哪个后端）', type:'select', opts:[
      {v:'werc',l:'WeRC · 原生观测'}, {v:'weflow',l:'WeFlow（旧链路，已停维护，需 RunAsDate 冻结时钟）'},
      {v:'alpha',l:'Alpha（WeFlow 继任者，原生 API）'}], restart:1},
    {key:'send_method', label:'发送端（回微信消息用什么）', type:'select', opts:[
      {v:'werc',l:'WeRC · 授权发件箱'}, {v:'uia',l:'UIA 自动化（默认，不花钱，微信 PC 客户端）'},
      {v:'alpha_api',l:'Alpha API（需 ¥100/月激活「发送文字消息」）'}], restart:1},
    {type:'info', text:'<b>端口提醒</b>：WeFlow 默认 5031、Alpha 默认也是 5031，两个同开会冲突 —— 本机把 Alpha 放在了 <b>5030</b>（设置 → 接口与集成 → 本机 HTTP API）。详见 docs/Alpha接入说明.md。'},
  ]},
  {tier:'common', icon:'🐱', title:'机器人身份', sub:'它在微信里叫什么、被什么名字唤醒', fields:[
    {type:'detect', label:'自动获取（从已登录的微信读取，改完仍可手动改）'},
    {key:'bot_nicknames', label:'机器人昵称（逗号分隔，@ 其中任何一个都会唤醒）', type:'text', ph:'你的机器人昵称'},
    {key:'bot_wxid', label:'机器人自己的 wxid', type:'text', ph:'wxid_xxx', restart:1},
  ]},
  {tier:'common', icon:'💬', title:'消息行为', sub:'它怎么读群消息、怎么回话', fields:[
    {key:'buffer_seconds', label:'消息缓冲（秒）：同一个人连发多条时，等这么久再合并成一条', type:'number', ph:'5'},
    {key:'group_reply_mode', label:'群聊模式（控制台也能一键切换，此项立即生效）', type:'select', opts:[
      {v:'all',l:'标准模式（@必回；非@消息交给 AstrBot 掷骰决定）'},
      {v:'batch',l:'批处理（一段时间内整群消息合并成一条）'}]},
    {key:'mention_as_text', label:'把 @ 转成文字「@昵称」（微信原生 @ 发不出去时的替代方案）', type:'toggle', def:'true'},
    {key:'quote_reply_prefix', label:'引用回复转文字前缀（把「回复某条消息」变成〔回复 某某：原文〕）', type:'toggle', def:'false'},
    {key:'quote_reply_native', label:'原生引用气泡（右键原消息→引用，2026-09-15 已打通；引用时要先横向找准气泡，会多花 1~6 秒，找不到会自动降级普通发送）', type:'toggle', def:'false'},
  ]},
  {tier:'common', icon:'🖼️', title:'图片', sub:'群里发图怎么处理', fields:[
    {key:'image_mention_window', label:'群图片等待 @ 的时间窗（秒）：图先到，同一人在窗口内 @ 才会读图', type:'number', ph:'120'},
    {key:'image_max_bytes', label:'单张图片大小上限（字节），超过就跳过', type:'number', ph:'8388608'},
    {type:'info', text:'<b>「怎么理解图片」不在这里配</b>：图片默认原样转交 AstrBot，由 AstrBot 面板(6185) → 配置 里的主模型（多模态）或图片转述模型决定。下面「上游遗留」里的桥接侧转述是备用方案，默认关闭。'},
  ]},
  {tier:'adv', icon:'🔌', title:'连接', sub:'各后端的地址与令牌（消息源/发送端在上面「消息链路」选）', fields:[
    {key:'alpha_base_url', label:'Alpha 地址', type:'text', ph:'http://127.0.0.1:5030', restart:1},
    {key:'alpha_access_token', label:'Alpha Access Token', type:'password', ph:'输入 Alpha Token', restart:1},
    {key:'alpha_account_id', label:'Alpha 账号 ID（留空 = 自动取唯一就绪账号）', type:'text', ph:'留空自动检测', restart:1},
    {key:'weflow_base_url', label:'WeFlow 地址', type:'text', ph:'http://127.0.0.1:5031', restart:1},
    {key:'access_token', label:'WeFlow Access Token', type:'password', ph:'输入 Token', restart:1},
    {key:'onebot_token',label:'OneBot 访问令牌（可选）',type:'password',restart:1},
    {key:'onebot_ws_url', label:'OneBot v11 反向 WebSocket 地址', type:'text', ph:'ws://127.0.0.1:11229/ws', restart:1},
    {key:'astrbot_attachments', label:'附件目录（AstrBot 存图片的路径）', type:'text', ph:'C:\astrbot\attachments'},
    {key:'astrbot_config_file', label:'AstrBot 主配置路径（成员与权限页同步用）', type:'text', ph:'留空 = 通用模式，不管理 AstrBot', restart:1},
  ]},
  {tier:'adv', icon:'🧰', title:'面板与排障', sub:'面板端口、日志开关', fields:[
    {key:'web_port', label:'Web 面板端口', type:'number', ph:'8766', restart:1},
    {type:'info',text:'桌面控制接口仅监听 127.0.0.1，不开放局域网访问。'},
    {key:'log_skipped_messages', label:'记录被跳过的消息（排障时强烈建议开着）', type:'toggle', def:'true'},
    {key:'switch_method', label:'联系人切换方式（UIA 发送时怎么找到聊天窗口）', type:'select', opts:[
      {v:'auto',l:'自动（先会话列表，找不到再搜索）'},
      {v:'list',l:'仅会话列表点击'},
      {v:'search',l:'仅 Ctrl+F 搜索'}]},
  ]},
  {tier:'legacy', icon:'📦', title:'发送参数与上游遗留（默认不动）', sub:'发送端在上面「消息链路」选；这里只有细节参数和历史遗留', fields:[
    {key:'alpha_send_wait_seconds', label:'Alpha 发送等待秒数（0~120，仅 send_method=alpha_api 时用）', type:'number', ph:'30', restart:1},
    {key:'weflow_send_api', label:'WeFlow 发送 API（历史遗留，代码已不使用）', type:'text', ph:'http://127.0.0.1:5031/api/v1/message'},
    {key:'image_caption_model', label:'桥接侧图片转述模型名（留空 = 不启用，走 AstrBot 配置）', type:'text', ph:'留空即可'},
    {key:'image_caption_provider', label:'转述服务', type:'select', opts:[{v:'ollama',l:'Ollama 本地'},{v:'openai',l:'OpenAI 兼容'}]},
    {key:'image_caption_api_key', label:'转述 API Key（OpenAI 模式）', type:'password', ph:'sk-xxx'},
    {key:'image_caption_api_base', label:'转述 API 地址（OpenAI 模式）', type:'text', ph:'https://api.moonshot.cn/v1'},
    {key:'image_caption_prompt', label:'转述提示词', type:'textarea', ph:'请用中文描述...'},
    {key:'ollama_base_url', label:'Ollama 地址', type:'text', ph:'http://127.0.0.1:61000'},
    {key:'ollama_timeout', label:'Ollama 超时（秒）', type:'number', ph:'60'},
  ]},
];

// ===== 设置加载 =====
function loadConfig() {
  fetch('/api/config').then(function(r){return r.json()}).then(function(cfg){
    cfg.onebot_ws_url ||= cfg.astrbot_ob_url;
    renderConfigForm(cfg);
    filterSettings();
    // wxid 没填 → 自动从微信读一次（用户仍可手动改，自动值只填入不保存）
    if (cfg.message_source !== 'werc' && !String(cfg.bot_wxid || '').trim()) detectBot(true);
  }).catch(function(e){
    document.getElementById('settingsForm').innerHTML = '<p style="color:#b5524a;font-size:13px;">加载配置失败: ' + e.message + '</p>';
  });
}

function renderConfigForm(cfg) {
  var TIER_META = {
    common: null,
    adv: {icon:'🔧', title:'进阶', note:'连接地址、端口、日志 —— 一般不用动'},
    legacy: {icon:'📦', title:'上游遗留', note:'默认关闭的备用方案，保持原样即可'},
  };
  var html = '';

  CFG_GROUPS.forEach(function(g){
    var meta = TIER_META[g.tier];
    var inner = '<div class="settings-row">';
    g.fields.forEach(function(f){ inner += renderField(f, cfg); });
    inner += '</div>';

    if (!meta) {
      html += '<div class="card" data-tier="common"><h3><span class="ic">' + g.icon + '</span>' + g.title + '</h3>'
        + '<div class="card-sub">' + g.sub + '</div>' + inner + '</div>';
    } else {
      html += '<details class="tier' + (g.tier === 'legacy' ? ' warn' : '') + '" data-tier="' + g.tier + '">'
        + '<summary><span class="arrow">▶</span>' + meta.icon + ' ' + g.title
        + ' <span class="count">' + meta.note + '</span></summary>'
        + '<div class="tier-body">' + inner + '</div></details>';
    }
  });

  document.getElementById('settingsForm').innerHTML = html;
}

// 同步开关右侧的「开/关」文字。
// 必须用 class 精确定位，不能用 span:last-child —— 那个选择器会先命中 .switch
// 内部的滑块 <span class="sl">（它是 .switch 的最后一个子元素），把文字写进滑块里，
// 表现为「字叠在圆点上、还被圆点遮住一半」（2026-09-15 用户反馈）。
function syncSwitchText(cb) {
  var row = cb.closest('.switch-row');
  var t = row && row.querySelector('.st');
  if (t) t.textContent = cb.checked ? '开' : '关';
}

function renderField(f, cfg) {
  if (f.type === 'detect') {
    return '<div class="settings-field wide"><label>' + f.label + '</label>'
      + '<div class="toolbar"><button class="btn btn-outline btn-sm" id="btnDetectBot" onclick="detectBot(false)">🔍 从微信自动获取</button>'
      + '<span id="detectMsg" class="field-hint">没填 wxid 时会自动跑一次</span></div></div>';
  }
  if (f.type === 'info') {
    return '<div class="info-line">' + f.text + '</div>';
  }
  var val = cfg[f.key] !== undefined ? cfg[f.key] : (f.def !== undefined ? f.def : '');
  if (f.key === 'group_reply_mode' && val === 'mention') val = 'all'; // 旧值兼容
  if (typeof val === 'boolean') val = val ? 'true' : 'false';
  if (Array.isArray(val)) val = val.join(', ');

  var badge = f.restart ? '<span class="restart-badge">需重启</span>' : '';
  var label = '<label>' + f.label + badge + '</label>';
  var id = ' id="cfg_' + f.key + '" data-key="' + f.key + '"';

  if (f.type === 'toggle') {
    var on = (val === true || val === 'true' || val === '1');
    return '<div class="settings-field wide"><label>' + f.label + badge + '</label>'
      + '<label class="switch-row"><span class="switch"><input type="checkbox"' + id
      + (on ? ' checked' : '')
      + ' onchange="syncSwitchText(this)">'
      + '<span class="sl"></span></span>'
      + '<span class="st">' + (on ? '开' : '关') + '</span></label></div>';
  }
  if (f.type === 'select') {
    var s = '<div class="settings-field">' + label + '<select' + id + '>';
    f.opts.forEach(function(o){ s += '<option value="' + o.v + '"' + (val == o.v ? ' selected' : '') + '>' + o.l + '</option>'; });
    return s + '</select></div>';
  }
  if (f.type === 'textarea') {
    return '<div class="settings-field wide">' + label + '<textarea' + id + ' rows="2" placeholder="' + esc(f.ph || '') + '">' + esc(val) + '</textarea></div>';
  }
  var t = f.type === 'number' ? 'number' : (f.type === 'password' ? 'password' : 'text');
  return '<div class="settings-field">' + label + '<input type="' + t + '"' + id + ' value="' + esc(val)
    + '" placeholder="' + esc(f.ph || '') + '"></div>';
}

function filterSettings() {
  var kw = (document.getElementById('cfgSearch').value || '').trim().toLowerCase();
  var form = document.getElementById('settingsForm');
  var total = 0, shown = 0;
  form.querySelectorAll('[data-tier]').forEach(function(block){
    var hit = !kw;
    block.querySelectorAll('.settings-field').forEach(function(fd){
      var match = !kw || fd.textContent.toLowerCase().indexOf(kw) >= 0;
      fd.style.display = match ? '' : 'none';
      if (match) { hit = true; shown++; }
    });
    block.querySelectorAll('.info-line').forEach(function(fd){
      var match = !kw || fd.textContent.toLowerCase().indexOf(kw) >= 0;
      fd.style.display = match ? '' : 'none';
      if (match) hit = true;
    });
    if (kw) {
      block.style.display = hit ? '' : 'none';
      if (block.tagName === 'DETAILS') block.open = hit;
    } else {
      block.style.display = '';
      if (block.tagName === 'DETAILS') block.open = false;
    }
  });
  CFG_GROUPS.forEach(function(g){ g.fields.forEach(function(f){ if (f.key) total++; }); });
  document.getElementById('cfgSearchCount').textContent = kw ? (shown + ' / ' + total + ' 项匹配') : '';
}

// ===== 保存配置 =====
var BOOL_KEYS = ['quote_reply_prefix', 'quote_reply_native', 'mention_as_text', 'log_skipped_messages'];

function saveConfig() {
  var fields = document.querySelectorAll('#settingsForm [id^="cfg_"]');
  var data = {};
  fields.forEach(function(el){
    var key = el.getAttribute('data-key') || el.id.replace('cfg_','');
    var val;
    if (el.type === 'checkbox') val = el.checked ? 'true' : 'false';
    else val = el.value.trim();
    if (el.type === 'number') val = Number(val) || 0;
    if (BOOL_KEYS.indexOf(key) >= 0) val = (val === 'true' || val === '1');
    if (key === 'bot_nicknames') val = val ? val.split(/[,，]\s*/).filter(Boolean) : [];
    data[key] = val;
  });

  fetch('/api/config', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(data),
  }).then(function(r){return r.json()}).then(function(res){
    if (res.ok) {
      showMsg('saveMsg', '✅ 已保存，重新打开桌面端后生效');
      toast('✅ 配置已保存', 'success');
    } else {
      showMsg('saveMsg', '❌ 保存失败');
    }
  }).catch(function(e){
    showMsg('saveMsg', '❌ 保存失败: ' + e.message);
  });
}

function importWeRC(){
  const box=document.getElementById('wercBundle');try{
    const d=JSON.parse(box.value),u=new URL(d.api_url),token=/^Bearer (\S+)$/.exec(d.headers?.Authorization||'');
    if(d.platform!=='WeRC'||!['127.0.0.1','localhost','[::1]'].includes(u.hostname)||!['http:','https:'].includes(u.protocol)||u.username||u.password||u.search||u.hash||!['','/','/api/v1','/api/v1/'].includes(u.pathname)||!token||!d.account_id)throw Error('不是有效的本机 WeRC 授权配置');
    const values={werc_base_url:u.origin+'/api/v1',werc_token:token[1],werc_account_id:d.account_id,message_source:'werc',send_method:'werc'};
    for(const [k,v] of Object.entries(values))document.getElementById('cfg_'+k).value=v;
    box.value='';toast('已填入；可先测试连接，再保存配置。','success');
  }catch(e){toast('导入失败：请粘贴 WeRC 复制的原始 JSON。','error')}
}
async function testWeRC(){try{const cfg={};for(const k of ['werc_base_url','werc_account_id','werc_token'])cfg[k]=document.getElementById('cfg_'+k).value;const d=await(await fetch('/api/test-werc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)})).json();toast(d.message||d.error,d.ok?'success':'error')}catch(e){toast('连接测试失败','error')}}
