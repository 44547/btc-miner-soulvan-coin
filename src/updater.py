import aiohttp
import os
import webbrowser
from typing import Optional

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"

async def latest_release_info(owner: str, repo: str) -> Optional[dict]:
    url = GITHUB_API.format(owner=owner, repo=repo)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={"Accept": "application/vnd.github+json"}) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

def open_release_in_browser(html_url: str):
    # prefer devcontainer host browser helper if available
    browser = os.environ.get("BROWSER")
    if browser:
        os.system(f'"$BROWSER" "{html_url}" &')
    else:
        webbrowser.open(html_url)

async def check_and_show_release(owner: str, repo: str, current_version: str) -> bool:
    info = await latest_release_info(owner, repo)
    if not info:
        return False
    tag = info.get("tag_name", "")
    if tag and tag != current_version:
        open_release_in_browser(info.get("html_url", ""))
        return True
    return False
