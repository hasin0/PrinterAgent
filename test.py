import requests, base64

FRESHSERVICE_DOMAIN = "dangote.freshservice.com"
API_KEY = "LcB3FhMh9r4UI1pc18WT"

token = base64.b64encode((API_KEY + ":X").encode()).decode()

r = requests.get(
    f"https://{FRESHSERVICE_DOMAIN}/api/v2/agents/me",
    headers={"Authorization": f"Basic {token}"}
)

print(r.json())