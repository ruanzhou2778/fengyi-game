import requests
import json

BASE_URL = "http://localhost:5000/api"

def test():
    print("=" * 50)
    print("测试宫斗游戏后端")
    print("=" * 50)
    
    resp = requests.get(f"{BASE_URL}/scenarios")
    scenarios = resp.json()
    print("开局选项：")
    for s in scenarios['scenarios']:
        print(f"  - {s['name']}: {s['description']}")
    
    resp = requests.post(f"{BASE_URL}/start", json={
        "scenario": "才女入宫",
        "name": "林婉儿"
    })
    game = resp.json()
    print(f"\n位份: {game['rank']}")
    print(f"故事: {game['narration']}")
    print(f"选项: {game['choices']}")
    
    player_id = game['player_id']
    resp = requests.post(f"{BASE_URL}/act", json={
        "player_id": player_id,
        "choice": game['choices'][0] if game['choices'] else "四处走走",
        "current_time": "巳时"
    })
    result = resp.json()
    print(f"\n新故事: {result['narration']}")
    print(f"属性: {result['attributes']}")
    print("\n测试完成！✅")

if __name__ == "__main__":
    test()