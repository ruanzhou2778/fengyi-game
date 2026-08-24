# events.py
import random

from heir_content import (
    REGENCY_EVENT_POOL, HEIR_REBELLION_POOL, HEIR_SPECIAL_POOL,
    INCOGNITO_POOL, CONSORT_CANDIDATES, CONSORT_CONFLICT_POOL,
    CONSORT_FUN_POOL,
)

# ============================================================
#  转旬事件模板（共 79 条，涵盖争宠、陷害、拉拢、意外、日常）
# ============================================================
LOCAL_EVENT_TEMPLATES = [
    # ---- 第一批（45条） ----
    {"desc": "{npc1}在御花园中巧遇皇帝，以一曲琵琶博得青睐。", "effects": {"宠爱": (4, 10), "威望": (2, 6)}},
    {"desc": "{npc1}深夜在御书房外焚香祈祷，皇帝闻香召见。", "effects": {"宠爱": (5, 12), "威望": (3, 7)}},
    {"desc": "{npc1}得知皇帝喜爱茶道，特献上珍藏的武夷山大红袍。", "effects": {"宠爱": (3, 8), "威望": (4, 8)}},
    {"desc": "{npc1}在宫宴上即兴作画，献上一幅《江山万里图》。", "effects": {"宠爱": (4, 9), "才情": (3, 7), "威望": (3, 6)}},
    {"desc": "{npc1}与{npc2}同时献上寿礼，暗中较劲。", "effects": {"宠爱": (3, 8), "威望": (-2, 4), "心计": (2, 5)}},
    {"desc": "{npc1}在御前失仪，被罚抄写宫规三遍。", "effects": {"威望": (-4, -1), "宠爱": (-3, 0), "心计": (1, 3)}},
    {"desc": "{npc1}因一首诗被皇帝称赞，赐号“才人”。", "effects": {"宠爱": (6, 12), "才情": (4, 8), "威望": (5, 10)}},
    {"desc": "{npc1}在{npc2}的茶中放入巴豆，使其在太后面前失态。", "effects": {"心计": (5, 10), "威望": (-5, 2), "宠爱": (-3, 3)}},
    {"desc": "{npc1}诬陷{npc2}私通侍卫，闹得满城风雨。", "effects": {"心计": (6, 12), "威望": (-6, 2), "宠爱": (-4, 2)}},
    {"desc": "{npc1}在{npc2}的寝殿放置木偶，行巫蛊之术。", "effects": {"心计": (8, 15), "威望": (-10, -2), "宠爱": (-6, 0)}},
    {"desc": "{npc1}买通太医，让{npc2}误服寒凉之药。", "effects": {"心计": (7, 14), "健康": (-5, -1), "宠爱": (-4, 0)}},
    {"desc": "{npc1}故意在{npc2}面前摔碎皇后赏赐的玉如意，栽赃陷害。", "effects": {"心计": (6, 11), "威望": (-8, 0), "宠爱": (-5, 2)}},
    {"desc": "{npc1}指使宫女散布谣言，说{npc2}诅咒皇帝。", "effects": {"心计": (5, 9), "威望": (-10, -3), "宠爱": (-6, -1)}},
    {"desc": "{npc1}向{npc2}赠送名贵药材，以示友好。", "effects": {"心计": (2, 5), "威望": (2, 4), "宠爱": (1, 3)}},
    {"desc": "{npc1}在{npc2}失意时送去炭火和食物，赢得信任。", "effects": {"心计": (3, 6), "威望": (4, 8), "宠爱": (2, 4)}},
    {"desc": "{npc1}与{npc2}结为金兰姐妹，共同进退。", "effects": {"心计": (2, 4), "威望": (3, 6), "魅力": (2, 4)}},
    {"desc": "{npc1}私下向{npc2}透露太后喜好，助其在太后面前表现。", "effects": {"心计": (4, 7), "威望": (3, 6)}},
    {"desc": "{npc1}在御花园赏花时被蜂蜇，皇帝亲自探望。", "effects": {"宠爱": (4, 9), "健康": (-2, 0), "威望": (2, 5)}},
    {"desc": "{npc1}不慎打翻香炉，烫伤了手，太医诊治。", "effects": {"健康": (-3, -1), "宠爱": (0, 3), "威望": (-1, 2)}},
    {"desc": "{npc1}在御膳房尝了一道新菜，赞不绝口，传为美谈。", "effects": {"威望": (2, 4), "宠爱": (1, 3)}},
    {"desc": "{npc1}在湖边喂鱼时不慎落水，被侍卫救起。", "effects": {"健康": (-4, -1), "宠爱": (1, 4), "威望": (-2, 2)}},
    {"desc": "{npc1}的寝殿夜间走水，幸好及时扑灭。", "effects": {"健康": (-3, -1), "威望": (2, 5), "宠爱": (2, 4)}},
    {"desc": "{npc1}在佛堂抄经七日，为太后祈福。", "effects": {"威望": (5, 10), "福运": (3, 6)}},
    {"desc": "{npc1}因思念故乡，在宫中栽种家乡的花木。", "effects": {"威望": (2, 4), "才艺": (2, 4)}},
    {"desc": "{npc1}与{npc2}在宫道相遇，因言语不和发生争执。", "effects": {"威望": (-3, 3), "心计": (2, 5), "宠爱": (-2, 2)}},
    {"desc": "{npc1}当众指责{npc2}不敬太后，两人反目。", "effects": {"威望": (-5, 2), "心计": (4, 8), "宠爱": (-3, 2)}},
    {"desc": "{npc1}因{npc2}抢了其风头，在宴会上出言讥讽。", "effects": {"威望": (-4, 1), "心计": (3, 6), "宠爱": (-2, 3)}},
    {"desc": "{npc1}因生育皇子有功，皇帝亲赐封号。", "effects": {"威望": (10, 18), "宠爱": (8, 15)}},
    {"desc": "{npc1}在太后寿宴上献上自绣的百寿图，太后大喜。", "effects": {"威望": (8, 15), "才艺": (4, 8), "宠爱": (5, 10)}},
    {"desc": "{npc1}在秋猎中为皇帝献上一首凯歌，皇帝大悦。", "effects": {"宠爱": (6, 12), "才情": (4, 8), "威望": (5, 10)}},
    {"desc": "{npc1}与{npc2}在梅园偶遇，一同赏雪品茶。", "effects": {"心计": (1, 3), "威望": (2, 4)}},
    {"desc": "{npc1}在御花园发现一株奇花，进献给皇帝。", "effects": {"宠爱": (3, 7), "威望": (2, 4)}},
    {"desc": "{npc1}的鹦鹉学会了说“万岁”，成为宫中笑谈。", "effects": {"宠爱": (2, 5), "威望": (1, 3)}},
    {"desc": "{npc1}因着衣不当被太后训斥，勒令闭门思过。", "effects": {"威望": (-6, -2), "宠爱": (-3, 0)}},
    {"desc": "{npc1}在宫中推广女红，教宫女们刺绣新花样。", "effects": {"威望": (3, 6), "才艺": (3, 6)}},
    {"desc": "{npc1}与{npc2}相约一起放风筝，引得众人围观。", "effects": {"威望": (2, 4), "魅力": (2, 4)}},
    {"desc": "{npc1}自创了一道糕点，献给皇后品尝，皇后称赞。", "effects": {"威望": (3, 6), "宠爱": (2, 5)}},
    {"desc": "{npc1}在佛前许愿，希望皇帝早日得子。", "effects": {"威望": (3, 5), "福运": (2, 4)}},
    {"desc": "{npc1}的宫女偷盗被抓，连累主子失宠。", "effects": {"威望": (-5, -1), "宠爱": (-3, 0), "心计": (1, 3)}},
    {"desc": "{npc1}仗着宠爱，竟敢顶撞皇后，被罚跪一炷香。", "effects": {"威望": (-8, -3), "宠爱": (-5, 0), "心计": (2, 5)}},
    {"desc": "{npc1}为皇帝缝制一件冬衣，针脚细密，皇帝御寒专用。", "effects": {"宠爱": (4, 8), "才艺": (3, 6)}},
    {"desc": "{npc1}与{npc2}在棋局上较量，胜负难分。", "effects": {"才情": (3, 6), "威望": (1, 3)}},
    {"desc": "{npc1}深夜独自在月下吹箫，萧声哀婉，皇帝闻之动容。", "effects": {"宠爱": (5, 10), "才艺": (4, 8)}},
    {"desc": "{npc1}因家书被截获，怀疑是{npc2}所为，两人结下梁子。", "effects": {"心计": (4, 7), "威望": (-3, 2)}},

    # ---- 第二批（15条） ----
    {"desc": "{npc1}在御膳房学做点心，不慎被烫伤，皇帝闻讯赶来探望。", "effects": {"宠爱": (4, 9), "健康": (-3, -1), "威望": (2, 5)}},
    {"desc": "{npc1}在佛前跪求雨露，恰逢天降甘霖，众人称其贤德。", "effects": {"威望": (6, 12), "福运": (4, 8)}},
    {"desc": "{npc1}与{npc2}一同献上绣品，{npc1}的绣品被太后称赞更胜一筹。", "effects": {"宠爱": (3, 7), "威望": (4, 8), "才艺": (3, 6)}},
    {"desc": "{npc1}深夜在御花园徘徊，被巡逻侍卫误认为刺客，闹出笑话。", "effects": {"威望": (-4, -1), "宠爱": (-2, 2)}},
    {"desc": "{npc1}在宫宴上弹奏一曲《高山流水》，皇帝赞其琴艺高超。", "effects": {"宠爱": (6, 12), "才艺": (5, 10), "威望": (4, 8)}},
    {"desc": "{npc1}发现{npc2}私自与宫外通信，以此要挟{npc2}。", "effects": {"心计": (7, 14), "威望": (-3, 3), "宠爱": (-2, 3)}},
    {"desc": "{npc1}因思念过世的母亲，在宫中设坛祭拜，皇后闻之动容。", "effects": {"威望": (4, 8), "福运": (2, 5)}},
    {"desc": "{npc1}在御花园中为一只受伤的小鸟包扎，被路过的皇帝看见。", "effects": {"宠爱": (3, 7), "威望": (2, 5)}},
    {"desc": "{npc1}与{npc2}因争抢一张宣纸发生口角，笔墨泼洒一地。", "effects": {"心计": (2, 5), "威望": (-3, 2), "宠爱": (-2, 2)}},
    {"desc": "{npc1}在宫中推广种花，御花园的花木焕然一新。", "effects": {"威望": (3, 6), "才艺": (3, 6)}},
    {"desc": "{npc1}在皇帝面前吟诵一首新诗，被皇帝收录进诗集。", "effects": {"宠爱": (5, 10), "才情": (6, 12), "威望": (4, 8)}},
    {"desc": "{npc1}捡到{npc2}遗失的玉佩，却没有归还，反而藏匿起来。", "effects": {"心计": (4, 8), "威望": (-2, 3)}},
    {"desc": "{npc1}在宫中收留了一只流浪猫，惹来闲话。", "effects": {"威望": (1, 3), "宠爱": (1, 3)}},
    {"desc": "{npc1}与{npc2}在棋局上对弈三日，不分胜负，成宫中佳话。", "effects": {"才情": (4, 8), "威望": (3, 6)}},
    {"desc": "{npc1}因误食过敏之物，全身起疹，太医连夜诊治。", "effects": {"健康": (-5, -2), "宠爱": (1, 4)}},

    # ---- 第三批（20条） ----
    {"desc": "{npc1}在御花园中喂食锦鲤时，发现水中有一枚金戒指，疑是{npc2}所失。", "effects": {"心计": (3, 6), "威望": (2, 4)}},
    {"desc": "{npc1}在深夜听到冷宫中传来哭声，次日告知皇后，皇后命人查探。", "effects": {"威望": (4, 8), "心计": (3, 6)}},
    {"desc": "{npc1}因连日下雨，旧疾复发，皇帝命太医好生诊治。", "effects": {"健康": (-3, 0), "宠爱": (3, 7)}},
    {"desc": "{npc1}在宫中发现一只受伤的白狐，将其救起，众人称奇。", "effects": {"威望": (3, 6), "福运": (4, 8)}},
    {"desc": "{npc1}在御膳房偷学御厨手艺，被御厨发现，反而被夸赞勤奋。", "effects": {"才艺": (4, 8), "威望": (2, 5)}},
    {"desc": "{npc1}因误信谗言，错怪了{npc2}，事后懊悔不已。", "effects": {"心计": (-2, 2), "威望": (-3, 1)}},
    {"desc": "{npc1}在宫中设宴款待各宫妃嫔，席间歌舞升平。", "effects": {"威望": (4, 8), "宠爱": (3, 6)}},
    {"desc": "{npc1}与{npc2}在湖畔偶遇，一同泛舟，共赏月色。", "effects": {"心计": (1, 3), "威望": (2, 4)}},
    {"desc": "{npc1}因宫中事务烦心，独自在亭中借酒消愁，被皇帝撞见。", "effects": {"宠爱": (2, 5), "健康": (-2, 0)}},
    {"desc": "{npc1}在佛前许愿，愿皇帝早日得子，次日便传来喜讯。", "effects": {"威望": (5, 10), "福运": (4, 8)}},
    {"desc": "{npc1}在宫中栽种了一株昙花，花开之夜，请来各宫妃嫔共赏。", "effects": {"威望": (3, 6), "才艺": (3, 6)}},
    {"desc": "{npc1}在御前献上一盏亲手制作的荷花灯，皇帝赞其心灵手巧。", "effects": {"宠爱": (4, 9), "才艺": (3, 7)}},
    {"desc": "{npc1}因宫女办事不力，亲自洒扫寝殿，被太后夸赞勤俭。", "effects": {"威望": (3, 6), "宠爱": (2, 4)}},
    {"desc": "{npc1}在御花园中与{npc2}比拼插花技艺，两人不分伯仲。", "effects": {"才艺": (4, 8), "威望": (2, 4)}},
    {"desc": "{npc1}在宫中听闻民间有灾，主动捐出首饰赈灾。", "effects": {"威望": (6, 12), "福运": (3, 6)}},
    {"desc": "{npc1}因思念故人，在宫中种下一片竹林，引来无数鸟雀。", "effects": {"威望": (2, 4), "才艺": (2, 4)}},
    {"desc": "{npc1}在御书房外捡到一枚玉佩，归还于{npc2}，{npc2}感激不尽。", "effects": {"心计": (2, 4), "威望": (3, 6)}},
    {"desc": "{npc1}因宫中流言四起，心中烦闷，独自在佛堂抄经静心。", "effects": {"心计": (2, 5), "福运": (3, 6)}},
    {"desc": "{npc1}在御花园中遇见皇帝，献上一束亲手采摘的野花，皇帝欣然接受。", "effects": {"宠爱": (3, 7), "威望": (2, 4)}},
    {"desc": "{npc1}与{npc2}因一只鹦鹉的归属产生争执，闹到皇后跟前。", "effects": {"心计": (3, 6), "威望": (-3, 2)}},
]

def generate_local_events(game_state, max_count=2):
    """生成最多 max_count 条本地事件，并尽量使用不同妃子名，避免重复"""
    if not game_state.npcs:
        return []
    npc_names = [name for name in game_state.npcs.keys() if name not in ["太后", "皇后"]]
    if not npc_names:
        return []
    num_events = min(max_count, len(LOCAL_EVENT_TEMPLATES), len(npc_names))
    selected_templates = random.sample(LOCAL_EVENT_TEMPLATES, min(num_events, len(LOCAL_EVENT_TEMPLATES)))
    events = []
    used_names = set()
    for template in selected_templates:
        desc_template = template["desc"]
        needs_two = "{npc2}" in desc_template
        available = [n for n in npc_names if n not in used_names]
        if not available:
            break
        if needs_two:
            pool = available if len(available) >= 2 else npc_names
            if len(pool) < 2:
                continue
            npc1, npc2 = random.sample(pool, 2)
            desc = desc_template.replace("{npc1}", npc1).replace("{npc2}", npc2)
        else:
            npc1 = random.choice(available)
            npc2 = None
            desc = desc_template.replace("{npc1}", npc1)
        effects = {}
        for attr, (min_val, max_val) in template["effects"].items():
            effects[attr] = random.randint(min_val, max_val)
        events.append({"desc": desc, "effects": effects})
        used_names.add(npc1)
        if npc2:
            used_names.add(npc2)
    return events

# ============================================================
#  自由行动降级故事模板（AI 失败时使用，共 60 条）
# ============================================================
FALLBACK_STORY_TEMPLATES = [
    # ---- 第一批（40条） ----
    "你漫步在御花园中，花香袭人，宫人们正忙着修剪花枝。你远远看见{npc1}在亭中独自品茶，若有所思。",
    "你正于廊下读书，忽然听见一阵急促的脚步声，原来是{npc1}身边的宫女前来传话，说太后召你过去。",
    "午膳过后，你闲来无事，便去探望生病的{npc2}。只见她面色苍白，正倚在榻上喝药。",
    "你在宫中散步时，听见几名宫女窃窃私语，说皇帝昨夜留宿在{npc1}宫中，惹得众人议论纷纷。",
    "今日是赏花节，各宫妃嫔都在御花园中赏玩牡丹。你偶遇{npc1}，两人寒暄几句，各自散去。",
    "你在佛堂抄经时，{npc2}突然进来，说是要求一签，你们便一同跪拜祈福。",
    "傍晚时分，你在回宫路上遇到{npc1}，她面色不悦，似乎与{npc2}刚发生过口角。",
    "你正在练习刺绣，忽然收到{npc1}派人送来的点心，说是新制的桂花糕。",
    "皇帝今日心情大好，在御书房召见了几位妃嫔，你也在其中。皇帝问起你近日所读之书，你从容应对。",
    "你在御膳房偶遇{npc1}，她正在亲自为皇帝炖汤，你便上前请教炖汤的诀窍。",
    "昨夜雷雨交加，你被雷声惊醒，早起时发现{npc2}派人送来安神茶，说是特地为你去准备的。",
    "你在园中采花时，{npc1}上前与你攀谈，说起近日宫中传言某位嫔妃失宠之事。",
    "你因身体不适未去请安，太后差人送来药材，并叮嘱你好好休养。",
    "你在宫中散步时，看见{npc1}和{npc2}在池边喂鱼，两人有说有笑，你便绕道而行。",
    "今日是初一，你前往慈宁宫向太后请安，太后留你用午膳，席间问起你家乡风物。",
    "你正于琴房练琴，{npc1}推门而入，说是想听你弹一曲《凤求凰》。",
    "你收到家书一封，得知父亲在朝中升迁，心中欢喜，便去佛前还愿。",
    "你在御花园中遇见{npc1}，她正对着一株枯萎的牡丹叹息，你便上前安慰。",
    "皇帝命各宫妃嫔各献一幅字画，你连日苦练，终于完成一幅《兰亭序》。",
    "你在宫中遇到{npc2}的宫女，她神色慌张，似乎有什么秘密。",
    "午后小憩时，你梦见自己回到了故乡，醒来后怅然若失。",
    "你在御膳房尝了一道新菜，觉得味道甚佳，便向御厨请教做法。",
    "你在宫中遇见{npc1}，她正与几名宫女踢毽子，见你来便邀你一同玩耍。",
    "你闲来无事，便去书阁翻阅古籍，发现了一本前朝妃嫔的诗词集。",
    "你在御花园中偶遇皇帝，皇帝问你为何独自在此，你回答正在赏荷。",
    "你在宫中听闻{npc1}近日得了赏赐，是一对上好的翡翠镯子。",
    "你与{npc2}相约去放风筝，不料风筝断线，落入御花园深处。",
    "你在宫中散步时，看见{npc1}正在训斥一名宫女，你便上前解围。",
    "今日是端午，宫中举办赛龙舟活动，你与{npc1}一同观看。",
    "你在宫中遇见{npc2}，她手里拿着一封书信，神色紧张，见你来便匆匆藏起。",
    "你在佛前为家人祈福，忽然听到身后有脚步声，回头一看竟是{npc1}。",
    "你在宫中遇到一位乐师，正在弹奏一首新曲，你驻足聆听良久。",
    "你在御膳房学着做了一道菜，送给{npc1}品尝，她赞不绝口。",
    "你在宫中散步时，发现一只受伤的蝴蝶，小心捧起送回草丛。",
    "你在宫中遇到{npc2}，她面带愁容，你问起缘由，她只说无事。",
    "你在宫中闲逛时，看见{npc1}正与一名画师交谈，似乎在商议画作之事。",
    "你在御花园中发现一本不知何人遗落的诗集，翻了几页，竟是一首新诗。",
    "你在宫中听闻{npc1}最近迷上了园艺，在寝殿外种了一片蔷薇。",
    "你在书阁中翻阅医术，为近来头疼之症寻找药方，正好遇到{npc2}也在查书。",
    "你在宫中遇到一位来自江南的绣娘，她正为皇后绣制一顶凤冠。",

    # ---- 第二批（20条） ----
    "你在宫中散步时，一阵风吹落树上的花瓣，恰巧落在你肩头。你抬头一看，{npc1}正站在不远处，对你微微一笑。",
    "你在御膳房中发现{npc1}正偷偷做糕点，说是要献给太后品尝。你便上前帮忙，两人忙了整整一个下午。",
    "你在书阁中翻阅古籍时，偶然发现{npc1}也在此处，她正捧着一本诗词集读得入神。",
    "今日天气晴好，你在御花园中散步，看见{npc1}正在教几个小宫女放风筝，欢声笑语不断。",
    "你在回宫路上遇到{npc1}，她正急匆匆赶往慈宁宫，说是有急事要禀报太后。",
    "你在寝殿中休息时，听见窗外传来一阵悠扬的笛声，循声望去，竟是{npc1}在月下吹笛。",
    "你在宫中遇到一位老嬷嬷，她拉着你的手说起许多旧事，其中提到了{npc1}的母亲。",
    "你在御膳房学做莲子羹时，{npc1}也来学习，两人一同研究火候，相谈甚欢。",
    "你在佛堂上香时，碰见{npc1}正在跪拜祈福，你便在她身旁默默许愿。",
    "你在园中采摘桂花时，{npc1}路过，称赞你采的桂花香气馥郁。",
    "你在宫中听闻{npc1}近日身体不适，便亲自熬了一碗汤药送去探望。",
    "你在御书房外等候召见时，{npc1}也来求见皇帝，两人相视一笑。",
    "你在宫中散步时，看见{npc1}正在教一只鹦鹉说话，那鹦鹉竟真的学会了叫“娘娘”。",
    "你在御膳房与{npc1}不期而遇，她正在为皇帝炖制一道滋补汤品。",
    "你在宫中听说{npc1}得到了一匹上好的蜀锦，便前去观赏，那花纹确实精美绝伦。",
    "你在御花园中遇见{npc1}，她正对着一株凋谢的花流泪，你便上前安慰。",
    "你在宫中夜间巡走时，看见{npc1}的寝殿还亮着灯，似乎还未入睡。",
    "你在晨起梳妆时，宫女来报说{npc1}派人送来一盒新制的胭脂。",
    "你在宫中遇到一个迷路的小太监，你领他到总管处时，发现{npc1}也在找这个小太监。",
    "你在书阁中抄录经文时，{npc1}借故前来，说是要借一本佛经，你便借给了她。",
]

# ============================================================
#  宫斗事件降级故事模板（AI 失败时使用，共 40 条）
# ============================================================
CONFLICT_FALLBACK_TEMPLATES = [
    # ---- 第一批（25条） ----
    "{initiator}与{target}在御花园相遇，因一言不合当众争执，惹来众人侧目。",
    "{initiator}暗中买通{target}身边的宫女，在其茶中下了泻药。",
    "{initiator}在皇帝面前状告{target}不敬太后，皇帝将{target}训斥一番。",
    "宫中传言{target}与侍卫有染，{initiator}趁机推波助澜。",
    "{initiator}在{target}的寝殿放置了一双绣花鞋，意图诬陷其私通。",
    "{initiator}故意在太后寿宴上迟到，却将过错推给{target}。",
    "{initiator}借机在皇帝面前献舞，抢了{target}的风头。",
    "{initiator}指使宫女散布{target}对皇帝不满的流言。",
    "{initiator}在{target}的膳食中下毒，幸被及时发现。",
    "{initiator}与{target}在宫道上狭路相逢，互不相让，闹到皇后跟前。",
    "{initiator}买通太医，让{target}的安胎药变成了凉药。",
    "{initiator}在太后面前告发{target}私下结交外臣。",
    "{initiator}故意摔碎{target}心爱的玉簪，两人反目成仇。",
    "{initiator}在宫宴上讽刺{target}出身低微，两人针锋相对。",
    "{initiator}在御前失仪，却诬陷是{target}故意设计。",
    "{initiator}利用{target}的丫鬟传递假消息，使其误入冷宫。",
    "{initiator}在{target}的服饰上做了手脚，使其在御前出丑。",
    "{initiator}买通宫人，在{target}的寝殿放置诅咒木偶。",
    "{initiator}在皇帝面前献上{target}私下写的诗词，皇帝怀疑其结党。",
    "{initiator}在{target}的茶点中加入致幻之物，使其言行失常。",
    "{initiator}与{target}同时争抢一首诗的作词权，闹得不可开交。",
    "{initiator}在太后面前揭发{target}曾对先帝不敬。",
    "{initiator}在御花园中推了{target}一把，使其落入水中。",
    "{initiator}将{target}写给家中的密信截获，并加以利用。",
    "{initiator}在宫宴上故意泼洒酒水在{target}的衣裙上。",

    # ---- 第二批（15条） ----
    "{initiator}在{target}的寝殿外偷听，听见{target}正与人密谋要对付自己。",
    "{initiator}在御前假意摔倒，却诬陷是{target}故意伸脚绊倒自己。",
    "{initiator}在{target}的茶点中掺入辣椒粉，使其在御前失态。",
    "{initiator}在太后面前进谗言，说{target}私下议论太后年迈。",
    "{initiator}在御花园中大声斥责{target}的宫女，实则是在给{target}难堪。",
    "{initiator}在{target}的必经之路上泼了水，使其滑倒摔伤。",
    "{initiator}在宫宴上故意与{target}同桌，席间言语相激。",
    "{initiator}在{target}的妆奁中放入一件禁忌之物，意图陷害。",
    "{initiator}在皇帝面前献上一首诗，暗讽{target}近日失宠。",
    "{initiator}在{target}的寝殿附近放了一只野猫，吓得{target}彻夜难眠。",
    "{initiator}在太后寿宴上迟到，却当众指责是{target}故意拖延。",
    "{initiator}在{target}的服饰上做手脚，使其在御前露出破绽。",
    "{initiator}在宫中散布{target}即将被废的谣言，动摇其人心。",
    "{initiator}在{target}的汤药中加入了安神之物，使其在重要场合昏昏欲睡。",
    "{initiator}在{target}面前故意与皇帝的近侍交谈甚欢，引人猜疑。",
]

# ============================================================
#  降级故事生成（供自由行动 AI 失败时使用）
# ============================================================
def generate_fallback_story(game_state):
    """从降级故事模板中随机生成一条，并用本局妃子名替换占位符。"""
    npc_names = []
    if getattr(game_state, "npcs", None):
        npc_names = [name for name in game_state.npcs.keys() if name not in ["太后", "皇后"]] or list(game_state.npcs.keys())
    template = random.choice(FALLBACK_STORY_TEMPLATES)
    desc = template
    npc_pool = list(npc_names)
    npc1 = random.choice(npc_pool) if npc_pool else None
    if "{npc1}" in desc and npc1 is not None:
        desc = desc.replace("{npc1}", npc1)
    if "{npc2}" in desc:
        others = [n for n in npc_pool if n != npc1] if npc_pool else []
        npc2 = random.choice(others) if others else npc1
        if npc2 is not None:
            desc = desc.replace("{npc2}", npc2)
    return desc

# ============================================================
#  宫斗事件降级故事生成（AI 失败时使用）
# ============================================================
def generate_conflict_fallback_narration(initiator, target):
    """从宫斗降级模板中随机生成一条，替换发起者与目标占位符。"""
    template = random.choice(CONFLICT_FALLBACK_TEMPLATES)
    return template.replace("{initiator}", initiator).replace("{target}", target)

# ============================================================
#  特殊事件（仅用于实时行动，转旬不用）
# ============================================================
SPECIAL_EVENTS = [
    {"name": "御花园偶遇", "trigger": {"宠爱": 40}, "description": "你在御花园赏花时，偶遇皇帝微服游园。", "effects": {"宠爱": 10, "威望": 5}, "choices": ["上前请安", "假装没看见", "故意展示才艺"], "story_hint": "皇帝正在游园"},
    {"name": "太后召见", "trigger": {"威望": 30}, "description": "太后突然召你前往慈宁宫，不知所谓何事。", "effects": {"威望": 10, "心计": 5}, "choices": ["恭敬前往", "称病不去", "找人打听"], "story_hint": "太后有要事相商"},
    {"name": "皇帝赏赐", "trigger": {"宠爱": 60}, "description": "皇帝今日心情大好，赏赐了众多珍宝给后宫。", "effects": {"宠爱": 5, "威望": 10}, "choices": ["欣然接受", "推辞谦让", "请求赏赐他人"], "story_hint": "龙颜大悦"},
]

def check_event(game_state):
    # 降低实时行动的随机事件触发概率，避免频繁弹出
    if random.random() > 0.1:  # 原来0.3，改为0.1
        return None
    attrs = game_state.attributes
    available = []
    for event in SPECIAL_EVENTS:
        trigger = event.get("trigger", {})
        meets = True
        for attr, threshold in trigger.items():
            if attrs.get(attr, 0) < threshold:
                meets = False
                break
        if meets:
            available.append(event)
    if available:
        available.sort(key=lambda e: sum(e.get("trigger", {}).values()), reverse=True)
        return random.choice(available[:3])
    return None

def get_daily_actions():
    return {
        "晨起请安": {"宠爱": 2, "威望": 3, "健康": -1, "desc": "向皇后和太后请安"},
        "练习才艺": {"才情": 5, "健康": -2, "desc": "练习琴棋书画"},
        "结交妃嫔": {"心计": 3, "威望": 2, "desc": "与其他妃嫔走动"},
        "侍奉皇帝": {"宠爱": 8, "健康": -3, "desc": "去御书房侍奉皇帝"},
        "宫中散步": {"健康": 3, "容貌": 1, "desc": "在宫中散步赏景"},
        "打听消息": {"心计": 5, "威望": 1, "desc": "打探宫中消息"},
    }

def apply_daily_action(game_state, action_key):
    actions = get_daily_actions()
    if action_key not in actions:
        return None
    action = actions[action_key]
    effects = {}
    for attr, change in action.items():
        if attr != "desc" and attr in game_state.attributes:
            old_value = game_state.attributes[attr]
            game_state.attributes[attr] = max(0, min(100, old_value + change))
            effects[attr] = change
    game_state.add_memory(f"进行了每日行动：{action['desc']}")
    return effects


# ============================================================
#  太子系统事件生成器
# ============================================================
#  素材池全部来自 heir_content.py；这里只负责「随机取一条 + 补齐运行期字段」。
#  返回的事件字典都带 kind 字段，供 app.py 分派处理。

def _copy_event(template):
    """浅拷贝模板并深拷贝 choices/options，避免运行期修改污染素材池。"""
    import copy
    return copy.deepcopy(template)


def generate_regency_event(exclude_ids=None):
    """随机返回一条监国政务事件。

    exclude_ids: 近期已出现过的事件 id 集合，尽量不重复。
    返回 {kind, id, category, description, flavor, choices:{A:{text,effect,bias,merit}, B:{...}}}
    """
    exclude = set(exclude_ids or [])
    pool = [e for e in REGENCY_EVENT_POOL if e["id"] not in exclude] or REGENCY_EVENT_POOL
    tpl = _copy_event(random.choice(pool))
    tpl["kind"] = "regency"
    return tpl


def find_regency_event(event_id):
    """按 id 取政务事件模板（进言 API 校验用）。"""
    for e in REGENCY_EVENT_POOL:
        if e["id"] == event_id:
            return _copy_event(e)
    return None


def generate_heir_rebellion_event(heir_age, chance=0.20):
    """太子 ≥14 岁时，每旬 chance 概率触发一条叛逆期事件。不触发返回 None。"""
    try:
        age = float(heir_age or 0)
    except (TypeError, ValueError):
        age = 0
    if age < 14:
        return None
    if random.random() >= chance:
        return None
    idx = random.randrange(len(HEIR_REBELLION_POOL))
    tpl = _copy_event(HEIR_REBELLION_POOL[idx])
    tpl["kind"] = "rebellion"
    tpl["id"] = f"reb_{idx}"
    return tpl


def generate_heir_special_event(chance=0.25):
    """太子特殊危机事件（调用方负责 3-5 旬的间隔控制）。"""
    if random.random() >= chance:
        return None
    idx = random.randrange(len(HEIR_SPECIAL_POOL))
    tpl = _copy_event(HEIR_SPECIAL_POOL[idx])
    tpl["kind"] = "special"
    tpl["id"] = f"sp_{idx}"
    return tpl


def generate_incognito_adventure():
    """微服私访奇遇：必定返回一条（由 API 侧校验银两与行动点）。"""
    idx = random.randrange(len(INCOGNITO_POOL))
    tpl = _copy_event(INCOGNITO_POOL[idx])
    tpl["kind"] = "incognito"
    tpl["id"] = f"inc_{idx}"
    return tpl


def generate_consort_selection_event():
    """太子选妃事件：一次性给出三位候选（文官党 / 武官党 / 宗室党）。"""
    candidates = [_copy_event(c) for c in CONSORT_CANDIDATES]
    random.shuffle(candidates)
    return {
        "kind": "consort_selection",
        "id": "consort_selection",
        "name": "东宫选妃",
        "description": "礼部呈上三家名册：文官清流、边镇将门、宗室嫡脉。太子妃之位只有一个，选谁，便等于选了东宫将来倚靠哪一方。",
        "flavor": "三位姑娘同日入宫觐见，衣裳、举止、连行礼的深浅都是各家掰算了半月的结果。太子坐在帘后，一个也没有先开口问。",
        "candidates": candidates,
    }


def find_consort_candidate(name):
    """按姓名取太子妃候选人模板。"""
    for c in CONSORT_CANDIDATES:
        if c["name"] == name:
            return _copy_event(c)
    return None


def generate_consort_conflict_event(available_ranks=None):
    """侧室宫斗对话事件。

    available_ranks: 当前内宅实际存在的位份集合；若提供，则只取双方位份都在场的事件。
    """
    pool = CONSORT_CONFLICT_POOL
    if available_ranks:
        ranks = set(available_ranks)
        filtered = [e for e in pool if set(e.get("roles", [])) <= ranks]
        if filtered:
            pool = filtered
    idx = CONSORT_CONFLICT_POOL.index(random.choice(pool))
    tpl = _copy_event(CONSORT_CONFLICT_POOL[idx])
    tpl["kind"] = "consort_conflict"
    tpl["id"] = f"cc_{idx}"
    return tpl


def generate_consort_fun_event():
    """内宅趣味事件。"""
    idx = random.randrange(len(CONSORT_FUN_POOL))
    tpl = _copy_event(CONSORT_FUN_POOL[idx])
    tpl["kind"] = "consort_fun"
    tpl["id"] = f"cf_{idx}"
    return tpl
