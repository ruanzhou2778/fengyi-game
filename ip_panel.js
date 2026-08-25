// ---- 内务府面板 ----
async function updateInnerPalacePanel(){
    const block = document.getElementById('innerPalaceBlock');
    const content = document.getElementById('ipContent');
    const actions = document.getElementById('ipActions');
    if(!block || !content || !actions) return;
    if(!playerId){ content.innerHTML='<span style="color:var(--text-light);">未开始游戏</span>'; actions.innerHTML=''; return; }
    try{
        const r = await myFetch(`${API_BASE}/api/inner_palace/status?player_id=${encodeURIComponent(playerId)}`, {skipLoading:true});
        const d = await parseApiResponse(r, {allowError:true});
        if(d.error){ content.innerHTML=`<span style="color:#e08080;">${d.error}</span>`; actions.innerHTML=''; return; }
        const budget = d.budget ?? 0;
        const sh = d.storehouse || {};
        const chief = d.chief || {};
        const market = d.market || {};
        const logs = d.logs || [];
        const evidence = d.corruption_evidence ?? 0;
        let html = `<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span>💰 库银</span><span style="color:var(--gold-dark);font-weight:600;">${budget}两</span></div>`;
        html += `<div style="padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span style="color:var(--text-light);">📦 库存</span><div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:1px;">`;
        for(const [k,v] of Object.entries(sh)){ html += `<span style="background:rgba(201,168,106,.12);padding:1px 4px;border-radius:3px;">${k}:${v}</span>`; }
        html += `</div></div>`;
        html += `<div style="padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span style="color:var(--text-light);">👤 总管</span> ${chief.name||'-'} <span style="font-size:7px;color:var(--text-mid);">忠${chief.loyalty??'-'} / 贪${chief.corruption??'-'} / 能${chief.skill??'-'}</span>${evidence>0?` <span style="color:#e08080;font-size:7px;">罪证${evidence}</span>`:''}</div>`;
        html += `<div style="padding:2px 0;border-bottom:1px solid rgba(201,168,106,.18);"><span style="color:var(--text-light);">🏷️ 市价</span><div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:1px;">`;
        for(const [k,v] of Object.entries(market)){ html += `<span style="font-size:7px;color:var(--text-mid);">${k}${v}</span>`; }
        html += `</div></div>`;
        if(logs.length){ html += `<div style="margin-top:2px;font-size:7px;color:var(--text-mid);line-height:1.3;">`; logs.slice().reverse().forEach(l=>{ html+=`<div>${l}</div>`; }); html+=`</div>`; }
        content.innerHTML = html;
        const remainActions = (window._lastGameData||{}).remaining_actions ?? 0;
        let btns = '';
        const dis = remainActions <= 0 ? 'disabled style="opacity:.45;cursor:not-allowed;"' : '';
        btns += `<button onclick="openIpPurchase()" ${dis} class="interact-btn" style="padding:2px 6px;font-size:8px;">🛒 采买</button>`;
        btns += `<button onclick="doIpEmbezzle()" ${dis} class="interact-btn" style="padding:2px 6px;font-size:8px;">🐀 贪墨</button>`;
        btns += `<button onclick="doIpAudit()" ${dis} class="interact-btn" style="padding:2px 6px;font-size:8px;">📜 查账</button>`;
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

if(typeof updateInnerPalacePanel==='function') setTimeout(updateInnerPalacePanel, 600);
