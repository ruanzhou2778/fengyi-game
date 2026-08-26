// ---- 内务府面板（Phase 1-6 扩展版）----
function ipAliveTargets(){
    const d = window._lastGameData;
    const out = [];
    if(d && d.npcs){
        for(const [n, v] of Object.entries(d.npcs)){
            if(v && v.alive !== false && n !== '太后') out.push(n);
        }
    }
    return out;
}

async function ipFetchStatus(){
    const r = await myFetch(`${API_BASE}/api/inner_palace/status?player_id=${encodeURIComponent(playerId)}`, {skipLoading:true});
    return await parseApiResponse(r, {allowError:true});
}

async function ipRefreshAll(){
    updateInnerPalacePanel();
    try{
        const sr = await myFetch(`${API_BASE}/api/state/${playerId}`);
        updateUI(await sr.json());
    }catch(e){}
}

function ipTargetOptions(selected){
    const ts = ipAliveTargets();
    if(!ts.length) return '<option value="">（暂无可操作对象）</option>';
    return ts.map(n=>`<option value="${n}" ${n===selected?'selected':''}>${n}</option>`).join('');
}

async function updateInnerPalacePanel(){
    const block = document.getElementById('innerPalaceBlock');
    const content = document.getElementById('ipContent');
    const actions = document.getElementById('ipActions');
    if(!block || !content || !actions) return;
    if(!playerId){ content.innerHTML='<span style="color:var(--text-light);">未开始游戏</span>'; actions.innerHTML=''; return; }
    try{
        const d = await ipFetchStatus();
        if(d.error){ content.innerHTML=`<span style="color:#e08080;">${d.error}</span>`; actions.innerHTML=''; return; }
        const budget = d.budget ?? 0;
        const sh = d.storehouse || {};
        const chief = d.chief || {};
        const market = d.market || {};
        const logs = d.logs || [];
        const evidence = d.corruption_evidence ?? 0;
        const purse = d.private_purse || {};
        const reviews = d.performance_reviews || {};
        const projects = d.projects || {};
        const cuts = d.stipend_cuts || {};
        const gifts = d.bonus_gifts || {};
        const effDay = (window._lastGameData||{}).day ?? 0;
        let html = `<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span>💰 库银</span><span style="color:var(--gold-dark);font-weight:600;">${budget}两</span></div>`;
        html += `<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span>🏦 私库</span><span style="font-size:8px;color:var(--text-mid);">${purse.enabled?`累计转入 ${purse.total_transferred??0}两`:'未开通（威望≥80）'}</span></div>`;
        html += `<div style="padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span style="color:var(--text-light);">📦 库存</span><div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:1px;">`;
        for(const [k,v] of Object.entries(sh)){ html += `<span style="background:rgba(201,168,106,.12);padding:1px 4px;border-radius:3px;">${k}:${v}</span>`; }
        html += `</div></div>`;
        html += `<div style="padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span style="color:var(--text-light);">👤 总管</span> ${chief.name||'-'} <span style="font-size:7px;color:var(--text-mid);">[${chief.faction||'中立'}] 忠${chief.loyalty??'-'} / 贪${chief.corruption??'-'} / 能${chief.skill??'-'}</span>${evidence>0?` <span style="color:#e08080;font-size:7px;">罪证${evidence}</span>`:''}</div>`;
        html += `<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span>📋 季度考绩</span><span style="font-size:8px;color:var(--text-mid);">${reviews.grade?`${reviews.grade}（${reviews.score}分）`:'未考绩'} · ${Math.max(0,(reviews.next_review??30)-effDay)}旬后</span></div>`;
        const projRows = Object.entries(projects).map(([pn, p])=>{
            const lv = p.level ?? 0;
            return `<span style="background:rgba(201,168,106,.12);padding:1px 4px;border-radius:3px;font-size:7px;">${pn}${lv>0?`Lv${lv}·${p.income_per_period}两/旬${p.status&&p.status!=='正常'?`·${p.status}`:''}`:'未开'}</span>`;
        }).join('');
        html += `<div style="padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span style="color:var(--text-light);">🏭 产业</span><div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:1px;">${projRows||'<span style="font-size:7px;color:var(--text-light);">暂无投资</span>'}</div></div>`;
        const active = [];
        for(const [t,v] of Object.entries(cuts)){ if(v.periods>0) active.push(`克扣${t} ${v.amount}%·${v.periods}旬`); }
        for(const [t,v] of Object.entries(gifts)){ if(v.periods>0) active.push(`赏赐${t} ${v.amount}两/旬·${v.periods}旬`); }
        if(active.length){
            html += `<div style="padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span style="color:var(--text-light);">🗂 生效中</span><div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:1px;">`+
                active.map(a=>`<span style="background:rgba(180,120,120,.15);padding:1px 4px;border-radius:3px;font-size:7px;">${a}</span>`).join('')+`</div></div>`;
        }
        html += `<div style="padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span style="color:var(--text-light);">🏷️ 市价</span><div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:1px;">`;
        for(const [k,v] of Object.entries(market)){ html += `<span style="font-size:7px;color:var(--text-mid);">${k}${v}</span>`; }
        html += `</div></div>`;
        if(logs.length){ html += `<div style="margin-top:2px;font-size:7px;color:var(--text-mid);line-height:1.3;">`; logs.slice().reverse().forEach(l=>{ html+=`<div>${l}</div>`; }); html+=`</div>`; }
        content.innerHTML = html;
        const remainActions = (window._lastGameData||{}).remaining_actions ?? 0;
        const dis = remainActions <= 0 ? 'disabled style="opacity:.45;cursor:not-allowed;"' : '';
        let btns = '';
        const B = (fn, label, extra) => btns += `<button onclick="${fn}" ${dis} class="interact-btn" style="padding:2px 6px;font-size:8px;${extra||''}">${label}</button>`;
        B('openIpPurchase()','🛒 采买');
        B('doIpEmbezzle()','🐀 贪墨');
        B('doIpAudit()','📜 查账');
        B('openIpCut()','✂️ 克扣', 'border-color:rgba(200,120,120,.5);');
        B('openIpBonus()','🎁 赏赐');
        B('openIpBanquet()','🏮 宫宴');
        B('ipPurseAction()','🏦 私库');
        B('ipChiefAction()','👤 总管');
        B('openIpUpgrade()','🏭 产业');
        if(remainActions<=0) btns += `<span style="font-size:7px;color:var(--text-light);margin-left:4px;">行动点不足</span>`;
        actions.innerHTML = btns;
    }catch(e){ content.innerHTML=`<span style="color:#e08080;">加载失败</span>`; actions.innerHTML=''; }
}


async function openIpPurchase(){
    if(!playerId) return;
    try{
        const r = await myFetch(`${API_BASE}/api/inner_palace/status?player_id=${encodeURIComponent(playerId)}`, {skipLoading:true});
        const d = await parseApiResponse(r, {allowError:true});
        if(d.error){ showToast('❌ '+d.error,'error'); return; }
        const market = d.market || {};
        const items = Object.keys(market);
        if(!items.length){ showToast('暂无可购物资'); return; }
        let opts = items.map(k=>`<option value="${k}">${k} (${market[k]}两)</option>`).join('');
        const html = `<div style="display:flex;flex-direction:column;gap:6px;">` +
            `<label style="font-size:9px;color:var(--text-mid);">选择物资</label>` +
            `<select id="ipBuyItem" style="padding:3px;border:1px solid var(--border-light);border-radius:4px;background:var(--bg-card);color:var(--text-dark);font-size:9px;">${opts}</select>` +
            `<label style="font-size:9px;color:var(--text-mid);">数量</label>` +
            `<input id="ipBuyQty" type="number" min="1" max="99" value="1" style="padding:3px;border:1px solid var(--border-light);border-radius:4px;background:var(--bg-card);color:var(--text-dark);font-size:9px;width:80px;">` +
            `</div>`;
        openModal('🛒 内务府采买', html, '确认采买', async ()=>{
            const item = document.getElementById('ipBuyItem')?.value;
            const qty = parseInt(document.getElementById('ipBuyQty')?.value||'1',10) || 1;
            if(!item || qty<=0){ showToast('请输入有效数量','error'); return; }
            try{
                const pr = await myFetch(`${API_BASE}/api/inner_palace/purchase`, {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({player_id: playerId, item, qty}), skipLoading:true
                });
                const pd = await parseApiResponse(pr, {allowError:true});
                if(pd.error){ showToast('❌ '+pd.error,'error'); return; }
                showToast('✅ '+(pd.message||'采买成功'));
                if(typeof addLogEntry==='function') addLogEntry('🛒 '+(pd.message||'采买完成'), 'system');
                updateInnerPalacePanel();
                const sr = await myFetch(`${API_BASE}/api/state/${playerId}`);
                updateUI(await sr.json());
            }catch(e){ showToast('❌ 采买失败：'+e.message,'error'); }
        }, null, true);
    }catch(e){ showToast('❌ 打开采买面板失败','error'); }
}


async function doIpEmbezzle(){
    if(!confirm('确定勾结总管贪墨？败露将损失威望。')) return;
    try{
        const r = await myFetch(`${API_BASE}/api/inner_palace/embezzle`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({player_id: playerId}), skipLoading:true
        });
        const d = await parseApiResponse(r, {allowError:true});
        if(d.error){ showToast('❌ '+d.error,'error'); return; }
        const msg = d.message || '操作完成';
        showToast(msg.includes('败露')?'⚠️ '+msg:'✅ '+msg);
        if(typeof addLogEntry==='function') addLogEntry('🐀 '+msg, 'system');
        updateInnerPalacePanel();
        const sr = await myFetch(`${API_BASE}/api/state/${playerId}`);
        updateUI(await sr.json());
    }catch(e){ showToast('❌ 贪墨失败：'+e.message,'error'); }
}

async function doIpAudit(){
    if(!confirm('确定查账？若无罪证可能被反噬。')) return;
    try{
        const r = await myFetch(`${API_BASE}/api/inner_palace/audit`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({player_id: playerId}), skipLoading:true
        });
        const d = await parseApiResponse(r, {allowError:true});
        if(d.error){ showToast('❌ '+d.error,'error'); return; }
        const msg = d.message || '查账完毕';
        showToast(msg.includes('未发现')?'⚠️ '+msg:'✅ '+msg);
        if(typeof addLogEntry==='function') addLogEntry('📜 '+msg, 'system');
        updateInnerPalacePanel();
        const sr = await myFetch(`${API_BASE}/api/state/${playerId}`);
        updateUI(await sr.json());
    }catch(e){ showToast('❌ 查账失败：'+e.message,'error'); }
}

// ---- Phase 1：克扣份例 ----
function openIpCut(){
    if(!playerId) return;
    const html = `<div style="display:flex;flex-direction:column;gap:6px;">` +
        `<label style="font-size:9px;color:var(--text-mid);">目标（月例将被克扣）</label>` +
        `<select id="ipCutTarget" style="padding:3px;border:1px solid var(--border-light);border-radius:4px;background:var(--bg-card);color:var(--text-dark);font-size:9px;">${ipTargetOptions()}</select>` +
        `<div style="display:flex;gap:6px;">` +
        `<div style="flex:1;"><label style="font-size:9px;color:var(--text-mid);">克扣比例</label>` +
        `<select id="ipCutPct" style="padding:3px;border:1px solid var(--border-light);border-radius:4px;background:var(--bg-card);color:var(--text-dark);font-size:9px;width:100%;"><option value="20">20%</option><option value="30" selected>30%</option><option value="50">50%</option></select></div>` +
        `<div style="flex:1;"><label style="font-size:9px;color:var(--text-mid);">持续旬数</label>` +
        `<input id="ipCutPeriods" type="number" min="3" max="30" value="10" style="padding:3px;border:1px solid var(--border-light);border-radius:4px;background:var(--bg-card);color:var(--text-dark);font-size:9px;width:100%;"></div>` +
        `</div>` +
        `<div style="font-size:8px;color:#e08080;">风险：目标好感/健康受损，总管忠诚低时可能揭发（威望-，罪证+）</div>` +
        `</div>`;
    openModal('✂️ 克扣份例', html, '暗中克扣', async ()=>{
        const target = document.getElementById('ipCutTarget')?.value;
        const pct = parseInt(document.getElementById('ipCutPct')?.value||'30',10) || 30;
        const periods = parseInt(document.getElementById('ipCutPeriods')?.value||'10',10) || 10;
        if(!target){ showToast('请选择目标','error'); return; }
        const r = await ipPostAction('cut_stipend', {player_id: playerId, target, pct, periods});
        if(r && r.error) return;
        await ipRefreshAll();
    }, null, true);
}

// ---- Phase 1：额外赏赐 ----
function openIpBonus(){
    if(!playerId) return;
    const html = `<div style="display:flex;flex-direction:column;gap:6px;">` +
        `<label style="font-size:9px;color:var(--text-mid);">目标</label>` +
        `<select id="ipBonusTarget" style="padding:3px;border:1px solid var(--border-light);border-radius:4px;background:var(--bg-card);color:var(--text-dark);font-size:9px;">${ipTargetOptions()}</select>` +
        `<div style="display:flex;gap:6px;">` +
        `<div style="flex:1;"><label style="font-size:9px;color:var(--text-mid);">每旬加发（两）</label>` +
        `<input id="ipBonusAmount" type="number" min="1" max="100" value="20" style="padding:3px;border:1px solid var(--border-light);border-radius:4px;background:var(--bg-card);color:var(--text-dark);font-size:9px;width:100%;"></div>` +
        `<div style="flex:1;"><label style="font-size:9px;color:var(--text-mid);">持续旬数</label>` +
        `<input id="ipBonusPeriods" type="number" min="3" max="30" value="5" style="padding:3px;border:1px solid var(--border-light);border-radius:4px;background:var(--bg-card);color:var(--text-dark);font-size:9px;width:100%;"></div>` +
        `</div>` +
        `<div style="font-size:8px;color:var(--text-mid);">立即按「每旬加发 × 旬数」扣库银；好感+5，期满恩义渐散（好感-2）</div>` +
        `</div>`;
    openModal('🎁 额外赏赐', html, '拨银赏赐', async ()=>{
        const target = document.getElementById('ipBonusTarget')?.value;
        const amount = parseInt(document.getElementById('ipBonusAmount')?.value||'20',10) || 20;
        const periods = parseInt(document.getElementById('ipBonusPeriods')?.value||'5',10) || 5;
        if(!target){ showToast('请选择目标','error'); return; }
        const r = await ipPostAction('give_bonus', {player_id: playerId, target, amount, periods});
        if(r && r.error) return;
        await ipRefreshAll();
    }, null, true);
}

// ---- Phase 1：宫宴 ----
function openIpBanquet(){
    if(!playerId) return;
    const T = [['奢华','100两 · 威望+8 皇帝好感+5'],['中等','50两 · 威望+4 皇帝好感+3'],['简朴','20两 · 威望+2 皇帝好感+1']];
    const html = `<div style="display:flex;flex-direction:column;gap:6px;">` +
        `<div style="font-size:8px;color:var(--text-mid);">总管技能越高，宴饮效果加成越多（最高+50%）</div>` +
        T.map(([k,v],i)=>`<label style="display:flex;align-items:center;gap:6px;font-size:9px;color:var(--text-dark);"><input type="radio" name="ipBanquetTier" value="${k}" ${i===1?'checked':''}> 🏮 ${k}宫宴 <span style="color:var(--text-mid);">（${v}）</span></label>`).join('') +
        `</div>`;
    openModal('🏮 承办宫宴', html, '举办宫宴', async ()=>{
        const tier = document.querySelector('input[name="ipBanquetTier"]:checked')?.value || '中等';
        const r = await ipPostAction('banquet', {player_id: playerId, tier});
        if(r && r.error) return;
        await ipRefreshAll();
    }, null, true);
}

// ---- 统一 POST 辅助 ----
async function ipPostAction(name, body){
    try{
        const r = await myFetch(`${API_BASE}/api/inner_palace/${name}`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify(body), skipLoading:true
        });
        const d = await parseApiResponse(r, {allowError:true});
        if(d.error){ showToast('❌ '+d.error,'error'); return d; }
        showToast('✅ '+(d.message||'操作完成'));
        if(typeof addLogEntry==='function') addLogEntry('🏛 '+(d.message||'内务府操作'), 'system');
        return d;
    }catch(e){ showToast('❌ 操作失败：'+e.message,'error'); return {error:e.message}; }
}

// ---- Phase 3：私库 ----
async function ipPurseAction(){
    if(!playerId) return;
    const d = await ipFetchStatus();
    if(d.error) return;
    const purse = d.private_purse || {};
    const budget = d.budget ?? 0;
    if(!purse.enabled){
        const html = `<div style="display:flex;flex-direction:column;gap:6px;">` +
            `<div style="font-size:9px;color:var(--text-mid);">开通私库需威望≥80。开通后可每旬将最多50两库银转入你的私银（有被察觉风险）。</div>` +
            `</div>`;
        openModal('🏦 开通私库', html, '开通', async ()=>{
            const r = await ipPostAction('private_purse/enable', {player_id: playerId});
            if(r && r.error) return;
            await ipRefreshAll();
        }, null, true);
        return;
    }
    const canTransfer = (window._lastGameData||{}).day > (purse.last_transfer_period ?? 0);
    const html = `<div style="display:flex;flex-direction:column;gap:6px;">` +
        `<div style="font-size:9px;color:var(--text-mid);">累计转入：${purse.total_transferred??0}两　当前库银：${budget}两</div>` +
        `<label style="font-size:9px;color:var(--text-mid);">划转金额（上限50，每旬一次）</label>` +
        `<input id="ipPurseAmount" type="number" min="1" max="50" value="20" style="padding:3px;border:1px solid var(--border-light);border-radius:4px;background:var(--bg-card);color:var(--text-dark);font-size:9px;width:120px;">` +
        (!canTransfer?`<div style="font-size:8px;color:#e08080;">本旬已划转过，请下旬再试</div>`:``) +
        `</div>`;
    openModal('🏦 私库划转', html, '划转', async ()=>{
        if(!canTransfer){ showToast('本旬已划转过','error'); return; }
        const amount = parseInt(document.getElementById('ipPurseAmount')?.value||'20',10) || 20;
        const r = await ipPostAction('private_purse/transfer', {player_id: playerId, amount});
        if(r && r.error) return;
        await ipRefreshAll();
    }, null, true);
}

// ---- Phase 2：总管任免 ----
async function ipChiefAction(){
    if(!playerId) return;
    const d = await ipFetchStatus();
    if(d.error) return;
    const chief = d.chief || {};
    const budget = d.budget ?? 0;
    const prestige = (window._lastGameData||{}).attributes?.['威望'] ?? 0;
    const evidence = d.corruption_evidence ?? 0;
    const canDismiss = prestige >= 80 || evidence >= 20;
    const html = `<div style="display:flex;flex-direction:column;gap:6px;">` +
        `<div style="font-size:9px;color:var(--text-dark);">现任：${chief.name||'-'}（${chief.faction||'中立'}）</div>` +
        `<div style="font-size:8px;color:var(--text-mid);">忠${chief.loyalty??'-'} / 贪${chief.corruption??'-'} / 能${chief.skill??'-'} · 任期${chief.tenure??0}旬 · 绩效${chief.performance??0}</div>` +
        `<div style="font-size:8px;color:var(--text-mid);">库银${budget}两 · 威望${prestige} · 罪证${evidence}</div>` +
        `<div style="display:flex;gap:6px;margin-top:4px;">` +
        `<button id="ipAppointBtn" style="flex:1;padding:4px;border:1px solid var(--border-light);border-radius:4px;background:rgba(201,168,106,.15);color:var(--text-dark);font-size:9px;cursor:pointer;">👔 任命新总管（100两）</button>` +
        `<button id="ipDismissBtn" ${canDismiss?'':'disabled style="opacity:.45;"'} style="flex:1;padding:4px;border:1px solid rgba(200,120,120,.5);border-radius:4px;background:rgba(200,120,120,.12);color:var(--text-dark);font-size:9px;cursor:pointer;">📢 弹劾解职（50两）</button>` +
        `</div>` +
        (canDismiss?'':'<div style="font-size:8px;color:#e08080;">弹劾需威望≥80或罪证≥20</div>') +
        `</div>`;
    openModal('👤 总管人事', html, '关闭', async ()=>{
        const appBtn = document.getElementById('ipAppointBtn');
        if(appBtn) appBtn.onclick = async ()=>{
            if(!confirm('确定任命新总管？花费100两。新总管随机生成（含派系）。')) return;
            const r = await ipPostAction('chief/appoint', {player_id: playerId});
            if(r && r.error) return;
            await ipRefreshAll();
        };
        const disBtn = document.getElementById('ipDismissBtn');
        if(disBtn && canDismiss) disBtn.onclick = async ()=>{
            if(!confirm(`确定弹劾${chief.name||'总管'}？花费50两，罪证清零。`)) return;
            const r = await ipPostAction('chief/dismiss', {player_id: playerId});
            if(r && r.error) return;
            await ipRefreshAll();
        };
    }, null, true);
}

// ---- Phase 5：产业投资 ----
async function openIpUpgrade(){
    if(!playerId) return;
    const d = await ipFetchStatus();
    if(d.error) return;
    const projects = d.projects || {};
    const budget = d.budget ?? 0;
    const names = Object.keys(projects);
    if(!names.length) return;
    const rows = names.map((n,i)=>{
        const p = projects[n] || {};
        const lv = p.level ?? 0;
        const cost = 100 + 80 * lv;
        const maxed = lv >= 5;
        const inc = lv > 0 ? `${p.income_per_period}两/旬${p.status && p.status!=='正常' ? '（'+p.status+'中）' : ''}` : '未开（首级后收益5两/旬）';
        return `<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 0;border-bottom:1px solid rgba(201,168,106,.18);">` +
            `<div><div style="font-size:9px;color:var(--text-dark);">🏭 ${n} ${maxed?'（已满级）':''}</div><div style="font-size:7px;color:var(--text-mid);">Lv${lv} · ${inc} · 累计投入${p.invested??0}两</div></div>` +
            `<button id="ipUpgBtn${i}" ${maxed||budget<cost?'disabled style="opacity:.45;"':''} style="padding:2px 8px;border:1px solid var(--border-light);border-radius:4px;background:rgba(201,168,106,.15);color:var(--text-dark);font-size:8px;cursor:pointer;">${maxed?'满级':`升级（${cost}两）`}</button>` +
            `</div>`;
    }).join('');
    const html = `<div style="display:flex;flex-direction:column;gap:4px;">` +
        `<div style="font-size:8px;color:var(--text-mid);">库银${budget}两。产业每旬自动进账，可能遭遇丰收/灾荒/贪墨。升级消耗1行动点。</div>` +
        rows + `</div>`;
    openModal('🏭 产业投资', html, '关闭', async ()=>{
        names.forEach((n,i)=>{
            const btn = document.getElementById('ipUpgBtn'+i);
            if(btn && !btn.disabled) btn.onclick = async ()=>{
                const r = await ipPostAction('project/upgrade', {player_id: playerId, name: n});
                if(r && r.error) return;
                await ipRefreshAll();
            };
        });
    }, null, true);
}

if(typeof updateInnerPalacePanel==='function') setTimeout(updateInnerPalacePanel, 600);
