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
import requests  # for HEAD requests to get video size

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
                        fe = fg.add_entry()
                        link = f'https://tiktok.com/@{user}/video/{video.id}'
                        fe.id(link)

                        ts = datetime.fromtimestamp(video.as_dict['createTime'], timezone.utc)
                        fe.published(ts)
                        fe.updated(ts)
                        updated = max(ts, updated) if updated else ts

                        # Title and basic link
                        title = video.as_dict.get('desc', 'No Title')[:255]
                        fe.title(title)
                        fe.link(href=link)

                        # Fetch TikTok download URL
                        video_url = video.as_dict['video'].get('downloadAddr')
                        if video_url:
                            # Try HEAD for size
                            try:
                                head = requests.head(video_url, allow_redirects=True)
                                video_size = head.headers.get('Content-Length', '0')
                            except Exception:
                                video_size = '0'

                            # Attempt self-host download, fallback on failure
                            try:
                                resp = requests.get(
                                    video_url,
                                    headers={"Range": "bytes=0-", "Referer": "https://www.tiktok.com"},
                                    cookies={"msToken": ms_token},
                                    stream=True,
                                    timeout=60
                                )
                                resp.raise_for_status()

                                video_dir = Path("videos") / user
                                video_dir.mkdir(parents=True, exist_ok=True)
                                video_path = video_dir / f"{video.id}.mp4"
                                with open(video_path, "wb") as f:
                                    for chunk in resp.iter_content(8192):
                                        f.write(chunk)

                                public_url = ghRawURL + f"videos/{user}/{video.id}.mp4"
                                fe.enclosure(public_url, resp.headers.get("Content-Length", video_size), "video/mp4")
                            except Exception as e:
                                print(f"[WARN] failed to download self-host MP4 for {video_url!r}: {e}")
                                fe.enclosure(video_url, video_size, "video/mp4")

                        # Create description with thumbnail
                        desc_text = video.as_dict.get('desc', 'No Description')[:255]
                        if video.as_dict['video'].get('cover'):
                            cover_url = video.as_dict['video']['cover']
                            parsed = urlparse(cover_url)
                            filename = Path(parsed.path).name
                            thumb_path = f'thumbnails/{user}/screenshot_{filename}.jpg'
                            full_thumb = Path(__file__).parent / thumb_path
                            if not full_thumb.exists():
                                async with async_playwright() as pw:
                                    await runscreenshot(pw, cover_url, str(full_thumb))
                            thumb_url = ghRawURL + thumb_path
                            content = f'<img src="{thumb_url}" /> {desc_text}'
                        else:
                            content = desc_text

                        fe.content(content)

                    # After looping all videos, write out the feed
                    if updated:
                        fg.updated(updated)
                    fg.rss_file(f'rss/{user}.xml', pretty=True)
                except Exception as e:
                    print(f"Error for user {user}: {e}")

if __name__ == '__main__':
    asyncio.run(user_videos())
