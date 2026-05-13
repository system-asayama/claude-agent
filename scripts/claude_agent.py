#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, json, requests, base64
import anthropic

ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']
GH_PAT = os.environ['GH_PAT']
ISSUE_TITLE = os.environ['ISSUE_TITLE']
ISSUE_BODY = os.environ.get('ISSUE_BODY', '')
ISSUE_NUMBER = os.environ['ISSUE_NUMBER']
REPO_OWNER = os.environ['REPO_OWNER']
AGENT_REPO = f"{REPO_OWNER}/claude-agent"

GH_HEADERS = {
    'Authorization': f'token {GH_PAT}',
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json'
}

def post_comment(text):
    url = f'https://api.github.com/repos/{AGENT_REPO}/issues/{ISSUE_NUMBER}/comments'
    requests.post(url, headers=GH_HEADERS, json={'body': text})

def get_file(repo, path):
    url = f'https://api.github.com/repos/{repo}/contents/{path}'
    r = requests.get(url, headers=GH_HEADERS)
    return r.json() if r.status_code == 200 else None

def put_file(repo, path, content, sha, msg):
    url = f'https://api.github.com/repos/{repo}/contents/{path}'
    data = {'message': f'[claude-agent] {msg}',
            'content': base64.b64encode(content.encode()).decode(),
            'sha': sha} if sha else {
            'message': f'[claude-agent] {msg}',
            'content': base64.b64encode(content.encode()).decode()}
    r = requests.put(url, headers=GH_HEADERS, json=data)
    return r.status_code in (200, 201)

def get_structure(repo):
    url = f'https://api.github.com/repos/{repo}/contents/'
    r = requests.get(url, headers=GH_HEADERS)
    if r.status_code != 200: return ''
    return '\n'.join([f"{'📁' if i['type']=='dir' else '📄'} {i['path']}" for i in r.json()[:30]])

repo_match = re.search(r'リポジトリ[\uff1a:] *([\w\-\.]+/[\w\-\.]+)', ISSUE_BODY)
target_repo = repo_match.group(1).strip() if repo_match else None

if not target_repo:
    post_comment("⚠️ リポジトリが指定されていません。\n\n```\nリポジトリ: system-asayama/login-system-app\n\n## 指示\nここに指示を書く\n```")
    exit()

post_comment(f"🤖 Claude Agent起動！\n\n対象: `{target_repo}`\n\n処理中...")

file_matches = re.findall(r'ファイル[\uff1a:] *([\w\./\-]+)', ISSUE_BODY)
file_contents = {}
for fp in file_matches:
    fd = get_file(target_repo, fp)
    if fd:
        file_contents[fp] = {'content': base64.b64decode(fd['content']).decode(), 'sha': fd['sha']}

structure = get_structure(target_repo)

user_msg = f"## 対象リポジトリ\n{target_repo}\n\n## 構造\n{structure}\n\n## 指示\n{ISSUE_BODY}\n"
if file_contents:
    user_msg += "\n## 現在のファイル内容\n"
    for p, d in file_contents.items():
        user_msg += f"\n### {p}\n```\n{d['content'][:5000]}\n```\n"

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
resp = client.messages.create(
    model='claude-opus-4-5',
    max_tokens=8000,
    system='GitHubリポジトリのコードを修正するエージェントです。必ず以下のJSON形式のみで返答してください（マークダウン不要）:\n{"summary": "変更内容の説明", "files": [{"path": "ファイルパス", "content": "変更後の完全な内容", "commit_message": "コミットメッセージ"}]}',
    messages=[{'role': 'user', 'content': user_msg}]
)

try:
    text = resp.content[0].text.strip()
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    result = json.loads(text)
except Exception as e:
    post_comment(f"❌ JSONパースエラー: {e}")
    exit()

updated, errors = [], []
for fi in result.get('files', []):
    sha = file_contents.get(fi['path'], {}).get('sha') or (get_file(target_repo, fi['path']) or {}).get('sha')
    if put_file(target_repo, fi['path'], fi['content'], sha, fi.get('commit_message', '更新')):
        updated.append(fi['path'])
    else:
        errors.append(fi['path'])

comment = f"✅ **完了！**\n\n{result.get('summary','')}\n\n**変更ファイル:**\n"
for f in updated: comment += f"- `{f}`\n"
if errors: comment += f"\n⚠️ エラー:\n" + ''.join([f"- `{f}`\n" for f in errors])
post_comment(comment)
