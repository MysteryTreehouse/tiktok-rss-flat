#!/usr/bin/env python3
import os
import asyncio
import csv
import requests
import json
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator
from TikTokApi import TikTokApi
import config
from playwright.async_api import async_playwright
from pathlib import Path
from urllib.parse import urlparse

# ─── monkey-patch TikTokApi so its __aexit__ is a no-op ─────────────────────────
async def _noop_aexit(self, exc_type, exc, tb):
    return None

TikTokApi.__aexit__ = _noop_aexit  # avoid trying to close a missing browser

# ─── your config and helpers ────────────────────────────────────────────────────

ghRawURL   = config.ghRawURL
ms_token   = os.environ.get("MS_TOKEN")
force_last = os.environ.get("FORCE_LAST_REFRESH") == "1"

# Parse optional proxy JSON from env
proxy_str    = os.environ.get("TIKTOK_PROXY")
proxies_list = [json.loads(proxy_str)] if proxy_str else None

async def runscreenshot(playwright, url, screenshotpath):
    launch_args = {}
    if proxy_str:
        # Playwright expects a dict with "server"
        launch_args["proxy"] = {"server": proxy_str}
    browser = await playwright.chromium.launch(**launch_args)
    page    = await browser.new_page()
    await page.goto(url)
    await page.screenshot(path=screenshotpath, quality=20, type='jpeg')
    await browser.close()

def find_any_url(obj):
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

# ─── main per-user loop ─────────────────────────────────────────────────────────

async def user_videos():
    with open('subscriptions.csv') as f:
        reader = csv.DictReader(f, fieldnames=['username'])
        for row in reader:
            user = row['username'].strip()
            print(f"Running for user '{user}'")

            fg = FeedGenerator()
            fg.id(f'https://www.tiktok.com/@{user}')
            fg.title(f'{user} TikTok')
            fg.author({'name':'Conor ONeill','email':'conor@conoroneill.com'})
            fg.link(href='http://tiktok.com', rel='alternate')
            fg.logo(g hRawURL + 'tiktok-rss.png')
            fg.subtitle(f'All the latest TikToks from {user}')
            fg.link(href=ghRawURL + f'rss/{user}.xml', rel='self')
            fg.language('en')

            updated = None

            # ── open TikTokApi session with headful WebKit ────────────────────────────
            async with TikTokApi() as api:
                try:
                    # Option A: using built-in TikTokApi proxy support
                    await api.create_sessions(
                        ms_tokens=[ms_token],
                        num_sessions=1,
                        sleep_after=3,
                        headless=False,
                        browser='webkit',
                        proxies=proxies_list
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
                        vid_id = video_data.get('id') or getattr(video,'id',None)
                        link   = f'https://www.tiktok.com/@{user}/video/{vid_id}'
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

                        # ── download video bytes ─────────────────────────
                        video_bytes = None
                        try:
                            video_bytes = await api.video(id=vid_id).bytes()
                        except Exception:
                            candidate = (
                                video_data.get('downloadAddr')
                                or video_data.get('download_addr')
                                or video_data.get('video',{}).get('downloadAddr')
                                or video_data.get('video',{}).get('download_addr')
                                or video_data.get('video',{}).get('playAddr')
                                or video_data.get('video',{}).get('play_addr')
                            ) or find_any_url(video_data)

                            if candidate:
                                try:
                                    req_kwargs = {"timeout": 20}
                                    if proxy_str:
                                        req_kwargs["proxies"] = {"http": proxy_str, "https": proxy_str}
                                    r = requests.get(candidate, **req_kwargs)
                                    r.raise_for_status()
                                    video_bytes = r.content
                                except Exception as e:
                                    print(f"[WARN] HTTP download failed for {vid_id}: {e}")
                            else:
                                print(f"[WARN] No video URL found for {vid_id}")

                        if video_bytes:
                            out_dir = Path("videos")/user
                            out_dir.mkdir(parents=True, exist_ok=True)
                            path = out_dir/f"{vid_id}.mp4"
                            with open(path,"wb") as wf:
                                wf.write(video_bytes)
                            public = ghRawURL + f"videos/{user}/{vid_id}.mp4"
                            fe.enclosure(public, str(len(video_bytes)), "video/mp4")
                        else:
                            fe.enclosure(link, "0", "video/mp4")

                        # ── thumbnail / content ───────────────────────────
                        desc  = title
                        cover = video_data.get('video',{}).get('cover')
                        if cover:
                            thumb_name = Path(urlparse(cover).path).name
                            thumb_rel  = f"thumbnails/{user}/screenshot_{thumb_name}.jpg"
                            thumb_abs  = Path(thumb_rel)
                            if not thumb_abs.exists():
                                try:
                                    async with async_playwright() as pw:
                                        await runscreenshot(pw, cover, str(thumb_abs))
                                except Exception as e:
                                    print(f"[WARN] Screenshot failed: {e}")
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
