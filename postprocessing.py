#!/usr/bin/env python3
"""
Fetches the latest TikTok videos for a given user and generates an RSS feed.
"""
import os
import asyncio
from TikTokApi import TikTokApi
from feedgen.feed import FeedGenerator

# Environment configuration
MS_TOKEN = os.getenv("MS_TOKEN")
FORCE_REFRESH = os.getenv("FORCE_LAST_REFRESH") == "1"
TIKTOK_USER = os.getenv("TIKTOK_USER", "treehousedetective")
TIKTOK_BROWSER = os.getenv("TIKTOK_BROWSER", "chromium")  # or 'firefox', 'webkit'
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "rss.xml")
MAX_VIDEOS = int(os.getenv("MAX_VIDEOS", "10"))

async def user_videos() -> list[dict]:
    """
    Uses the TikTokApi to fetch the latest videos of the configured user.
    """
    async with TikTokApi() as api:
        # Establish a browsing session with your TikTok ms_token
        await api.create_sessions(
            ms_tokens=[MS_TOKEN],      # pass your ms_token here
            num_sessions=1,
            browser=TIKTOK_BROWSER,
            use_test_endpoints=FORCE_REFRESH
        )
        # Fetch user videos (async iterator)
        videos = []
        async for video in api.user(username=TIKTOK_USER).videos(count=MAX_VIDEOS):
            # Convert video object to dict
            if hasattr(video, "dict"):  # pydantic-style
                vid_data = video.dict()
            elif hasattr(video, "as_dict"):  # legacy
                vid_data = video.as_dict
            else:
                vid_data = video.__dict__
            videos.append(vid_data)
        return videos


def build_rss(videos: list[dict]) -> None:
    """
    Builds and writes an RSS feed from a list of video dicts.
    """
    fg = FeedGenerator()
    fg.title(f"@{TIKTOK_USER} TikTok Feed")
    fg.link(href=f"https://www.tiktok.com/@{TIKTOK_USER}", rel="alternate")
    fg.description(f"Latest TikTok videos from @{TIKTOK_USER}")

    for vid in videos:
        fe = fg.add_entry()
        fe.id(vid.get("id"))
        title = vid.get("desc") or vid.get("id")
        fe.title(title[:60] + ("..." if len(title) > 60 else ""))
        # video URL may be nested under 'video' -> 'playAddr'
        url = vid.get("video", {}).get("playAddr") or vid.get("downloadAddr")
        if url:
            fe.link(href=url)
        # convert timestamp to RFC822 string if needed
        create_time = vid.get("createTime")
        if create_time:
            fe.pubDate(create_time)

    fg.rss_file(OUTPUT_FILE)
    print(f"Generated RSS feed with {len(videos)} videos -> {OUTPUT_FILE}")


if __name__ == "__main__":
    videos = asyncio.run(user_videos())
    build_rss(videos)
