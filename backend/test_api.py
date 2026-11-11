import httpx

resp = httpx.post(
    "https://api.deepseek.com/chat/completions",
    headers={
        "Authorization": "Bearer sk-0a563e3571284bebaa458e8959742cba",
        "Content-Type": "application/json",
    },
    json={
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "用一句话介绍桔子分期"}],
        "temperature": 0.5,
        "max_tokens": 100,
    },
    timeout=30,
)
data = resp.json()
print(f"Status: {resp.status_code}")
print(f"Model: {data['model']}")
print(f"Reply: {data['choices'][0]['message']['content']}")
print(f"Tokens: {data.get('usage', {})}")
