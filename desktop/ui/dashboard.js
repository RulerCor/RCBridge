const labels = {werc:'WeRC',alpha:'Alpha',weflow:'WeFlow',uia:'Windows UIA',alpha_api:'Alpha API'};
const byId = id => document.getElementById(id);
async function refreshDashboard(){
  try {const r=await fetch('/status'); if(!r.ok) throw Error(r.status);const s=await r.json();
    byId('statusText').textContent=s.running?(s.paused?'已暂停':'运行中'):'未运行';
    byId('recvStatus').textContent=labels[s.message_source]||s.message_source;
    byId('recvDetail').textContent=s.weflow_connected?'接收接口已连接':'接收接口未连接';
    byId('obStatus').textContent=s.ob_connected?'OneBot 已连接':'OneBot 未连接';
    byId('sendMethod').textContent=labels[s.send_method]||s.send_method;
    byId('btnStart').disabled=s.running;byId('btnStop').disabled=!s.running;
    byId('displayVersion').textContent=s.project_version||'';
    const el=byId('log'),follow=el.scrollHeight-el.scrollTop-el.clientHeight<40;
    el.textContent=s.log||'暂无记录。配置消息源后，点击「启动桥接」。';if(follow)el.scrollTop=el.scrollHeight;
  }catch(e){byId('statusText').textContent='控制端未连接'}
}
async function action(cmd){try{const r=await fetch('/'+cmd,{method:'POST'});const d=await r.json();if(!r.ok||!d.ok)throw Error(d.error||r.status);await refreshDashboard()}catch(e){toast(e.message,'error')}}
const [tab]=location.hash.slice(1).split('/');switchTab(['settings','members'].includes(tab)?tab:'dashboard');
refreshDashboard();setInterval(refreshDashboard,3000);

async function inspectOutbox(){const el=byId('receipts');el.textContent='读取中…';try{const d=await(await fetch('/api/werc-outbox')).json();if(!d.ok)throw Error(d.error);const names={awaiting_approval:'等待批准',queued:'已排队',submitting:'提交中',unknown:'结果未知，不要重发',server_accepted:'服务端受理',recipient_confirmed:'收件端已确认',rejected:'已拒绝',canceled:'已取消',expired:'已过期'};el.textContent=d.rows.map(r=>(names[r.state]||r.state)+'  '+r.task).join('\n')||'当前账号暂无保留任务'}catch(e){el.textContent=e.message}}
