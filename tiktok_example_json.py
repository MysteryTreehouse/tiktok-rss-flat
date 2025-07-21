from TikTokApi import TikTokApi
import json

# ← pass your proxy + browser settings here
api = TikTokApi.get_instance(
    browser="webkit",
    headless=False,
    proxy="http://user:pass@your.proxy.host:PORT"
)

count = 1
tiktoks = api.by_username("iamtabithabrown", count=count)

jsonString = json.dumps(tiktoks)
with open("tiktok_example_data.json", "w") as jsonFile:
    jsonFile.write(jsonString)

for tiktok in tiktoks:
    print(tiktok["video"]["cover"])
