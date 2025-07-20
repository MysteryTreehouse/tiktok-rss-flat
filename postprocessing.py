#!/usr/bin/env python3
import os
import asyncio
import csv
import requests
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator
from TikTokApi import TikTokApi
import config
from playwright.async_api import async_playwright
from pathlib import Path
from urllib.parse import urlparse

# GitHub raw base URL for assets and hosted videos
ghRawURL = config.ghRawURL

# your TikTok ms token must be set in env
ms_token = os.environ.get("MS_TOKEN")
if not ms_token:
    raise RuntimeError("MS_TOKEN environment variable is required")

# whether to fetch only the very last video (if set to "1")
force_last = os.environ.get("FORCE_LAST_REFRESH") == "1"

async def runscreenshot(playwright, url, screenshotpath):
    browser = await playwright.chromium.launch()
    page = await browser.new_page()
    await page.goto(url)
    await page.screenshot(path=screenshotpath, quality=20, type='jpeg')
    await browser.close()

def find_any_url(obj):
    """Recursively find the first HTTP(s) URL in a nested dict/list."""
    if isinstance(obj, str) and obj.startswith("http"):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            u = find_any_url(v)
            if u:
                return u
    if isinstance(obj, list):
        for v in obj:
            u = find_any_url(v)
            if u:
                return u
    return None

async def user_videos():
    with open('subscriptions.csv') as f:
        reader = csv.DictReader(f, fieldnames=['username'])
        for row in reader:
            user = row['username'].strip()
            print(f"Running for user '{user}'")

            # set up new RSS feed for this user
            fg = FeedGenerator()
            fg.id(f'https://www.tiktok.com/@{user}')
            fg.title(f'{user} TikTok')
            fg.author({'name': 'Conor ONeill', 'email': 'conor@conoroneill.com'})
            fg.link(href='http://tiktok.com', rel='alternate')
            fg.logo(ghRawURL + 'tiktok-rss.png')
            fg.subtitle(f'All the latest TikToks from {user}')
            fg.link(href=ghRawURL + f'rss/{user}.xml', rel='self')
            fg.language('en')

            updated = None

            # **no args** here; we pass ms_token into create_sessions() below
            async with TikTokApi() as api:
                # create exactly one session, supplying your ms_token
                await api.create_sessions(
                    ms_tokens=[ms_token],
                    num_sessions=1,
                    sleep_after=3,
                    headless=False
                )

                ttuser = api.user(user)
                try:
                    # confirm user exists
                    await ttuser.info()
                    count = 1 if force_last else 10

                    async for video in ttuser.videos(count=count):
                        # safe metadata
                        try:
                            video_data = video.dict()
                        except AttributeError:
                            video_data = getattr(video, "__dict__", {}) or {}

                        fe = fg.add_entry()
                        vid_id = video_data.get('id') or getattr(video, 'id', None)
                        link = f'https://www.tiktok.com/@{user}/video/{vid_id}'
                        fe.id(link)

                        # **timestamps** — handle both int epochs and datetime objects
                        ts_val = video_data.get('createTime') or video_data.get('create_time')
                        if ts_val:
                            if isinstance(ts_val, datetime):
                                ts = ts_val
                            else:
                                ts = datetime.fromtimestamp(int(ts_val), timezone.utc)
                            fe.published(ts)
                            fe.updated(ts)
                            updated = max(updated, ts) if updated else ts

                        # title + link
                        title = video_data.get('desc') or 'TikTok video'
                        fe.title(title[:255])
                        fe.link(href=link)

                        # try downloading via API
                        video_bytes = None
                        try:
                            video_bytes = await api.video(id=vid_id).bytes()
                        except Exception:
                            # fallback to any available URL
                            candidate = (
                                video_data.get('downloadAddr')
                                or video_data.get('download_addr')
                                or video_data.get('video', {}).get('downloadAddr')
                                or video_data.get('video', {}).get('download_addr')
                                or video_data.get('video', {}).get('playAddr')
                                or video_data.get('video', {}).get('play_addr')
                            )
                            if not candidate:
                                candidate = find_any_url(video_data)

                            if candidate:
                                try:
                                    resp = requests.get(candidate, timeout=20)
                                    resp.raise_for_status()
                                    video_bytes = resp.content
                                except Exception as e:
                                    print(f"[WARN] HTTP download failed for {vid_id}: {e}")
                            else:
                                print(f"[WARN] No video URL found for {vid_id}")

                        # save video + enclosure
                        if video_bytes:
                            out_dir = Path("videos") / user
                            out_dir.mkdir(parents=True, exist_ok=True)
                            path = out_dir / f"{vid_id}.mp4"
                            with open(path, "wb") as wf:
                                wf.write(video_bytes)
                            public = ghRawURL + f"videos/{user}/{vid_id}.mp4"
                            fe.enclosure(public, str(len(video_bytes)), "video/mp4")
                        else:
                            fe.enclosure(link, "0", "video/mp4")

                        # thumbnail + content
                        desc = title
                        cover = video_data.get('video', {}).get('cover')
                        if cover:
                            thumb_name = Path(urlparse(cover).path).name
                            thumb_rel = f"thumbnails/{user}/screenshot_{thumb_name}.jpg"
                            thumb_abs = Path(thumb_rel)
                            if not thumb_abs.exists():
                                async with async_playwright() as pw:
                                    await runscreenshot(pw, cover, str(thumb_abs))
                            thumb_url = ghRawURL + thumb_rel
                            fe.content(f'<img src="{thumb_url}" /> {desc}')
                        else:
                            fe.content(desc)

                    # finalize feed
                    if updated:
                        fg.updated(updated)
                    fg.rss_file(f'rss/{user}.xml', pretty=True)

                except Exception as e:
                    print(f"Error for user {user}: {e}")

if __name__ == '__main__':
    asyncio.run(user_videos())
