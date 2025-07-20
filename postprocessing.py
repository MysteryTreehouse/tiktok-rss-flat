#!/usr/bin/env python3
import os
import sys
import asyncio
from datetime import datetime
from TikTokApi import TikTokApi, Video, VideoApi, User, Music, Posts, VerifyFp
from TikTokApi.exceptions import TikTokException
from feedgen.feed import FeedGenerator

# --- your existing helpers (e.g. read config, manage cache) go here ---
# (I’ve elided any utility functions you had above; just make sure they stay in place.)

async def user_videos():
    user = os.environ.get("TT_USER", "treehousedetective")
    max_videos = int(os.environ.get("MAX_VIDEOS", "10"))

    # instantiate TikTokApi in WebKit, non-headless mode:
    async with TikTokApi(
        verify_fp=VerifyFp(os.environ.get("VERIFY_FP", "")),
        browser="webkit",
        headless=False,
    ) as api:

        try:
            # fetch latest posts
            posts: Posts = await api.user_posts(username=user, count=max_videos)
        except TikTokException as e:
            print(f"Error: TikTok blocked us for {user}: {e}")
            return

        # process each video and build RSS items...
        fg = FeedGenerator()
        fg.title(f"{user}'s TikTok feed")
        fg.link(href="https://tiktok.com/@" + user, rel="alternate")
        fg.description(f"Latest {max_videos} TikToks by {user}")
        fg.lastBuildDate(datetime.utcnow())

        for post in posts:
            video: Video = post.video
            entry = fg.add_entry()
            entry.id(video.id)
            entry.title(video.text or f"TikTok {video.id}")
            entry.link(href=video.download_addr)
            entry.pubDate(datetime.utcfromtimestamp(post.create_time))
            entry.enclosure(video.download_addr, 0, "video/mp4")

        # write out RSS
        rss_path = os.path.join(os.getcwd(), f"{user}.xml")
        fg.rss_file(rss_path)
        print(f"Wrote {rss_path}")

if __name__ == "__main__":
    # allow forcing a full refresh
    if os.environ.get("FORCE_LAST_REFRESH") == "1":
        # rm any timestamp cache you might have
        pass

    # run the scraper
    asyncio.run(user_videos())
