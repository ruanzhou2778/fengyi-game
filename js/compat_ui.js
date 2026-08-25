// ===== 兼容UI适配：连接新UI按钮到旧游戏函数 =====
// 作用：提供新UI HTML 中 onclick 引用的壳层函数，将 mock 按钮连接到真实游戏逻辑
// 注意：此文件在旧游戏脚本之后加载
(function() {
    function waitForReady(cb, maxWait) {
        var waited = 0;
        var check = function() {
            if (window.__compatReady && typeof startGame === 'function') {
                cb();
            } else if (waited < (maxWait || 5000)) {
                waited += 100;
                setTimeout(check, 100);
            }
        };
        check();
    }

    waitForReady(function() {
        // ---- 1. 壳层函数：新UI HTML 的 onclick 引用 ----
        window.doFlip = function() {
            if (!window.playerId) { showToast('❌ 请先开始游戏'); return; }
            if (window._lastGameData) triggerFlip(window._lastGameData);
            else showToast('❌ 无游戏数据');
        };
        window.doRandomEvent = function() {
            if (!window.playerId || isProcessing) { showToast('⏳ 处理中...'); return; }
            triggerRandomConflict();
        };
        window.doNextPeriod = function() { nextPeriod(); };
        window.doFreeAction = function() {
            var input = document.getElementById('userInput');
            if (!input) { showToast('❌ 未找到输入框'); return; }
            var text = input.value.trim();
            if (!text) { showToast('❌ 请输入内容'); return; }
            sendFreeInput(text);
        };
        window.openSaveList = function() { openSaveListModal(); };
        window.closeSaveList = function() { closeSaveListModal(); };
        window.closeFlipResult = function() {
            var frm = document.getElementById('flipResultModal');
            if (frm) frm.style.display = 'none';
            closeModal();
        };
        window.closeFlipResultModal = function() {
            var frm = document.getElementById('flipResultModal');
            if (frm) frm.style.display = 'none';
            closeModal();
        };
        window.closeEventResult = function() { closeModal(); };
        window.openPlayerDetail = function() {
            if (!window.playerId) { showToast('❌ 请先开始游戏'); return; }
            openModal('📋 我的档案', '<div id="playerDetailContent">加载中...</div>', '关闭', null, true);
            if (window._lastGameData) {
                var d = _lastGameData;
                document.getElementById('playerDetailContent').innerHTML =
                    '<div style="font-size:9px;line-height:1.6;">' +
                    '<p>👤 姓名：' + (d.player_name || d.name || '-') + '</p>' +
                    '<p>👑 位份：' + (d.display_rank || d.rank || '-') + '</p>' +
                    '<p>🏠 出身：' + (d.family_background || '-') + '</p>' +
                    '<p>🎂 年龄：' + (d.age || '-') + '岁</p>' +
                    '<p>🪙 银两：' + (d.silver || 0) + '</p></div>';
            }
        };
        window.closePlayerDetail = function() { closeModal(); };
        window.toggleMap = function() {
            var overlay = document.getElementById('mapOverlay');
            if (!overlay) { showToast('🗺️ 暂无舆图'); return; }
            overlay.classList.toggle('active');
        };
        window.openLedger = function() {
            var d = window._lastGameData;
            openModal('📜 宫中账目', '<div style="font-size:9px;line-height:1.6;">' +
                (d ? '<p>🪙 银两：' + (d.silver || 0) + '</p>' +
                '<p>📅 日期：' + (d.calendar_str || '-') + '</p>' +
                '<p>⚡ 行动点：' + (d.remaining_actions || 0) + '/' + (d.max_actions || 7) + '</p>'
                : '<p>暂无游戏数据</p>') + '</div>', '关闭');
        };
        window.closeLedger = function() { closeModal(); };

        // ---- 2. 替换新UI中的 mock 按钮 onclick ----
        document.querySelectorAll('[onclick*="存档已保存"]').forEach(function(btn) {
            btn.setAttribute('onclick', "saveGame('default');showToast('✅ 存档已保存');");
        });
        document.querySelectorAll('[onclick*="读取存档"]').forEach(function(btn) {
            btn.setAttribute('onclick', "openSaveListModal()");
        });
        document.querySelectorAll('[onclick*="打开皇帝交互面板"]').forEach(function(el) {
            el.setAttribute('onclick', "openEmperorInteract()");
        });
        document.querySelectorAll('[onclick*="打开太后交互面板"]').forEach(function(el) {
            el.setAttribute('onclick', "openDowagerInteract()");
        });
        document.querySelectorAll('[onclick*="招募宫女（30两）"]').forEach(function(btn) {
            btn.setAttribute('onclick', "hireServant('宫女')");
        });
        document.querySelectorAll('[onclick*="招募太监（20两）"]').forEach(function(btn) {
            btn.setAttribute('onclick', "hireServant('太监')");
        });
        document.querySelectorAll('[onclick*="打开背包"]').forEach(function(btn) {
            btn.setAttribute('onclick', "openInventory()");
        });
        document.querySelectorAll('[onclick*="发起宫斗"]').forEach(function(btn) {
            btn.setAttribute('onclick', "document.querySelector('[data-page=pageConflict]').click()");
        });
        document.querySelectorAll('[onclick*="邀约争锋"]').forEach(function(btn) {
            btn.setAttribute('onclick', "showToast('🗡️ 请在宫斗页选择目标');document.querySelector('[data-page=pageConflict]').click()");
        });
        document.querySelectorAll('[onclick*="祈福（15两）"]').forEach(function(btn) {
            btn.setAttribute('onclick', "doPray('health')");
        });
        document.querySelectorAll('[onclick*="掌祀（40两）"]').forEach(function(btn) {
            btn.setAttribute('onclick', "doPray('ancestor')");
        });
        document.querySelectorAll('[onclick*="执行"]').forEach(function(btn) {
            btn.setAttribute('onclick', "performIntrigueAction()");
        });
        document.querySelectorAll('[onclick*="贪墨"]').forEach(function(btn) {
            btn.setAttribute('onclick', "showToast('💰 暂未实现')");
        });
        document.querySelectorAll('[onclick*="查账"]').forEach(function(btn) {
            btn.setAttribute('onclick', "openLedger()");
        });

        // ---- 4. 同步迷你状态到新UI顶栏 ----
        var topBar = document.querySelector('.top-bar .left');
        if (topBar) {
            var mr = document.getElementById('miniRank');
            var ms = document.getElementById('miniSilver');
            if (mr && mr.parentNode !== topBar) {
                topBar.insertBefore(mr, topBar.firstChild);
                mr.style.cssText = 'font-size:8px;color:var(--gold);margin-right:4px;';
            }
            if (ms && ms.parentNode !== topBar) {
                var ref = document.getElementById('miniCalendar');
                if (ref) topBar.insertBefore(ms, ref);
                else topBar.appendChild(ms);
                ms.style.cssText = 'font-size:8px;color:var(--gold);margin-right:4px;';
            }
        }

        // ---- 5. 兜底函数 ----
        if (typeof confirmReset !== 'function') {
            window.confirmReset = function() {
                if (confirm('确定重建新档？')) {
                    localStorage.removeItem('gongdou_playerId');
                    window.playerId = null;
                    location.reload();
                }
            };
        }

        console.log('🌸 兼容层已加载，新UI已连接到游戏引擎');
    });
})();