// ===== 兼容层准备：在旧脚本之前注入缺失的DOM元素 =====
(function() {
    function ensureEl(id, tag, parent, style) {
        var el = document.getElementById(id);
        if (el) return el;
        el = document.createElement(tag || 'div');
        el.id = id;
        if (style) el.style.cssText = style;
        else el.style.display = 'none';
        var target = (typeof parent === 'string') ? document.getElementById(parent) : parent;
        if (target) target.appendChild(el);
        else document.body.appendChild(el);
        return el;
    }

    // 1. 顶栏状态ID - 给新UI的span加ID
    var barLeft = document.querySelector('.top-bar .left');
    if (barLeft) {
        var spans = barLeft.querySelectorAll('span');
        if (spans[0]) spans[0].id = 'miniCalendar';
        if (spans[2]) spans[2].id = 'miniActions';
    }
    ensureEl('miniRank', 'span', null, 'display:none;');
    ensureEl('miniSilver', 'span', null, 'display:none;');

    // 2. 当前故事显示 - 替换新UI的storyDisplay
    var sd = document.getElementById('storyDisplay');
    ensureEl('currentStoryDisplay', 'div', null, '');
    var csd = document.getElementById('currentStoryDisplay');
    csd.className = 'story-display';
    csd.style.cssText = 'padding:10px;line-height:1.5;font-size:9px;color:var(--text-dark);';
    csd.innerHTML = '<span class="speaker">🌸</span> 点击「入宫选秀」开始你的后宫之旅';
    if (sd && sd.parentNode) {
        sd.parentNode.insertBefore(csd, sd);
        sd.parentNode.removeChild(sd);
    }

    // 3. 日志
    var la = document.getElementById('logArea');
    if (la) la.innerHTML = '';
    ensureEl('logContent', 'div', 'logArea', 'padding:4px;font-size:8px;line-height:1.4;');

    // 4. npcGrid - 替换新UI的.npc-grid
    var ng = document.querySelector('.page#pageHarem .npc-grid');
    ensureEl('npcGrid', 'div', null, '');
    var ngEl = document.getElementById('npcGrid');
    ngEl.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:6px;width:100%;';
    if (ng && ng.parentNode) {
        ng.parentNode.insertBefore(ngEl, ng);
        ng.parentNode.removeChild(ng);
    }

    // 5. 状态页 - 替换静态内容为可见动态元素
    var ps = document.getElementById('pageStatus');
    if (ps) {
        ps.innerHTML = '<div id="statusContent" style="padding:5px;font-size:9px;line-height:1.6;">' +
            '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px;">' +
            '<span id="sName" style="font-weight:bold;color:var(--gold);"></span> ' +
            '<span id="sFamily" style="color:var(--text-light);"></span> ' +
            '<span id="sRank" style="color:var(--gold);"></span>' +
            '</div>' +
            '<div style="display:flex;flex-wrap:wrap;gap:3px;margin-bottom:4px;font-size:8px;color:var(--text-light);">' +
            '<span>🪙 <span id="sSilver">0</span></span> ' +
            '<span>📅 <span id="sCalendar">-</span></span> ' +
            '<span>👤 <span id="sAppearance">-</span></span> ' +
            '<span>🎯 <span id="sTalent">-</span></span> ' +
            '<span>🧠 <span id="sPersonality">-</span></span> ' +
            '<span>⭐ <span id="sTraits">-</span></span>' +
            '</div>' +
            '<div id="attrBars" style="margin-bottom:3px;"></div>' +
            '<div id="childrenGrid" style="display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-bottom:3px;"></div>' +
            '<div id="factionContent" style="margin-bottom:3px;"></div>' +
            '<div id="memoriesList" style="margin-bottom:3px;max-height:100px;overflow-y:auto;"></div>' +
            '<div id="changeLog" style="margin-bottom:3px;max-height:80px;overflow-y:auto;"></div>' +
            '</div>';
    } else {
        ensureEl('sName', 'span', null, 'display:none;');
        ensureEl('sFamily', 'span', null, 'display:none;');
        ensureEl('sRank', 'span', null, 'display:none;');
        ensureEl('sSilver', 'span', null, 'display:none;');
        ensureEl('sCalendar', 'span', null, 'display:none;');
        ensureEl('sAppearance', 'span', null, 'display:none;');
        ensureEl('sTalent', 'span', null, 'display:none;');
        ensureEl('sPersonality', 'span', null, 'display:none;');
        ensureEl('sTraits', 'span', null, 'display:none;');
        ensureEl('attrBars', 'div', null, 'display:none;');
        ensureEl('childrenGrid', 'div', null, 'display:none;');
        ensureEl('factionContent', 'div', null, 'display:none;');
        ensureEl('memoriesList', 'div', null, 'display:none;');
        ensureEl('changeLog', 'div', null, 'display:none;');
    }

    // 6. 模态框系统
    ensureEl('modalOverlay', 'div', null, '');
    var mo = document.getElementById('modalOverlay');
    mo.innerHTML = '<div class="modal-box"><div class="modal-title" id="modalTitle"></div><div class="modal-body" id="modalBody" style="max-height:60dvh;overflow-y:auto;"></div><div style="text-align:center;padding-top:8px;"><button id="modalConfirmBtn" class="btn btn-primary" style="padding:6px 22px;border-radius:12px;border:1px solid var(--border-light);background:var(--bg-card);color:var(--text-dark);font-family:inherit;font-size:11px;cursor:pointer;">确 定</button></div></div>';
    mo.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;justify-content:center;align-items:center;';

    // 7. 其他必要元素
    ensureEl('saveListModalBody', 'div');
    ensureEl('flipResultContent', 'div');
    ensureEl('endingOverlay', 'div', null, '');
    var eo = document.getElementById('endingOverlay');
    eo.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:10000;justify-content:center;align-items:center;overflow-y:auto;';
    ensureEl('endingBox', 'div', null, 'display:none;');
    ensureEl('loadingOverlay', 'div', null, '');
    var lo = document.getElementById('loadingOverlay');
    lo.innerHTML = '<div class="loading-box"><div class="loading-icon">🌸</div><div class="loading-title">加载中...</div><div class="loading-sub">禀报中，请稍后</div></div>';
    lo.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:10001;justify-content:center;align-items:center;';

    // 8. 旧脚本const所需元素
    ensureEl('userInput', 'input');
    ensureEl('sendBtn', 'button');
    ensureEl('nextPeriodBtn', 'button');
    ensureEl('loading', 'div');
    ensureEl('statusTags', 'div');
    ensureEl('edictContainer', 'div');
    ensureEl('actionPointBanner', 'div');
    ensureEl('endingWarnBanner', 'div');
    ensureEl('pregnancyProgress', 'div');
    ensureEl('pregnancyProgressFill', 'div');
    ensureEl('pregnancyProgressLabel', 'div');

    // 9. 皇帝/太后
    ensureEl('empName', 'span');
    ensureEl('empPersonality', 'span');
    ensureEl('empStats', 'div');
    ensureEl('dowagerFavor', 'span');
    ensureEl('dowagerPersonality', 'span');

    // 10. 各式面板
    ensureEl('heirPalacePanel', 'div');
    ensureEl('chonghuaPanel', 'div');
    ensureEl('chonghuaToggleBtn', 'button');
    ensureEl('chonghuaStats', 'div');
    ensureEl('chonghuaChildList', 'div');
    ensureEl('chonghuaCandidateList', 'div');
    ensureEl('chonghuaManageBar', 'div');
    ensureEl('princessPanel', 'div');
    ensureEl('princessToggleBtn', 'button');
    ensureEl('princessList', 'div');
    ensureEl('princessFactionBar', 'div');
    ensureEl('servantList', 'div');
    ensureEl('servantCount', 'span');
    ensureEl('conflictTarget', 'select');
    ensureEl('conflictType', 'select');
    ensureEl('conflictLog', 'div');
    ensureEl('conflictAssistList', 'div');
    ensureEl('duelPanel', 'div');
    ensureEl('duelTarget', 'select');
    ensureEl('curseTarget', 'select');
    ensureEl('intrigueSummary', 'div');
    ensureEl('intrigueLog', 'div');
    ensureEl('intrigueAction', 'select');
    ensureEl('intrigueTarget', 'select');
    ensureEl('queenAuthorityStatus', 'div');
    ensureEl('queenAuthorityTarget', 'select');
    ensureEl('sixPalaceAssistantCandidate', 'select');
    ensureEl('blessContainer', 'div');
    ensureEl('blessContent', 'div');
    ensureEl('prayType', 'select');
    ensureEl('prayTarget', 'select');

    // 11. 配置
    ensureEl('configToggleBtn', 'button');
    ensureEl('configPanel', 'div');
    ensureEl('saveConfigBtn', 'button');
    ensureEl('romanceToggle', 'input', null, 'display:none;');
    ensureEl('romanceLabel', 'span');
    ensureEl('configStatus', 'div');
    ensureEl('scenarioConfigStatus', 'div');

    // 12. 翻牌结果模态框
    ensureEl('flipResultModal', 'div', null, '');
    var frm = document.getElementById('flipResultModal');
    frm.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9998;justify-content:center;align-items:center;';
    frm.innerHTML = '<div class="modal-box"><div class="modal-title">翻牌结果</div><div id="flipResultContent" class="modal-body" style="max-height:60dvh;overflow-y:auto;"></div><div style="text-align:center;padding-top:8px;"><button onclick="closeFlipResultModal()" class="btn btn-primary" style="padding:6px 22px;border-radius:12px;font-family:inherit;font-size:11px;cursor:pointer;">知道了</button></div></div>';

    // 13. 存档列表模态框 - 确保 saveListModalBody 在 saveListModal 中
    var slm = document.getElementById('saveListModal');
    if (slm) {
        var oldBody = document.getElementById('saveListModalBody');
        if (oldBody) {
            if (oldBody.parentNode !== slm) {
                oldBody.parentNode.removeChild(oldBody);
            }
        }
        if (!document.getElementById('saveListModalBody')) {
            var sib = document.createElement('div');
            sib.id = 'saveListModalBody';
            sib.style.cssText = 'max-height:50dvh;overflow-y:auto;padding:4px;';
            slm.appendChild(sib);
        }
    }

    window.__compatReady = true;
    console.log('🌸 兼容层准备完成');
})();