(function () {
    'use strict';

    window.GameModules = window.GameModules || {};
    const names = window.GameModules.names || {};
    const familyBackgrounds = window.GameModules.family_backgrounds || {};

    const extractSurname = names.extract_surname || function (n) { return (n && n[0]) || '某'; };
    const clanFamilyScore = familyBackgrounds.get_family_score || function () { return 45; };

    function randomChoice(arr) {
        return arr[Math.floor(Math.random() * arr.length)];
    }

    function randomUniform(a, b) {
        return a + Math.random() * (b - a);
    }

    function randomInt(a, b) {
        return Math.floor(Math.random() * (b - a + 1)) + a;
    }

    const DUEL_SKILLS = {
        '持宠生娇': { attr: '宠爱', desc: '比圣宠深浅' },
        '金枝玉叶': { attr: '家世', desc: '比出身门第' },
        '破口大骂': { attr: '健康', desc: '比体质气势' },
        '绵里藏针': { attr: '心计', desc: '比城府心机' },
        '才压群芳': { attr: '才情', desc: '比才学辞章' },
        '位高权重': { attr: '位份', desc: '比位份高低' },
        '群起攻之': { attr: '人手', desc: '比宫人多寡' },
        '沉默不语': { attr: '福运', desc: '以静制动' },
    };

    const DRAIN_OPTIONS = {
        '降其心智': { self: '心计', target: '心计', favor: -12, desc: '你心计渐长，对方城府受损' },
        '辱其自尊': { self: '威望', target: '威望', favor: -18, desc: '你威望抬升，对方颜面尽失' },
        '摧其斗志': { self: '倾向', target: '倾向', favor: 0, desc: '你气势更盛，对方斗志消磨' },
        '以理服人': { self: 'all', target: 'all', favor: -8, desc: '同时吸取心计、威望与倾向' },
    };

    const RANK_ORDER_LOCAL = ['更衣', '官女子', '答应', '常在', '贵人', '才人', '美人', '婕妤', '嫔', '妃', '贵妃', '皇贵妃', '皇后'];
    const TITLED_CONSORT_POWER = 12;   // 妃 + 普通封号
    const FOUR_CONSORT_POWER = 13;     // 妃 + 四妃封号（淑/德/贤/宸）
    const FOUR_CONSORT_TITLES = ['淑', '德', '贤', '宸'];
    const RANK_POWER = { '更衣':1,'官女子':2,'答应':4,'常在':5,'贵人':6,'才人':7,'美人':8,'婕妤':9,'嫔':10,'妃':11,'贵妃':17,'皇贵妃':18,'皇后':19 };
    function _rankPower(rankName, nobletitle) {
        if (rankName === '妃' && nobletitle) {
            return FOUR_CONSORT_TITLES.includes(nobletitle) ? FOUR_CONSORT_POWER : TITLED_CONSORT_POWER;
        }
        return RANK_POWER[rankName] !== undefined ? RANK_POWER[rankName] : 3;
    }

    function _rankLevel(rankName, nobletitle) {
        return _rankPower(rankName, nobletitle);
    }

    function _familyScore(family, familyMeta) {
        return clanFamilyScore(family, familyMeta);
    }

    function _getRankName(rank) {
        if (rank && typeof rank === 'object' && rank.name) return rank.name;
        return String(rank || '答应');
    }

    function _statValue(gameState, who, attrKey, isPlayer) {
        let attrs, rank, nobletitle, family, familyMeta, people;

        if (isPlayer) {
            attrs = gameState.attributes || {};
            rank = _getRankName(gameState.rank);
            nobletitle = gameState.nobletitle;
            family = gameState.family_background;
            familyMeta = gameState.family_meta;
            people = (gameState.get_active_servants ? gameState.get_active_servants().length : 0) * 12;
        } else {
            const npc = (gameState.npcs && gameState.npcs[who]) || {};
            attrs = npc.attributes || {};
            rank = npc.rank || '答应';
            nobletitle = npc.nobletitle;
            family = npc.family_background || '未知';
            familyMeta = npc.family_meta;
            people = randomInt(8, 40);
        }

        const mapping = {
            '宠爱': attrs['宠爱'] !== undefined ? attrs['宠爱'] : 30,
            '健康': attrs['健康'] !== undefined ? attrs['健康'] : 60,
            '心计': attrs['心计'] !== undefined ? attrs['心计'] : 40,
            '才情': attrs['才情'] !== undefined ? attrs['才情'] : 40,
            '福运': attrs['福运'] !== undefined ? attrs['福运'] : 30,
            '家世': _familyScore(family, familyMeta) + (attrs['威望'] !== undefined ? attrs['威望'] : 20) * 0.25,
            '位份': _rankLevel(rank, nobletitle) * 8 + 10,
            '人手': people,
        };

        return parseFloat(mapping[attrKey] !== undefined ? mapping[attrKey] : 40);
    }

    function availableSkills(rankName) {
        let n = 2 + Math.floor(_rankLevel(rankName) / 3);
        n = Math.max(2, Math.min(5, n));
        const keys = Object.keys(DUEL_SKILLS);
        return keys.slice(0, n);
    }

    function periodKey(gameState) {
        return gameState.year + '-' + gameState.month + '-' + gameState.day;
    }

    function startDuel(gameState, target) {
        const existing = gameState._active_duel;
        if (existing && !existing.finished) {
            return [existing, null];
        }
        if (!gameState.npcs || !gameState.npcs[target]) {
            return [null, '目标不存在'];
        }
        const npc = gameState.npcs[target];
        if (!npc.alive || !npc.is_active) {
            return [null, '对方已不在后宫'];
        }
        const last = gameState.last_duel_period;
        if (last === periodKey(gameState)) {
            return [null, '本旬已主动争锋一次，下旬再来'];
        }
        const pSkills = availableSkills(_getRankName(gameState.rank));
        const nSkills = availableSkills(npc.rank || '答应');
        const duel = {
            target: target,
            player_score: 0,
            npc_score: 0,
            player_left: pSkills.slice(),
            npc_left: nSkills.slice(),
            log: ['你邀约' + extractSurname(target) + (npc.rank || '妃嫔') + '争锋，帘后对坐，茶未凉而杀机已起。'],
            finished: false,
        };
        gameState._active_duel = duel;
        return [duel, null];
    }

    function playDuelSkill(gameState, skillKey) {
        const duel = gameState._active_duel;
        if (!duel || duel.finished) {
            return [null, '当前没有进行中的争锋'];
        }
        if (duel.player_left.indexOf(skillKey) === -1) {
            return [null, '这招已经用过，或你尚未习得'];
        }
        const target = duel.target;
        const skill = DUEL_SKILLS[skillKey];
        const pVal = _statValue(gameState, gameState.name, skill.attr, true);
        const nVal = _statValue(gameState, target, skill.attr, false);
        const luck = randomUniform(0.88, 1.12);
        const pHit = pVal * luck;
        const nHit = nVal * randomUniform(0.88, 1.12);
        const delta = Math.floor(Math.abs(pHit - nHit) / 6) + 8;
        if (pHit >= nHit) {
            duel.player_score += delta;
            duel.log.push('【' + skillKey + '】' + skill.desc + '——你占上风（' + Math.floor(pVal) + ' vs ' + Math.floor(nVal) + '），评分 +' + delta);
        } else {
            duel.npc_score += delta;
            duel.log.push('【' + skillKey + '】' + skill.desc + '——对方更胜一筹（' + Math.floor(pVal) + ' vs ' + Math.floor(nVal) + '），对方评分 +' + delta);
        }
        const idx = duel.player_left.indexOf(skillKey);
        duel.player_left.splice(idx, 1);

        if (duel.npc_left.length > 0) {
            const npcSkill = randomChoice(duel.npc_left);
            const ns = DUEL_SKILLS[npcSkill];
            const p2 = _statValue(gameState, gameState.name, ns.attr, true);
            const n2 = _statValue(gameState, target, ns.attr, false);
            const d2 = Math.floor(Math.abs(p2 - n2) / 6) + 8;
            if (n2 * randomUniform(0.9, 1.1) >= p2) {
                duel.npc_score += d2;
                duel.log.push('对方使出【' + npcSkill + '】，' + ns.desc + '，对方评分 +' + d2);
            } else {
                duel.player_score += d2;
                duel.log.push('对方使出【' + npcSkill + '】，反被你压过，你评分 +' + d2);
            }
            const npcIdx = duel.npc_left.indexOf(npcSkill);
            duel.npc_left.splice(npcIdx, 1);
        }

        if (!duel.player_left.length || (!duel.npc_left.length && !duel.player_left.length)) {
            duel.finished = true;
            if (duel.player_score > duel.npc_score) {
                duel.winner = 'player';
                duel.log.push('争锋落幕。你 ' + duel.player_score + ' : ' + duel.npc_score + ' 对方。可择处置。');
            } else if (duel.player_score < duel.npc_score) {
                duel.winner = 'npc';
                duel.log.push('争锋落幕。你 ' + duel.player_score + ' : ' + duel.npc_score + ' 对方。此番受挫。');
            } else {
                duel.winner = 'draw';
                duel.log.push('争锋落幕。平手 ' + duel.player_score + '。帘外风停，各自散去。');
            }
        }
        return [duel, null];
    }

    function resolveDuel(gameState, drainKey) {
        const duel = gameState._active_duel;
        if (!duel || !duel.finished) {
            return [null, '争锋尚未结束'];
        }
        const target = duel.target;
        const npc = gameState.npcs[target] || {};
        if (!npc.attributes) npc.attributes = {};
        const nattrs = npc.attributes;
        const pattrs = gameState.attributes || {};
        const margin = Math.abs(duel.player_score - duel.npc_score);
        let steal = Math.min(18, 6 + Math.floor(margin / 8));
        const effects = {};
        let narration = '';
        const winner = duel.winner;

        if (winner === 'player') {
            if (!DRAIN_OPTIONS[drainKey]) {
                drainKey = '降其心智';
            }
            if (drainKey === '以理服人' && (pattrs['心计'] || 0) < 55) {
                return [null, '心计不足 55，尚不能以理服人'];
            }
            const opt = DRAIN_OPTIONS[drainKey];
            if (opt.self === 'all') {
                ['心计', '威望', '倾向'].forEach(function (k) {
                    const gain = Math.max(2, Math.floor(steal / 2));
                    const cap = typeof gameState.get_attr_max === 'function' ? gameState.get_attr_max(k) : 100;
                    pattrs[k] = Math.min(cap, (pattrs[k] !== undefined ? pattrs[k] : 30) + gain);
                    nattrs[k] = Math.max(0, (nattrs[k] !== undefined ? nattrs[k] : 40) - gain);
                    effects[k] = gain;
                });
            } else {
                const k = opt.self;
                const cap = typeof gameState.get_attr_max === 'function' ? gameState.get_attr_max(k) : 100;
                pattrs[k] = Math.min(cap, (pattrs[k] !== undefined ? pattrs[k] : 30) + steal);
                nattrs[k] = Math.max(0, (nattrs[k] !== undefined ? nattrs[k] : 40) - steal);
                effects[k] = steal;
            }
            npc['压力'] = Math.min(120, (npc['压力'] !== undefined ? npc['压力'] : 20) + 8 + Math.floor(steal / 2));
            if (gameState.relationships && gameState.relationships[target]) {
                gameState.relationships[target]['好感'] = Math.max(-100, (gameState.relationships[target]['好感'] || 0) + opt.favor);
            }
            if (!gameState.rivalries) gameState.rivalries = {};
            gameState.rivalries[target] = (gameState.rivalries[target] || 0) + 8;
            narration = '你胜了' + target + '，择「' + drainKey + '」。' + opt.desc + '。对方压力攀升。';
        } else if (winner === 'npc') {
            steal = Math.max(4, Math.floor(steal / 2));
            ['心计', '倾向'].forEach(function (k) {
                pattrs[k] = Math.max(0, (pattrs[k] !== undefined ? pattrs[k] : 30) - steal);
                nattrs[k] = Math.min(100, (nattrs[k] !== undefined ? nattrs[k] : 40) + Math.floor(steal / 2));
                effects[k] = -steal;
            });
            pattrs['威望'] = Math.max(0, (pattrs['威望'] !== undefined ? pattrs['威望'] : 20) - 3);
            effects['威望'] = (effects['威望'] !== undefined ? effects['威望'] : 0) - 3;
            if (gameState.relationships && gameState.relationships[target]) {
                gameState.relationships[target]['好感'] = Math.max(-100, (gameState.relationships[target]['好感'] || 0) - 10);
            }
            narration = '你败于' + target + '。颜面受损，心计与倾向皆挫。';
        } else {
            narration = '与' + target + '争锋未分胜负，各自收场。';
        }

        gameState.last_duel_period = periodKey(gameState);
        gameState._active_duel = null;
        if (typeof gameState.add_memory === 'function') {
            gameState.add_memory(narration);
        }
        if (typeof gameState.add_attr_change === 'function') {
            gameState.add_attr_change(effects, '争锋：' + target);
        }
        return [{
            narration: narration,
            effects: effects,
            log: duel.log,
            winner: winner,
            player_score: duel.player_score,
            npc_score: duel.npc_score,
            pressure: npc['压力'] || 0,
        }, null];
    }

    function chatProbe(gameState, npcName) {
        const npc = gameState.npcs && gameState.npcs[npcName];
        if (!npc) {
            return [null, '妃嫔不在'];
        }
        const pWit = (gameState.attributes && gameState.attributes['心计']) || 40;
        const nWit = (npc.attributes && npc.attributes['心计']) || 50;
        const revealed = [];
        let hint;
        if (pWit + randomInt(0, 20) >= nWit) {
            revealed.push('性格：' + (npc.personality || '难测') + '（' + (npc.personality_desc || '') + '）');
            revealed.push('心计约 ' + nWit);
            revealed.push('倾向 ' + ((npc.attributes && npc.attributes['倾向']) || '?') + '，压力 ' + (npc['压力'] || 0));
            hint = '闲聊间，她心思已被你摸清几分。';
        } else {
            hint = '闲聊数句，她笑意浅淡，什么也没透。聊不出性格与心计，说明暂且惹不起。';
            revealed.push('未探明');
        }
        if (gameState.relationships && gameState.relationships[npcName]) {
            gameState.relationships[npcName]['好感'] = Math.min(100, (gameState.relationships[npcName]['好感'] || 0) + randomInt(0, 3));
            gameState.relationships[npcName]['互动次数'] = (gameState.relationships[npcName]['互动次数'] || 0) + 1;
        }
        const narration = hint + ' ' + revealed.join('；');
        return [{ narration: narration, revealed: revealed, safe_to_duel: pWit + 10 >= nWit }, null];
    }

    function prayOrCurse(gameState, mode, target) {
        if (mode === 'bless') {
            const cost = 15;
            if (gameState.silver < cost) {
                return [null, '银两不足，香火钱要十五两'];
            }
            gameState.silver -= cost;
            const luck = randomInt(4, 9);
            const tend = randomInt(1, 4);
            if (!gameState.attributes) gameState.attributes = {};
            gameState.attributes['福运'] = Math.min(100, (gameState.attributes['福运'] || 30) + luck);
            gameState.attributes['倾向'] = Math.min(100, (gameState.attributes['倾向'] || 30) + tend);
            let extra = '';
            if (Math.random() < 0.18) {
                const fav = randomInt(2, 6);
                const favCap = typeof gameState.get_attr_max === 'function' ? gameState.get_attr_max('宠爱') : 100;
                gameState.attributes['宠爱'] = Math.min(favCap, (gameState.attributes['宠爱'] || 0) + fav);
                extra = ' 签上显「宠」字，宠爱+' + fav + '。';
            }
            const narration = '你至奉天楼焚香祈福。福运+' + luck + '，倾向+' + tend + '。' + extra;
            const effects = { '福运': luck, '倾向': tend, '银两': -cost };
            if (typeof gameState.add_memory === 'function') {
                gameState.add_memory(narration);
            }
            if (typeof gameState.add_attr_change === 'function') {
                gameState.add_attr_change(effects, '奉天楼祈福');
            }
            return [{ narration: narration, effects: effects }, null];
        }

        if (mode === 'curse') {
            const cost = 40;
            if (gameState.silver < cost) {
                return [null, '掌祀需四十两香火与纸钱'];
            }
            if (!target || !gameState.npcs || !gameState.npcs[target]) {
                return [null, '请选定要克的妃嫔'];
            }
            if ((gameState.attributes && gameState.attributes['心计']) || 0 < 25) {
                return [null, '心计太浅，掌祀只恐反噬'];
            }
            gameState.silver -= cost;
            const npc = gameState.npcs[target];
            const press = randomInt(12, 22);
            const luckCut = randomInt(3, 8);
            npc['压力'] = Math.min(120, (npc['压力'] || 20) + press);
            if (!npc.attributes) npc.attributes = {};
            const nattrs = npc.attributes;
            nattrs['福运'] = Math.max(0, (nattrs['福运'] || 40) - luckCut);
            let backfire = '';
            if (Math.random() < 0.22) {
                const selfCut = randomInt(2, 6);
                if (!gameState.attributes) gameState.attributes = {};
                gameState.attributes['福运'] = Math.max(0, (gameState.attributes['福运'] || 30) - selfCut);
                backfire = ' 香灰骤灭，自身福运-' + selfCut + '。';
            }
            if (gameState.relationships && gameState.relationships[target]) {
                gameState.relationships[target]['好感'] = Math.max(-100, (gameState.relationships[target]['好感'] || 0) - 6);
            }
            if (!gameState.rivalries) gameState.rivalries = {};
            gameState.rivalries[target] = (gameState.rivalries[target] || 0) + 5;
            const narration = '你在奉天楼暗行掌祀，克向' + target + '。对方压力+' + press + '，福运-' + luckCut + '。' + backfire;
            const effects = { '银两': -cost };
            if (typeof gameState.add_memory === 'function') {
                gameState.add_memory(narration);
            }
            return [{ narration: narration, effects: effects, pressure: npc['压力'] }, null];
        }

        return [null, '无效仪式'];
    }

    function processPressure(gameState) {
        const events = [];
        const npcs = gameState.npcs || {};
        for (const name in npcs) {
            if (!Object.prototype.hasOwnProperty.call(npcs, name)) continue;
            const npc = npcs[name];
            if (name === '太后' || !npc.alive) continue;
            let press = npc['压力'] || 20;
            if (press > 15) {
                npc['压力'] = Math.max(0, press - randomInt(1, 4));
            }
            press = npc['压力'] || 0;
            if (press >= 100) {
                if (!npc.attributes) npc.attributes = {};
                const nattrs = npc.attributes;
                const loss = randomInt(8, 16);
                nattrs['心计'] = Math.max(5, (nattrs['心计'] || 40) - loss);
                nattrs['倾向'] = Math.max(0, (nattrs['倾向'] || 40) - loss);
                nattrs['健康'] = Math.max(10, (nattrs['健康'] || 60) - 6);
                npc['压力'] = randomInt(35, 55);
                npc.personality = '心神不宁';
                events.push('💔 ' + name + ' 压力难承，竟至疯癫边缘，心计与斗志大损。');
            } else if (press >= 70 && Math.random() < 0.35) {
                events.push('😟 ' + name + ' 近日神思恍惚，宫人说她夜里常惊坐。');
            }
        }
        const attrs = gameState.attributes || {};
        if ((attrs['倾向'] || 30) < 20 && Math.random() < 0.2) {
            events.push('你自觉气势不足，行走宫道都要让人三分。');
        }
        return events;
    }

    window.GameModules.palace_extra = {
        DUEL_SKILLS: DUEL_SKILLS,
        DRAIN_OPTIONS: DRAIN_OPTIONS,
        RANK_ORDER_LOCAL: RANK_ORDER_LOCAL,
        available_skills: availableSkills,
        period_key: periodKey,
        start_duel: startDuel,
        play_duel_skill: playDuelSkill,
        resolve_duel: resolveDuel,
        chat_probe: chatProbe,
        pray_or_curse: prayOrCurse,
        process_pressure: processPressure,
    };
})();
