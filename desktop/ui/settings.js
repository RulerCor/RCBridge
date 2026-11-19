const connectionFields = {
  wercFields: [
    ['werc_base_url', 'WeRC 本机地址'], ['werc_account_id', '账号 ID'], ['werc_token', 'Bot 令牌', 'password'],
  ],
  onebotFields: [
    ['onebot_ws_url', '反向 WebSocket 地址'], ['onebot_token', '访问令牌（可选）', 'password'],
  ],
  advancedFields: [
    ['message_source', '接收来源', 'select', {werc:'WeRC', alpha:'Alpha', weflow:'WeFlow'}],
    ['send_method', '发送方式', 'select', {werc:'WeRC', alpha_api:'Alpha API', uia:'Windows UIA'}],
    ['alpha_base_url', 'Alpha 地址', 'text', null, 'alpha'],
    ['alpha_access_token', 'Alpha 令牌', 'password', null, 'alpha'],
    ['alpha_account_id', 'Alpha 账号 ID（可选）', 'text', null, 'alpha'],
    ['weflow_base_url', 'WeFlow 地址', 'text', null, 'weflow'],
    ['access_token', 'WeFlow 令牌', 'password', null, 'weflow'],
    ['bot_wxid', '机器人微信 ID', 'text', null, 'legacy'],
    ['bot_nicknames', '机器人昵称（逗号分隔）', 'text', null, 'legacy'],
    ['astrbot_config_file', 'AstrBot 配置文件（可选）'],
    ['astrbot_attachments', '本地附件目录（可选）'],
    ['web_port', '本机控制端口', 'number'],
  ],
};
const setting = key => document.getElementById('cfg_' + key);

function renderConnectionFields(cfg) {
  for (const [id, fields] of Object.entries(connectionFields)) {
    const nodes = fields.map(([key, title, type = 'text', options, condition]) => {
      const field = document.createElement('div');
      if (condition) field.dataset.connection = condition;
      const label = document.createElement('label');
      label.htmlFor = 'cfg_' + key;
      label.textContent = title;
      const input = document.createElement(options ? 'select' : 'input');
      input.id = label.htmlFor;
      if (options) {
        for (const [value, text] of Object.entries(options)) input.add(new Option(text, value));
        input.addEventListener('change', showConnectionFields);
      } else {
        input.type = type;
        if (type === 'password') input.autocomplete = 'off';
        if (type === 'number') { input.min = 1; input.max = 65535; }
      }
      const value = cfg[key];
      if (options && value && !Object.hasOwn(options, value)) {
        // Preserve a legacy value rather than silently overwriting it on save.
        input.add(new Option(String(value), value));
      }
      input.value = Array.isArray(value) ? value.join(', ') : (value ?? (options ? 'werc' : ''));
      field.append(label, input);
      return field;
    });
    document.getElementById(id).replaceChildren(...nodes);
  }
  showConnectionFields();
}

function showConnectionFields() {
  const source = setting('message_source').value;
  const send = setting('send_method').value;
  const visible = {alpha: source === 'alpha' || send === 'alpha_api', weflow: source === 'weflow', legacy: source !== 'werc' || send === 'uia'};
  document.querySelectorAll('[data-connection]').forEach(el => { el.hidden = !visible[el.dataset.connection]; });
}

async function loadConfig() {
  const buttons = ['saveConfigBtn', 'importWeRCBtn', 'testWeRCBtn'].map(id => document.getElementById(id));
  buttons.forEach(el => { el.disabled = true; });
  try {
    const r = await fetch('/api/config');
    if (!r.ok) throw Error('无法读取配置');
    const cfg = await r.json();
    if (cfg.error) throw Error(cfg.error);
    cfg.onebot_ws_url ||= cfg.astrbot_ob_url;
    renderConnectionFields(cfg);
    buttons.forEach(el => { el.disabled = false; });
  } catch (e) { toast(e.message, 'error'); }
}

async function saveConfig() {
  const data = {};
  for (const [key] of Object.values(connectionFields).flat()) {
    const input = setting(key);
    const value = input.value.trim();
    if (input.type === 'number' && (!value || !input.checkValidity())) { toast('端口应在 1–65535 之间。', 'error'); return; }
    data[key] = key === 'bot_nicknames' ? value.split(/[,，]\s*/).filter(Boolean)
      : input.type === 'number' ? Number(value) : value;
  }
  try {
    const r = await fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
    const result = await r.json();
    if (!r.ok || !result.ok) throw Error(result.error || '保存失败');
    toast('已保存。重新打开 RCBridge 后生效。', 'success');
  } catch (e) { toast(e.message, 'error'); }
}

function importWeRC() {
  const box = document.getElementById('wercBundle');
  try {
    const d = JSON.parse(box.value);
    const u = new URL(d.api_url);
    const token = /^Bearer (\S+)$/.exec(d.headers?.Authorization || '');
    if (d.platform !== 'WeRC' || !['127.0.0.1','localhost','[::1]'].includes(u.hostname) || !['http:','https:'].includes(u.protocol) || u.username || u.password || u.search || u.hash || !['','/','/api/v1','/api/v1/'].includes(u.pathname) || !token || !d.account_id) throw Error();
    const values = {werc_base_url:u.origin+'/api/v1', werc_token:token[1], werc_account_id:d.account_id, message_source:'werc', send_method:'werc'};
    for (const [key, value] of Object.entries(values)) setting(key).value = value;
    showConnectionFields();
    box.value = '';
    toast('已导入，请保存。', 'success');
  } catch { toast('请粘贴 WeRC 复制的原始配置。', 'error'); }
}

async function testWeRC() {
  try {
    const data = {};
    for (const [key] of connectionFields.wercFields) data[key] = setting(key).value.trim();
    const d = await (await fetch('/api/test-werc', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)})).json();
    toast(d.message || d.error, d.ok ? 'success' : 'error');
  } catch { toast('连接测试失败', 'error'); }
}
