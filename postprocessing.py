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

# GitHub raw base URL for assets
ghRawURL = config.ghRawURL

# TikTok msToken and force-refresh flag
ms_token = os.environ.get("MS_TOKEN")
force_last = os.environ.get("FORCE_LAST_REFRESH") == "1"

# Optional proxy support via environment
proxy_url = os.environ.get("TIKTOK_PROXY")
proxies_list = [proxy_url] if proxy_url else None

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

            # Set up the RSS feed
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

            async with TikTokApi() as api:
                try:
                    await api.create_sessions(
                        ms_tokens=[ms_token],
                        num_sessions=1,
                        sleep_after=3,
                        headless=False,       # non-headless mode
                        browser='webkit',     # use WebKit to evade bot detection
                        proxies=proxies_list  # optional proxy list
                    )

                    ttuser = api.user(user)
                    await ttuser.info()

                    count = 1 if force_last else 10
                    async for video in ttuser.videos(count=count):
                        try:
                            video_data = video.dict()
                        except:
                            video_data = {}

                        fe = fg.add_entry()
                        vid_id = video_data.get('id') or getattr(video, 'id', None)
                        link = f'https://www.tiktok.com/@{user}/video/{vid_id}'
                        fe.id(link)

                        ts_val = video_data.get('createTime') or video_data.get('create_time')
                        if ts_val:
                            ts = datetime.fromtimestamp(ts_val, timezone.utc)
                            fe.published(ts)
                            fe.updated(ts)
                            updated = max(updated, ts) if updated else ts

                        title = video_data.get('desc') or 'TikTok video'
                        fe.title(title[:255])
                        fe.link(href=link)

                        video_bytes = None
                        try:
                            video_bytes = await api.video(id=vid_id).bytes()
                        except Exception:
                            candidate = (
                                video_data.get('downloadAddr')
                                or video_data.get('download_addr')
                                or video_data.get('video', {}).get('downloadAddr')
                                or video_data.get('video', {}).get('download_addr')
                                or video_data.get('video', {}).get('playAddr')
                                or video_data.get('video', {}).get('play_addr')
                            ) or find_any_url(video_data)

                            if candidate:
                                try:
                                    resp = requests.get(candidate, timeout=20)
                                    resp.raise_for_status()
                                    video_bytes = resp.content
                                except Exception as e:
                                    print(f"[WARN] HTTP download failed for {vid_id}: {e}")
                            else:
                                print(f"[WARN] No video URL found for {vid_id}")

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

                    if updated:
                        fg.updated(updated)
                    fg.rss_file(f'rss/{user}.xml', pretty=True)

                except Exception as e:
                    msg = str(e).lower()
                    if 'empty response' in msg:
                        print(f"[ERROR] TikTok blocked us for {user}: {e}")
                    else:
                        print(f"[ERROR] Unexpected error for {user}: {e}")

if __name__ == '__main__':
    asyncio.run(user_videos())
