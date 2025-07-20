import os
import asyncio
from TikTokApi import TikTokApi
from feedgen.feed import FeedGenerator

def find_any_url(video_data: dict) -> str:
    # existing logic to select the best available URL
    for key in ("playAddr", "downloadAddr", "shareCoverUrl", "coverUrl"):
        url = video_data.get(key)
        if url:
            return url
    return None

async def user_videos():
    token = os.environ.get("MS_TOKEN")
    force_refresh = bool(os.environ.get("FORCE_LAST_REFRESH"))
    async with TikTokApi(custom_verifyFp=token, use_test_endpoints=force_refresh) as api:
        # fetch user videos, possibly forcing re-import if enabled
        videos = await api.user_videos(user="treehousedetective")
        fg = FeedGenerator()
        fg.title("TikTok RSS")
        fg.link(href="https://www.tiktok.com/@treehousedetective", rel="alternate")
        fg.description("Latest uploads from treehousedetective")

        for video in videos:
            # Corrected call: use as_dict(), not as.dict()
            video_data = video.as_dict()
            url = find_any_url(video_data)
            if not url:
                print(f"[WARN] No video URL found for {video_data.get('id')}")
                continue
            entry = fg.add_entry()
            entry.id(str(video_data.get('id')))
            entry.title(video_data.get('desc', ''))
            entry.link(href=url)
            entry.pubDate(video_data.get('createTime'))

        rss = fg.rss_str(pretty=True)
        with open("feed.xml", "wb") as f:
            f.write(rss)

if __name__ == '__main__':
    asyncio.run(user_videos())
