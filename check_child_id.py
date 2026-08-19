from models import GameState

save = {
    "game_state": {
        "npcs": {
            "妃A": {"name": "妃A", "children": [{"name": "child1", "gender": "皇子"}]}
        },
        "children": [{"name": "pc_child", "gender": "公主"}]
    }
}

gs = GameState.from_save_data(save)
print('npc child entries:', gs.npcs['妃A']['children'])
print('top-level children:', gs.children)
for child in gs.npcs['妃A']['children']:
    print('npc child_id:', child.get('child_id'))
for child in gs.children:
    print('top child_id:', child.get('child_id'))
