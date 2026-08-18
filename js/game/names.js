// names.js — 好听、可冷门、不难听的宫廷名库
(function (global) {
    'use strict';

    const PLAYER_SURNAMES = [
        "林", "沈", "柳", "苏", "顾", "陆", "谢", "江", "萧", "楚",
        "叶", "白", "温", "安", "云", "沐", "秦", "许", "唐", "贺",
        "颜", "殷", "钟", "崔", "卢", "程", "薛", "罗", "常", "乐",
        "于", "时", "齐", "康", "余", "元", "孟", "平", "黄", "穆",
        "尹", "姚", "邵", "湛", "汪", "祁", "禹", "宋", "庞", "熊",
        "纪", "舒", "屈", "项", "祝", "董", "杜", "阮", "蓝", "闵",
        "席", "季", "贾", "路", "黎", "易", "文", "关", "聂", "晁",
        "荀", "郗", "班", "惠", "甄", "封", "饶", "鞠", "丰", "相",
        "查", "游", "竺", "权", "盖", "益", "桓", "裴", "卫", "蒋",
        "韩", "杨", "朱", "尤", "何", "吕", "施", "张", "孔", "曹",
        "严", "金", "魏", "陶", "姜", "戚", "邹", "喻", "柏", "窦",
        "章", "潘", "葛", "范", "彭", "韦", "昌", "马", "苗", "方",
        "俞", "任", "袁", "华", "周", "吴", "郑", "王", "冯", "陈",
        "上官", "南宫", "东方", "独孤", "公孙", "皇甫", "长孙", "尉迟",
        "欧阳", "司马", "慕容", "宇文", "令狐", "夏侯", "诸葛", "端木",
        "太史", "申屠", "澹台", "闻人", "司徒", "赫连",
    ];

    const NPC_SURNAMES = PLAYER_SURNAMES.slice();

    const EMPEROR_SURNAMES = [
        "萧", "李", "赵", "朱", "慕容", "宇文", "拓跋", "上官", "司马", "欧阳",
        "令狐", "公孙", "皇甫", "长孙", "尉迟", "独孤", "南宫", "东方", "端木",
        "太史", "申屠", "澹台", "闻人", "夏侯", "诸葛", "司徒", "赫连", "陆",
        "江", "沈", "顾", "谢", "裴", "桓", "荀", "班", "甄", "封",
    ];

    const FEMALE_GIVEN = [
        "婉", "容", "月", "烟", "荷", "清", "雪", "梅", "兰", "竹",
        "菊", "莲", "瑶", "琼", "琳", "琪", "玥", "璇", "玟", "珺",
        "瑾", "瑜", "莹", "雅", "静", "慧", "贤", "淑", "仪", "柔",
        "娴", "芷", "萱", "蕊", "蓉", "薇", "露", "霜", "霓", "锦",
        "素", "青", "碧", "紫", "丹", "彤", "绯", "茜", "芙", "棠",
        "槿", "茉", "芍", "苓", "蘅", "若", "伊", "萦", "澜", "漪",
        "珂", "珞", "瑛", "琬", "璐", "霏", "霖", "晴", "晗", "昕",
        "茵", "蓁", "洛", "沁", "怡", "悦", "宁", "姝", "妍", "嫣",
        "嫕", "嬛", "妤", "婕", "娉", "婷", "媛", "姿", "韵", "馥",
        "馨", "绾", "缈", "婵", "姗", "绚", "茗", "菡", "菖", "薷",
        "荇", "蘩", "蘼", "蕖", "芃", "荪", "萏", "霙", "昳", "潋",
        "晼", "涟", "霁", "岚", "岫", "荃", "晚", "晴", "嘉", "言", "知", "远",
        "修", "宜", "惠", "安", "端", "敏", "静", "和", "柔", "嘉",
        "昭", "华", "清", "蘅", "晚", "晴", "泠", "月", "缃", "素",
    ];

    const EMPEROR_GIVEN = [
        "渊", "湛", "翰", "翊", "祺", "彦", "澈", "瀚", "曜", "煜",
        "桓", "晟", "昱", "昊", "昶", "暄", "曦", "翎", "轩", "骞",
        "骐", "骥", "骧", "霖", "岚", "澜", "沧", "泓", "淳", "濯",
        "澄", "潇", "璟", "琰", "璋", "琮", "璜", "璞", "珏", "琛",
        "瑞", "祯", "祥", "禧", "景", "承", "乾", "玄", "朗", "修",
        "远", "嘉", "言", "知", "明", "清", "晏", "昭", "宁", "启",
        "元", "弘", "晔", "行", "安", "泽", "煜", "熙", "和", "嘉",
    ];

    const PRINCE_NAMES = [
        "承泽", "承煜", "景行", "景安", "永嘉", "永和", "启明", "启元",
        "昭宁", "昭远", "弘晔", "弘澈", "承熙", "承瑞", "知远", "修远",
        "清晏", "嘉言", "玄朗", "景澄",
    ];

    const PRINCESS_NAMES = [
        "清蘅", "婉宁", "昭华", "端敏", "惠安", "静和", "宜修", "瑾萱",
        "柔嘉", "娴雅", "清涟", "晚晴", "缃素", "泠月", "嘉言", "修宜",
        "晏宁", "晞华", "纨素", "璆华",
    ];

    const SERVANT_GIRL = ["春蘅", "夏涟", "秋缃", "冬泠", "翠筠", "青萝", "白芷", "红绡", "碧桃", "紫薇", "小蘅", "小涟"];
    const SERVANT_EUNUCH = ["安福", "顺德", "承喜", "永安", "小安", "小福", "小德", "小顺"];

    const COMPOUND_SURNAMES = [
        "上官", "司马", "欧阳", "慕容", "宇文", "拓跋", "令狐", "诸葛",
        "司徒", "司空", "夏侯", "长孙", "赫连", "尉迟", "独孤", "南宫",
        "东方", "端木", "太史", "申屠", "澹台", "公冶", "万俟", "闻人",
        "皇甫", "公孙",
    ];

    const CHILD_GIVEN_NAME_CATEGORIES = {
        "德行": ["德", "仁", "义", "礼", "智", "信", "忠", "孝", "廉", "耻", "谦", "让", "厚", "和", "恕", "敬", "慎", "恒", "毅", "直"],
        "才学": ["文", "武", "诗", "书", "画", "琴", "棋", "翰", "墨", "章", "学", "识", "博", "雅", "颖", "敏", "睿", "哲", "思", "言"],
        "吉祥": ["瑞", "祥", "福", "禄", "寿", "康", "宁", "安", "嘉", "祺", "昌", "隆", "泰", "顺", "吉", "庆", "禧", "佑", "臻", "盛"],
        "品格": ["慧", "静", "婉", "淑", "贤", "贞", "烈", "勇", "刚", "柔", "清", "纯", "真", "正", "明", "朗", "昭", "光", "辉", "耀"],
        "自然": ["云", "雨", "雪", "月", "星", "晨", "曦", "霖", "泽", "澜", "风", "霜", "露", "虹", "山", "川", "林", "竹", "松", "梅"],
    };

    const CHILD_GIVEN_CHARS = Object.values(CHILD_GIVEN_NAME_CATEGORIES).flat();

    function randomChoice(arr) {
        return arr[Math.floor(Math.random() * arr.length)];
    }

    function randomInt(min, max) {
        return Math.floor(Math.random() * (max - min + 1)) + min;
    }

    function shuffleArray(arr) {
        const copy = arr.slice();
        for (let i = copy.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [copy[i], copy[j]] = [copy[j], copy[i]];
        }
        return copy;
    }

    function randomGiven(pool, twoCharChance) {
        if (twoCharChance === undefined) twoCharChance = 0.55;
        let given = randomChoice(pool);
        if (Math.random() < twoCharChance) {
            let second = randomChoice(pool);
            while (second === given) {
                second = randomChoice(pool);
            }
            given += second;
        }
        return given;
    }

    function randomSurname(pool) {
        return randomChoice(pool || NPC_SURNAMES);
    }

    function generateFemaleName(surnames) {
        return generateFemaleNameForSurname(randomSurname(surnames));
    }

    function generateFemaleNameForSurname(surname) {
        surname = (surname || "").trim() || randomSurname();
        return surname + randomGiven(FEMALE_GIVEN, 0.52);
    }

    function generateEmperorNameLocal() {
        const surname = randomChoice(EMPEROR_SURNAMES);
        return surname + randomGiven(EMPEROR_GIVEN, 0.65);
    }

    function generateChildName(gender, used) {
        used = used || new Set();
        const pool = gender === "皇子" ? PRINCE_NAMES : PRINCESS_NAMES;
        const available = pool.filter(function (n) { return !used.has(n); });
        return randomChoice(available.length ? available : pool);
    }

    function generateServantName(type_) {
        const pool = type_ === "宫女" ? SERVANT_GIRL : SERVANT_EUNUCH;
        return randomChoice(pool);
    }

    function extractSurname(name) {
        if (!name) return "某";
        for (let i = 0; i < COMPOUND_SURNAMES.length; i++) {
            const s = COMPOUND_SURNAMES[i];
            if (name.startsWith(s)) return s;
        }
        return name[0];
    }

    function isValidGivenChar(char) {
        return Boolean(char) && CHILD_GIVEN_CHARS.indexOf(char) !== -1;
    }

    global.GameModules = global.GameModules || {};
    global.GameModules.names = {
        PLAYER_SURNAMES: PLAYER_SURNAMES,
        NPC_SURNAMES: NPC_SURNAMES,
        EMPEROR_SURNAMES: EMPEROR_SURNAMES,
        FEMALE_GIVEN: FEMALE_GIVEN,
        EMPEROR_GIVEN: EMPEROR_GIVEN,
        PRINCE_NAMES: PRINCE_NAMES,
        PRINCESS_NAMES: PRINCESS_NAMES,
        SERVANT_GIRL: SERVANT_GIRL,
        SERVANT_EUNUCH: SERVANT_EUNUCH,
        COMPOUND_SURNAMES: COMPOUND_SURNAMES,
        CHILD_GIVEN_NAME_CATEGORIES: CHILD_GIVEN_NAME_CATEGORIES,
        CHILD_GIVEN_CHARS: CHILD_GIVEN_CHARS,
        randomGiven: randomGiven,
        randomSurname: randomSurname,
        generateFemaleName: generateFemaleName,
        generateFemaleNameForSurname: generateFemaleNameForSurname,
        generateEmperorNameLocal: generateEmperorNameLocal,
        generateChildName: generateChildName,
        generateServantName: generateServantName,
        extractSurname: extractSurname,
        isValidGivenChar: isValidGivenChar,
        randomChoice: randomChoice,
        randomInt: randomInt,
        shuffleArray: shuffleArray,
    };
})(typeof window !== 'undefined' ? window : globalThis);
