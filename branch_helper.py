import os
import requests
from datetime import datetime

TOKEN = os.getenv("GITHUB_TOKEN")
OWNER = "dsimutin"
REPO = "runa"

def get_latest_sha():
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/commits/main"
    headers = {"Authorization": f"token {TOKEN}"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()["sha"]

def create_branch():
    sha = get_latest_sha()
    name = f"feature/update_{datetime.now().strftime('%Y%m%d_%H%M')}"
    
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/git/refs"
    headers = {"Authorization": f"token {TOKEN}"}
    
    data = {
        "ref": f"refs/heads/{name}",
        "sha": sha
    }
    
    r = requests.post(url, headers=headers, json=data)
    
    if r.status_code == 201:
        print("OK:", name)
    else:
        print("ERROR:", r.json())

if __name__ == "__main__":
    create_branch()