import os
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
       if __name__ == "__main__":
    scan()
    timeout=30
)

print("STATUS:", response.status_code)
print("RESPONSE:", response.text)
