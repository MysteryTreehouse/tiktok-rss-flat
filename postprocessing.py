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

# Configuration
ghRawURL = config.ghRawURL
ms_token = os.environ.get("MS_TOKEN")
force_last = os.environ.get("FORCE_LAST_REFRESH") == "1"

async def runscreenshot(playwright, url, screenshotpath):
    browser = await playwright.chromium.launch(headless=True)
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
            # Initialize API and session
            async with TikTokApi() as api:
                await api.create_sessions(
                    ms_tokens=[ms_token],
                    num_sessions=1,
                    sleep_after=3,
                    headless=True
                )

                ttuser = api.user(user)
                try:
                    await ttuser.info()
                    count = 1 if force_last else 10
                    async for video in ttuser.videos(count=count):
                        # safe metadata
                        try:
                            video_data = video.dict()
                        except:
                            video_data = {}

                        fe = fg.add_entry()
                        vid_id = video_data.get('id') or getattr(video, 'id', None)
                        link = f'https://www.tiktok.com/@{user}/video/{vid_id}'
                        fe.id(link)

                        # timestamps
                        ts_val = video_data.get('createTime') or video_data.get('create_time')
                        ts = None
                        if ts_val is not None:
                            if isinstance(ts_val, (int, float)):
                                ts = datetime.fromtimestamp(ts_val, timezone.utc)
                            elif isinstance(ts_val, datetime):
                                if ts_val.tzinfo is None:
                                    ts = ts_val.replace(tzinfo=timezone.utc)
                                else:
                                    ts = ts_val
                        if ts:
                            fe.published(ts)
                            fe.updated(ts)
                            updated = max(updated, ts) if updated else ts

                        # title + link
                        title = video_data.get('desc') or 'TikTok video'
                        fe.title(title[:255])
                        fe.link(href=link)

                        # video download logic
                        video_bytes = None
                        # 1) built-in bytes()
                        try:
                            video_bytes = await api.video(id=vid_id).bytes()
                        except:
                            pass
                        # 2) download helper
                        if not video_bytes or len(video_bytes) < 100000:
                            try:
                                tmp_path = Path('videos') / user / f"{vid_id}.mp4"
                                tmp_path.parent.mkdir(parents=True, exist_ok=True)
                                await api.video(id=vid_id).download(tmp_path)
                                with open(tmp_path, 'rb') as f:
                                    video_bytes = f.read()
                            except:
                                pass
                        # 3) HTTP fallback
                        if not video_bytes or len(video_bytes) < 100000:
                            # check known fields
                            candidate = (
                                video_data.get('video', {}).get('downloadAddrNoWaterMark') or
                                video_data.get('video', {}).get('download_addr_no_water_mark') or
                                video_data.get('video', {}).get('downloadAddr') or
                                video_data.get('video', {}).get('download_addr')
                            )
                            # list fallback
                            if not candidate:
                                dl_list = video_data.get('video', {}).get('download_addr_list') or video_data.get('video', {}).get('downloadAddrList')
                                if isinstance(dl_list, list) and dl_list:
                                    first = dl_list[0]
                                    if isinstance(first, dict):
                                        url_list = first.get('url_list') or first.get('urlList')
                                        if isinstance(url_list, list) and url_list:
                                            candidate = url_list[0]
                            # recursive fallback
                            if not candidate:
                                candidate = find_any_url(video_data)

                            if candidate:
                                try:
                                    headers = {"User-Agent": "Mozilla/5.0"}
                                    resp = requests.get(candidate, headers=headers, timeout=20)
                                    resp.raise_for_status()
                                    if 'video' in resp.headers.get('Content-Type', ''):
                                        video_bytes = resp.content
                                    else:
                                        print(f"[WARN] HTTP URL did not return video for {vid_id}")
                                except Exception as e:
                                    print(f"[WARN] HTTP download failed for {vid_id}: {e}")
                            else:
                                print(f"[WARN] No video URL found for {vid_id}")

                        # write file + enclosure
                        if video_bytes:
                            out_dir = Path('videos') / user
                            out_dir.mkdir(parents=True, exist_ok=True)
                            path = out_dir / f"{vid_id}.mp4"
                            with open(path, 'wb') as wf:
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
