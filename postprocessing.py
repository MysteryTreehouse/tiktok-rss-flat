import os
import asyncio
import csv
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator
from TikTokApi import TikTokApi
import config
from playwright.async_api import async_playwright, Playwright
from pathlib import Path
from urllib.parse import urlparse

# Edit config.py to change your URLs
ghRawURL = config.ghRawURL
ms_token = os.environ.get("MS_TOKEN")

async def runscreenshot(playwright: Playwright, url, screenshotpath):
    browser = await playwright.chromium.launch()
    page = await browser.new_page()
    await page.goto(url)
    await page.screenshot(path=screenshotpath, quality=20, type='jpeg')
    await browser.close()

async def user_videos():
    with open('subscriptions.csv') as f:
        cf = csv.DictReader(f, fieldnames=['username'])
        for row in cf:
            user = row['username'].strip()
            print(f"Running for user '{user}'")

            fg = FeedGenerator()
            fg.id(f'https://www.tiktok.com/@{user}')
            fg.title(f'{user} TikTok')
            fg.author({'name': 'Conor ONeill', 'email': 'conor@conoroneill.com'})
            fg.link(href='http://tiktok.com', rel='alternate')
            fg.logo(ghRawURL + 'tiktok-rss.png')
            fg.subtitle(f'OK Boomer, all the latest TikToks from {user}')
            fg.link(href=ghRawURL + f'rss/{user}.xml', rel='self')
            fg.language('en')

            updated = None
            async with TikTokApi() as api:
                await api.create_sessions(ms_tokens=[ms_token], num_sessions=1, sleep_after=3, headless=False)
                ttuser = api.user(user)
                try:
                    await ttuser.info()
                    async for video in ttuser.videos(count=10):
                        # Safely convert Video model to dict
                        try:
                            video_data = video.dict()
                        except:
                            video_data = {}

                        fe = fg.add_entry()
                        vid_id = video.id if hasattr(video, 'id') else video_data.get('id')
                        link = f'https://tiktok.com/@{user}/video/{vid_id}'
                        fe.id(link)

                        # Timestamps
                        create_ts = video_data.get('createTime') or video_data.get('create_time')
                        if create_ts:
                            ts = datetime.fromtimestamp(create_ts, timezone.utc)
                            fe.published(ts)
                            fe.updated(ts)
                            updated = max(ts, updated) if updated else ts

                        # Title
                        title = video_data.get('desc') or 'No Title'
                        fe.title(title[:255])
                        fe.link(href=link)

                        # Download via TikTokApi
                        try:
                            video_bytes = await api.video(id=vid_id).bytes()
                            video_dir = Path("videos") / user
                            video_dir.mkdir(parents=True, exist_ok=True)
                            video_path = video_dir / f"{vid_id}.mp4"
                            with open(video_path, "wb") as f:
                                f.write(video_bytes)

                            public_url = ghRawURL + f"videos/{user}/{vid_id}.mp4"
                            fe.enclosure(public_url, str(len(video_bytes)), "video/mp4")
                        except Exception as e:
                            print(f"[WARN] TikTokApi download failed for {vid_id}: {e}")
                            fe.enclosure(link, "0", "video/mp4")

                        # Thumbnail + description
                        desc_text = title
                        cover = video_data.get('video', {}).get('cover')
                        if cover:
                            parsed = urlparse(cover)
                            filename = Path(parsed.path).name
                            thumb_path = f'thumbnails/{user}/screenshot_{filename}.jpg'
                            full_thumb = Path(__file__).parent / thumb_path
                            if not full_thumb.exists():
                                async with async_playwright() as pw:
                                    await runscreenshot(pw, cover, str(full_thumb))
                            thumb_url = ghRawURL + thumb_path
                            content = f'<img src="{thumb_url}" /> {desc_text}'
                        else:
                            content = desc_text
                        fe.content(content)

                    # Write out the feed
                    if updated:
                        fg.updated(updated)
                    fg.rss_file(f'rss/{user}.xml', pretty=True)

                except Exception as e:
                    print(f"Error for user {user}: {e}")

if __name__ == '__main__':
    asyncio.run(user_videos())
