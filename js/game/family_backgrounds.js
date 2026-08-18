(function () {
    'use strict';

    window.GameModules = window.GameModules || {};
    const names = window.GameModules.names || {};

    const EMPEROR_GIVEN = names.EMPEROR_GIVEN || [];
    const NPC_SURNAMES = names.NPC_SURNAMES || [];
    const extractSurname = names.extract_surname || function (n) { return (n && n[0]) || '某'; };
    const generateFemaleNameForSurname = names.generate_female_name_for_surname || function (s) { return s + '婉'; };
    const randomGiven = names.random_given || function (pool) { return pool[Math.floor(Math.random() * pool.length)] || '某'; };
    const randomSurname = names.random_surname || function (pool) { return (pool || NPC_SURNAMES)[Math.floor(Math.random() * (pool || NPC_SURNAMES).length)] || '林'; };

    function randomChoice(arr) {
        return arr[Math.floor(Math.random() * arr.length)];
    }

    function weightedChoice(items, weights) {
        const total = weights.reduce(function (a, b) { return a + b; }, 0);
        let r = Math.random() * total;
        for (let i = 0; i < items.length; i++) {
            r -= weights[i];
            if (r <= 0) return items[i];
        }
        return items[items.length - 1];
    }

    const MINISTRIES = ['吏部', '户部', '礼部', '兵部', '刑部', '工部'];

    const DAUGHTER_STATUSES = [
        { key: '嫡', weight: 32, rank_offset: 0, score_mod: 12, attr: { '威望': 2, '魅力': 2 } },
        { key: '庶', weight: 38, rank_offset: 1, score_mod: 0, attr: { '心计': 2 } },
        { key: '养', weight: 18, rank_offset: 2, score_mod: -10, attr: { '福运': 1, '心计': 1 } },
        { key: '私生', weight: 12, rank_offset: 2, score_mod: -20, attr: { '心计': 3, '容貌': -1 } },
    ];

    const PLAYER_START_RANKS = ['秀女', '答应', '常在', '贵人', '嫔'];

    const GRADE_BASE_RANK_INDEX = { 1: 4, 2: 4, 3: 3, 4: 3, 5: 2, 6: 2, 7: 1, 8: 1, 9: 0 };

    const GRADE_BASE_SCORE = { 1: 88, 2: 78, 3: 70, 4: 62, 5: 55, 6: 48, 7: 42, 8: 36, 9: 30 };

    const GRADE_WEIGHTS = [1, 2, 3, 4, 5, 6, 7, 8, 9];
    const GRADE_WEIGHT_VALUES = [2, 3, 6, 10, 14, 18, 16, 12, 6];
    const PLAYER_GRADE_WEIGHT_VALUES = [3, 5, 8, 12, 16, 14, 10, 6, 4];

    const GRADE_ATTR_BONUS = {
        1: { '威望': 5, '才情': 3, '魅力': 3 },
        2: { '威望': 4, '才情': 2, '魅力': 2 },
        3: { '威望': 3, '才情': 2, '魅力': 1 },
        4: { '威望': 2, '才情': 1 },
        5: { '威望': 1, '才情': 1 },
        6: { '心计': 1 },
        7: { '心计': 1, '福运': 1 },
        8: { '福运': 1 },
        9: { '福运': 1 },
    };

    const STORY_OPENERS = {
        '嫡': [
            '身为{official_name}嫡女，自幼受教于庭训，族中对我寄予厚望。',
            '我是{official_name}的嫡出女儿，门楣虽高，选秀入宫后每一步都关乎家族荣辱。',
            '家父{official_name}膝下嫡女，自幼习礼明义。选秀诏下，我便知此生再难只做闺阁中人。',
        ],
        '庶': [
            '我是{official_name}的庶出女儿，自幼谨小慎微，却也不得不被推上选秀之路。',
            '庶出之身让我比旁人更早学会察言观色。家父{official_name}说，入宫或是我最好的出路。',
            '同为{official_name}之女，我却只是庶出。选秀入选后，我更知唯有自强方能立足。',
        ],
        '养': [
            '我本是养女，由{official_name}抚养成人。虽非亲生，却也承蒙栽培，选秀入宫是我报答恩情的方式。',
            '寄养在{official_name}门下多年，外人只当我也是府中千金。入宫之后，这身份反倒成了我的枷锁。',
            '养女之身，名分尴尬。{official_name}将我送入宫中，说是为我寻一条生路。',
        ],
        '私生': [
            '私生女的身份，我从未对人言明。家父{official_name}将我送入宫中，或许只是想抹去这段不堪。',
            '我出身隐秘，是{official_name}不愿承认的女儿。选秀入选，是我为自己挣下的唯一名分。',
            '名分不正，自幼受尽冷眼。{official_name}将我送进深宫，说是成全，更像是安置。',
        ],
    };

    const STORY_MIDDLES_HIGH = [
        '父亲现任{title}，朝堂上颇有声名，京中无人不知{family_label}。',
        '父亲官至{title}，府中门客往来不绝，我耳濡目染，也略懂朝局利害。',
        '家父{official_name}如今是{title}，族中荣耀皆系于他一身，我亦不敢辜负。',
    ];

    const STORY_MIDDLES_MID = [
        '父亲任{title}，虽非权倾朝野，却也足以在地方称一方人物。',
        '家父{official_name}现为{title}，门第清贵，却也算不得京城顶流。',
        '父亲在任{title}，家教谨严，我入宫前便被告知，谨言慎行方能保全。',
    ];

    const STORY_MIDDLES_LOW = [
        '父亲只是{title}，品秩不高，家族指望我入宫谋个出身。',
        '家父{official_name}官居{title}，门楣平常，选秀于我而言，几乎是唯一的出路。',
        '父亲任{title}，俸禄微薄，送我入宫选秀，不过是想为家族博一线机会。',
    ];

    const STORY_CLOSERS = {
        '琴艺': '我自幼习琴，指下清音曾慰父亲心绪，入宫后亦想以才艺自保。',
        '棋艺': '我善弈棋，棋盘上的进退取舍，与这后宫生存之道竟有几分相似。',
        '书法': '我苦练书法，一笔一画皆求端正，入宫后更知行事亦需如此。',
        '绘画': '我嗜丹青，画中山水虽静，却难比这深宫波澜。',
        '诗词': '我略通诗词，曾以一首咏梅诗得父亲夸赞，入宫后亦不敢荒废笔墨。',
        '舞蹈': '我善舞，曾在家宴上献舞娱亲，如今这舞技或许也是我的倚仗。',
        '歌喉': '我歌喉清越，闺中时常练唱，入宫后或能以声动人。',
        '刺绣': '我精于刺绣，针黹之间见心性，这手艺或许能让我在宫中立足。',
        '医术': '我随府医略通药理，入宫后见惯了人情冷暖，更觉医术可贵。',
        '茶道': '我善茶道，烹茶如待人，水温火候皆不可差。',
        '花艺': '我喜莳花弄草，闺中庭院四季有香，入宫后最念那抹清幽。',
        '香道': '我习香道，识得诸般香料，这嗅觉或许能助我避开宫中险恶。',
        '骑射': '我自幼习骑射，不似寻常闺秀娇弱，入宫后也不愿轻易示弱。',
        '烹饪': '我厨艺尚可，曾亲手为父亲备膳，入宫后这手艺倒成了慰藉。',
        '音律': '我通晓音律，丝竹之声曾是我闺中时光最好的陪伴。',
        '兵法': '我读过兵书，虽为女子，却也知进退攻守之理。',
        '占卜': '我略通占卜，冥冥之中或有天意，入宫前曾卜过一卦，结果吉凶难辨。',
        '酿酒': '我善酿酒，府中家宴上的佳酿多出自我的手，入宫后这技艺怕是难再施展。',
    };

    const PERSONALITY_CLOSERS = {
        '温婉贤淑': '性情温婉，我只盼在深宫中守住本心，不争不抢。',
        '端庄大方': '我行事向来端庄，入宫后更须步步谨慎，不负家教。',
        '活泼开朗': '我生性开朗，纵使深宫幽深，也不愿失了生气。',
        '冷傲孤高': '我性情孤高，不屑逢迎，可这宫里由不得人清高。',
        '聪慧机敏': '我心思灵敏，入宫前便知这后宫从无净土。',
        '心机深沉': '我惯于谋算，入宫不过是另一盘棋局的开端。',
        '温柔可人': '我待人温柔，只愿以真心换真心，却不知这宫中真心几何。',
        '刚烈果断': '我性情刚烈，宁折不弯，入宫后也不会轻易低头。',
        '娴静淡雅': '我性情淡雅，不爱争宠，却也不信淡泊便能自保。',
        '娇俏灵动': '我娇俏灵动，或能以几分鲜活在这沉闷宫墙内博得一线生机。',
        '沉稳内敛': '我沉稳内敛，遇事不慌，入宫后更须藏锋守拙。',
        '明媚张扬': '我明媚张扬，不愿做个默默无闻的妃嫔。',
        '潇洒不羁': '我潇洒不羁，深宫规矩繁多，与我本性多有相悖。',
        '纯真无邪': '我心思单纯，入宫前对后宫险恶只有模糊想象。',
        '坚韧隐忍': '我惯于隐忍，再大的委屈也能咽下，只等一个时机。',
    };

    const PLAYER_FAMILY_OPTIONS = [];

    function _pickOfficialTitle(grade) {
        if (grade === 1) {
            return randomChoice(['太师', '太傅', '太保', '内阁首辅', '文华殿大学士']);
        }
        if (grade === 2) {
            const m = randomChoice(MINISTRIES);
            return randomChoice([m + '尚书', '都察院左都御史', '两江总督', '湖广总督', '闽浙总督']);
        }
        if (grade === 3) {
            const m = randomChoice(MINISTRIES);
            return randomChoice([m + '侍郎', '顺天巡抚', '山东巡抚', '河南巡抚', '四川巡抚']);
        }
        if (grade === 4) {
            const m = randomChoice(MINISTRIES);
            return randomChoice([m + '郎中', '参将', '按察使', '盐运使']);
        }
        if (grade === 5) {
            return randomChoice(['知府', '同知', '通判', '参将', '副将']);
        }
        if (grade === 6) {
            return randomChoice(['知州', '同知', '通判', '州判', '都事']);
        }
        if (grade === 7) {
            return randomChoice(['知县', '县丞', '主簿', '经历', '巡检']);
        }
        if (grade === 8) {
            return randomChoice(['县丞', '主簿', '典史', '吏目', '巡检']);
        }
        return randomChoice(['典史', '吏目', '未入流训导', '巡检']);
    }

    function _pickDaughterStatus() {
        const keys = DAUGHTER_STATUSES.map(function (s) { return s.key; });
        const weights = DAUGHTER_STATUSES.map(function (s) { return s.weight; });
        const key = weightedChoice(keys, weights);
        for (let i = 0; i < DAUGHTER_STATUSES.length; i++) {
            if (DAUGHTER_STATUSES[i].key === key) return DAUGHTER_STATUSES[i];
        }
        return DAUGHTER_STATUSES[1];
    }

    function _officialGivenName() {
        return randomGiven(EMPEROR_GIVEN, 0.55);
    }

    function _rankBonusFor(grade, status) {
        const baseIdx = GRADE_BASE_RANK_INDEX[grade] || 0;
        const idx = Math.max(0, Math.min(PLAYER_START_RANKS.length - 1, baseIdx - status.rank_offset));
        return PLAYER_START_RANKS[idx];
    }

    function _attrBonusFor(grade, status) {
        const bonus = Object.assign({}, GRADE_ATTR_BONUS[grade] || {});
        const attr = status.attr || {};
        for (const k in attr) {
            if (Object.prototype.hasOwnProperty.call(attr, k)) {
                bonus[k] = (bonus[k] || 0) + attr[k];
            }
        }
        return bonus;
    }

    function _scoreFor(grade, status) {
        return Math.max(20, Math.min(95, (GRADE_BASE_SCORE[grade] || 40) + status.score_mod));
    }

    function formatTemplate(template, fmt) {
        return template.replace(/\{(\w+)\}/g, function (_, key) {
            return fmt[key] !== undefined ? fmt[key] : '';
        });
    }

    function generateOfficialBackground(surname, forPlayer) {
        surname = (surname || '').trim() || randomSurname(NPC_SURNAMES);

        const grade = forPlayer
            ? weightedChoice(GRADE_WEIGHTS, PLAYER_GRADE_WEIGHT_VALUES)
            : weightedChoice(GRADE_WEIGHTS, GRADE_WEIGHT_VALUES);
        const title = _pickOfficialTitle(grade);
        const status = _pickDaughterStatus();
        const given = _officialGivenName();
        const officialName = surname + given;
        const label = title + officialName + '（' + status.key + '）女';

        const statusDesc = {
            '嫡': '嫡出千金，族中寄予厚望',
            '庶': '庶出之女，自幼谨小慎微',
            '养': '养女之身，寄人篱下却得栽培',
            '私生': '私生之女，名分尴尬却不得不选秀',
        };
        const desc = '父' + officialName + '，现任' + title + '，' + statusDesc[status.key];

        const score = _scoreFor(grade, status);
        const meta = {
            surname: surname,
            official_title: title,
            official_name: officialName,
            official_grade: grade,
            daughter_status: status.key,
            score: score,
        };

        const result = {
            id: label,
            label: label,
            desc: desc,
            meta: meta,
            score: score,
        };

        if (forPlayer) {
            result.rankBonus = _rankBonusFor(grade, status);
            result.attrBonus = _attrBonusFor(grade, status);
        }

        return result;
    }

    function generateOfficialBackgroundForName(fullName, forPlayer) {
        return generateOfficialBackground(extractSurname(fullName), forPlayer);
    }

    function generateConcubineIdentity(surnames) {
        const surname = randomSurname(surnames || NPC_SURNAMES);
        const name = generateFemaleNameForSurname(surname);
        const bg = generateOfficialBackground(surname);
        return [name, bg];
    }

    function generateBackgroundStory(bg, playerName, talent, personality) {
        const meta = (bg && bg.meta) || {};
        const status = meta.daughter_status || '庶';
        const title = meta.official_title || '官员';
        const officialName = meta.official_name || '某人';
        const grade = meta.official_grade || 5;
        const familyLabel = (bg && bg.label) || (title + officialName + '（' + status + '）女');

        const openerPool = STORY_OPENERS[status] || STORY_OPENERS['庶'];
        const opener = randomChoice(openerPool);
        let middlePool;
        if (grade <= 3) {
            middlePool = STORY_MIDDLES_HIGH;
        } else if (grade <= 6) {
            middlePool = STORY_MIDDLES_MID;
        } else {
            middlePool = STORY_MIDDLES_LOW;
        }
        const middle = randomChoice(middlePool);

        const fmt = {
            official_name: officialName,
            title: title,
            family_label: familyLabel,
            status: status,
            player_name: playerName || '我',
        };
        const parts = [formatTemplate(opener, fmt), formatTemplate(middle, fmt)];

        if (talent && STORY_CLOSERS[talent]) {
            parts.push(STORY_CLOSERS[talent]);
        }
        if (personality && PERSONALITY_CLOSERS[personality]) {
            parts.push(PERSONALITY_CLOSERS[personality]);
        }

        return parts.join('');
    }

    function getFamilyScore(family, familyMeta) {
        if (familyMeta && typeof familyMeta === 'object') {
            return familyMeta.score !== undefined ? familyMeta.score : 45;
        }
        if (!family) {
            return 40;
        }
        if (family === '皇室宗亲') {
            return 95;
        }
        const text = String(family);
        if (text.indexOf('（私生）') !== -1) {
            return 35;
        }
        if (text.indexOf('（养）') !== -1) {
            return 42;
        }
        if (text.indexOf('（庶）') !== -1) {
            return 52;
        }
        if (text.indexOf('（嫡）') !== -1) {
            let base = 68;
            if (['太师', '太傅', '太保', '首辅', '大学士'].some(function (t) { return text.indexOf(t) !== -1; })) {
                return Math.min(95, base + 18);
            }
            if (text.indexOf('尚书') !== -1 || text.indexOf('总督') !== -1) {
                return Math.min(90, base + 12);
            }
            if (text.indexOf('侍郎') !== -1 || text.indexOf('巡抚') !== -1) {
                return Math.min(82, base + 6);
            }
            return base;
        }
        const highTitles = ['太师', '太傅', '太保', '首辅', '大学士', '尚书', '总督'];
        const midTitles = ['侍郎', '巡抚', '郎中', '按察使'];
        const lowTitles = ['知府', '知州', '知县', '县丞', '典史', '吏目'];
        if (highTitles.some(function (t) { return text.indexOf(t) !== -1; })) {
            return 72;
        }
        if (midTitles.some(function (t) { return text.indexOf(t) !== -1; })) {
            return 58;
        }
        if (lowTitles.some(function (t) { return text.indexOf(t) !== -1; })) {
            return 42;
        }
        return 45;
    }

    function randomFamilyClan(surname) {
        const bg = generateOfficialBackground(surname || randomSurname());
        return bg.label;
    }

    window.GameModules.family_backgrounds = {
        MINISTRIES: MINISTRIES,
        DAUGHTER_STATUSES: DAUGHTER_STATUSES,
        PLAYER_START_RANKS: PLAYER_START_RANKS,
        GRADE_BASE_RANK_INDEX: GRADE_BASE_RANK_INDEX,
        GRADE_BASE_SCORE: GRADE_BASE_SCORE,
        GRADE_WEIGHTS: GRADE_WEIGHTS,
        GRADE_WEIGHT_VALUES: GRADE_WEIGHT_VALUES,
        GRADE_ATTR_BONUS: GRADE_ATTR_BONUS,
        STORY_OPENERS: STORY_OPENERS,
        STORY_MIDDLES_HIGH: STORY_MIDDLES_HIGH,
        STORY_MIDDLES_MID: STORY_MIDDLES_MID,
        STORY_MIDDLES_LOW: STORY_MIDDLES_LOW,
        STORY_CLOSERS: STORY_CLOSERS,
        PERSONALITY_CLOSERS: PERSONALITY_CLOSERS,
        PLAYER_FAMILY_OPTIONS: PLAYER_FAMILY_OPTIONS,
        generate_official_background: generateOfficialBackground,
        generate_official_background_for_name: generateOfficialBackgroundForName,
        generate_concubine_identity: generateConcubineIdentity,
        generate_background_story: generateBackgroundStory,
        get_family_score: getFamilyScore,
        random_family_clan: randomFamilyClan,
    };
})();
