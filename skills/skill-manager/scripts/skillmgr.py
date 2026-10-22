#!/usr/bin/env python3
"""skillmgr — 盘点 / 体检 / 来源识别 / 查找安装 agent skills（只走官方工具）。

子命令:
  inventory   已安装清单（来源、ref、路径、agents、时间、功能说明）
  check       只读检查上游是否有更新（按来源预取，不改 lock、不动安装目录）
  scan        体检 + 整理建议（识别未登记技能的来源，给出官方接管命令）
  doctor      结构排障：重复、断链、name 不一致、本地改动、lock/磁盘不一致
  find        封装 npx skills find
  add         封装 npx skills add -g
  update      封装 npx skills update -g -y
  install-cli 复制自身到 ~/.local/bin/skillmgr

依赖: python3 标准库 + git + npx。网络访问仅用于:
  - check/scan: git fetch 上游 ref（缓存于 ~/.cache/skill-manager/repos）
  - scan: skills.sh 检索 API 与 GitHub API（结果缓存 7 天）
不会写入任何安装目录，不会修改 lock。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

HOME = os.path.expanduser("~")
LOCK = os.path.join(HOME, ".agents", ".skill-lock.json")
ROOTS = {
    "agents": os.path.join(HOME, ".agents", "skills"),
    "opencode": os.path.join(HOME, ".config", "opencode", "skills"),
    "claude": os.path.join(HOME, ".claude", "skills"),
}
CACHE = os.path.join(HOME, ".cache", "skill-manager")
REPO_CACHE = os.path.join(CACHE, "repos")
RESOLVE_CACHE = os.path.join(CACHE, "resolve.json")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
SKIP_FILES = {"metadata.json"}
NPX = ["npx", "-y", "skills@latest"]
FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---", re.S)
HTTP_TIMEOUT = 20
RESOLVE_TTL = 7 * 24 * 3600
VENDOR_SKILLS = {
    "officecli": "officecli skills install",
    "browser-skill": "bsk update && bsk install-skill --all -y --force",
}


# ---------------------------------------------------------------- 基础工具


def die(msg: str, code: int = 1) -> None:
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def run(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 300,
    capture: bool = True,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, cwd=cwd, timeout=timeout, text=True, env=env, capture_output=capture
        )
    except FileNotFoundError as exc:
        if shutil.which(cmd[0]) is None:
            die(f"找不到命令: {cmd[0]}")
        die(f"执行失败（工作目录不存在？）: {' '.join(cmd)} cwd={cwd} ({exc})")
    except subprocess.TimeoutExpired:
        die(f"命令超时({timeout}s): {' '.join(cmd)}")


def git(
    *args: str, cwd: str | None = None, timeout: int = 300, env: dict | None = None
) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=cwd, timeout=timeout, env=env)


def require_npx() -> None:
    if not shutil.which("npx"):
        die("找不到 npx，请先安装 Node.js 22+")


def read_lock() -> dict:
    if not os.path.isfile(LOCK):
        return {}
    try:
        with open(LOCK, encoding="utf-8") as f:
            return json.load(f).get("skills", {})
    except (OSError, json.JSONDecodeError) as exc:
        die(f"读取 {LOCK} 失败: {exc}")


def npx_ls() -> dict[str, dict]:
    """npx skills ls -g --json → {name: entry}；失败时返回空（降级到 lock）。"""
    if not shutil.which("npx"):
        return {}
    proc = run([*NPX, "ls", "-g", "--json"], timeout=180)
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return {item.get("name"): item for item in data if isinstance(item, dict)}


def skill_dirs(name: str) -> dict[str, str]:
    found = {}
    for tag, root in ROOTS.items():
        path = os.path.join(root, name)
        if os.path.exists(path) or os.path.islink(path):
            found[tag] = path
    return found


def primary_path(name: str) -> str:
    dirs = skill_dirs(name)
    return dirs.get("agents") or next(iter(dirs.values()), "")


def parse_frontmatter(path: str) -> tuple[str, str]:
    skill_md = os.path.join(path, "SKILL.md")
    try:
        with open(skill_md, encoding="utf-8", errors="replace") as f:
            head = f.read(8000)
    except OSError:
        return "", ""
    m = FRONTMATTER.match(head)
    if not m:
        return "", ""
    fm = m.group(1)
    name = ""
    desc_lines: list[str] = []
    in_desc = False
    for line in fm.splitlines():
        if re.match(r"^[A-Za-z_][\w-]*\s*:", line) and not line.startswith((" ", "\t")):
            in_desc = bool(re.match(r"^description\s*:", line))
            if in_desc:
                value = line.split(":", 1)[1].strip()
                desc_lines = [value] if value not in ("", ">", "|", ">-", "|-") else []
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip("\"'")
            continue
        if in_desc:
            desc_lines.append(line.strip())
    desc = " ".join(part for part in desc_lines if part)
    desc = re.sub(r"\s+", " ", desc).strip().strip("\"'")
    return name, desc


def content_hash(path: str) -> str:
    """与 npx skills 的 content hash 语义一致（路径 + 内容，排序，忽略 .git 等）。"""
    files: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            if fn in SKIP_FILES or fn.startswith("._"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, path).replace(os.sep, "/")
            files.append((rel, full))
    h = hashlib.sha256()
    for rel, full in sorted(files, key=lambda x: x[0]):
        h.update(rel.encode())
        try:
            with open(full, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"<unreadable>")
    return h.hexdigest()


def is_tree_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value or ""))


def fmt_time(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d")
    except ValueError:
        return value[:10]


def short(text: str, limit: int = 64) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def disp_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - disp_width(text))


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [disp_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], disp_width(cell))
    print("  ".join(pad(h, widths[i]) for i, h in enumerate(headers)).rstrip())
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(pad(cell, widths[i]) for i, cell in enumerate(row)).rstrip())


# ---------------------------------------------------------------- inventory


def build_inventory(ls: dict[str, dict] | None = None) -> list[dict]:
    lock = read_lock()
    ls = npx_ls() if ls is None else ls
    names = sorted(set(lock) | set(ls))
    rows = []
    for name in names:
        meta = lock.get(name, {})
        live = ls.get(name, {})
        path = live.get("path") or primary_path(name)
        fm_name, desc = parse_frontmatter(path) if path else ("", "")
        agents = live.get("agents") or [tag for tag in skill_dirs(name)]
        rows.append(
            {
                "name": name,
                "source": meta.get("source") or live.get("source") or "(未登记)",
                "ref": meta.get("ref") or "-",
                "path": path or "-",
                "agents": ", ".join(agents),
                "installed": fmt_time(meta.get("installedAt")),
                "updated": fmt_time(meta.get("updatedAt")),
                "description": short(desc or "(无 description)"),
                "name_matches_dir": (fm_name == name) if fm_name else None,
                "in_lock": name in lock,
                "on_disk": bool(path),
            }
        )
    return rows


def cmd_inventory(args: argparse.Namespace) -> int:
    rows = build_inventory()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("未发现已安装的 skills。")
        return 0
    print(
        f"已安装 {len(rows)} 个技能"
        f"（lock 登记 {sum(1 for r in rows if r['in_lock'])}，"
        f"磁盘存在 {sum(1 for r in rows if r['on_disk'])}）\n"
    )
    print_table(
        ["技能", "来源", "ref", "更新于", "agents", "功能"],
        [
            [
                r["name"],
                r["source"],
                r["ref"],
                fmt_time(r["updated"]),
                r["agents"],
                r["description"],
            ]
            for r in rows
        ],
    )
    print("\n提示: `skillmgr check` 看更新；`skillmgr scan` 做体检与整理建议。")
    return 0


# ---------------------------------------------------------------- 上游仓库缓存


def cache_repo(url: str) -> str:
    os.makedirs(REPO_CACHE, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", url.replace("git@github.com:", "")).strip(
        "_"
    )
    path = os.path.join(REPO_CACHE, slug)
    if os.path.isdir(os.path.join(path, ".git")):
        return path
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    proc = git(
        "clone",
        "--filter=blob:none",
        "--depth",
        "1",
        "--no-checkout",
        url,
        path,
        timeout=600,
    )
    if proc.returncode != 0:
        last = (proc.stderr.strip().splitlines() or ["未知错误"])[-1]
        raise RuntimeError(f"clone 失败: {last[:160]}")
    return path


def fetch_ref(repo: str, ref: str | None) -> str:
    target = ref or "HEAD"
    proc = git("fetch", "--depth", "1", "origin", target, cwd=repo, timeout=600)
    if proc.returncode != 0:
        last = (proc.stderr.strip().splitlines() or ["未知错误"])[-1]
        raise RuntimeError(f"fetch {target} 失败: {last[:160]}")
    return "FETCH_HEAD"


def is_tag_ref(repo: str, ref: str | None) -> bool:
    if not ref:
        return False
    proc = git(
        "ls-remote", "--tags", "origin", f"refs/tags/{ref}", cwd=repo, timeout=120
    )
    return bool(proc.stdout.strip())


def folder_of(skill_path: str) -> str:
    return os.path.dirname(skill_path.replace("\\", "/")).strip("/")


def tree_sha(repo: str, rev: str, folder: str) -> str:
    # 注意: GitHub 的 git/trees/<ref> API 对「仓库根目录技能」返回的是 commit sha，
    # 对子目录返回子树 tree sha。npx skills 原样写入 lock，这里必须复刻，否则
    # 根目录技能会被误判为「可更新」。
    spec = f"{rev}:{folder}" if folder else rev
    proc = git("rev-parse", spec, cwd=repo, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"路径不存在: {folder or '<repo root>'}")
    return proc.stdout.strip()


def prune_checkouts(max_age: int = 3600) -> None:
    """清理被中断的检出目录（checkout-*），避免缓存无限增长。"""
    try:
        for entry in os.listdir(REPO_CACHE):
            if not entry.startswith("checkout-"):
                continue
            path = os.path.join(REPO_CACHE, entry)
            try:
                if time.time() - os.path.getmtime(path) > max_age:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass
    except OSError:
        pass


def git_blob_sha(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def upstream_blobs(repo: str, rev: str, folder: str) -> dict[str, str]:
    """rev 下某目录的文件 → git blob sha（不下载文件内容）。"""
    proc = git("ls-tree", "-r", rev, "--", folder or ".", cwd=repo, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"ls-tree 失败: {proc.stderr.strip()[:160]}")
    prefix = f"{folder}/" if folder else ""
    blobs: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 3 or parts[1] != "blob":
            continue
        rel = path[len(prefix) :] if prefix and path.startswith(prefix) else path
        blobs[rel] = parts[2]
    return blobs


def local_blobs(path: str) -> dict[str, str]:
    blobs: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES or fn.startswith("._"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, path).replace(os.sep, "/")
            try:
                with open(full, "rb") as f:
                    blobs[rel] = git_blob_sha(f.read())
            except OSError:
                continue
    return blobs


def checkout_folder(repo: str, rev: str, folder: str) -> tuple[str, str]:
    """把 rev 下的 folder 检出到临时目录，返回 (临时根目录, 目标目录)。

    调用方必须删除临时根目录（不能只取 dirname(目标)：仓库根目录技能的
    dirname 就是缓存根，会误删整个缓存）。
    """
    os.makedirs(REPO_CACHE, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="checkout-", dir=REPO_CACHE)
    env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, ".index")}
    proc = git(
        "--work-tree",
        tmp,
        "checkout",
        rev,
        "--",
        folder or ".",
        cwd=repo,
        timeout=300,
        env=env,
    )
    if proc.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"checkout 失败: {proc.stderr.strip()[:160]}")
    return tmp, (os.path.join(tmp, folder) if folder else tmp)


class Source:
    """一个 (sourceUrl, ref) 的预取结果，组内所有技能共用，避免逐技能 fetch。"""

    def __init__(self, url: str, ref: str | None):
        self.url = url
        self.ref = ref
        self.repo = ""
        self.rev = ""
        self.pinned = False
        self.error = ""

    def prepare(self) -> "Source":
        try:
            self.repo = cache_repo(self.url)
            self.rev = fetch_ref(self.repo, self.ref)
            self.pinned = is_tag_ref(self.repo, self.ref)
        except Exception as exc:  # noqa: BLE001 - 报告里给出原因
            self.error = str(exc)
        return self


def prepare_sources(lock: dict, jobs: int = 6) -> dict[tuple[str, str], Source]:
    prune_checkouts()
    groups = group_lock(lock)
    sources: dict[tuple[str, str], Source] = {}
    plan: list[tuple[tuple[str, str], Source]] = []
    for key, items in groups.items():
        entry = items[0][1]
        if skip_reason(entry):
            continue
        url = entry.get("sourceUrl") or entry.get("source")
        if not url:
            continue
        src = Source(url, entry.get("ref"))
        sources[key] = src
        plan.append((key, src))
    if not plan:
        return sources
    with ThreadPoolExecutor(max_workers=max(1, min(jobs, len(plan)))) as pool:
        list(pool.map(lambda item: item[1].prepare(), plan))
    return sources


def skip_reason(entry: dict) -> str | None:
    source_type = entry.get("sourceType")
    if source_type == "local":
        return "本地路径安装（不跟上游）"
    if source_type == "well-known":
        return "well-known 源（无 lock 版本信息）"
    if not entry.get("skillFolderHash"):
        return "无版本记录（私有/已删除仓库或旧版安装）"
    if not entry.get("skillPath"):
        return "未记录 skillPath（旧版安装）"
    return None


def check_skill(
    name: str,
    entry: dict,
    sources: dict[tuple[str, str], Source],
    deep: bool = False,
) -> dict:
    result = {
        "name": name,
        "source": entry.get("source") or "-",
        "ref": entry.get("ref") or "-",
        "status": "unknown",
        "detail": "",
        "skill_path": entry.get("skillPath") or "-",
    }
    reason = skip_reason(entry)
    if reason:
        result.update(status="unmanaged", detail=reason)
        return result
    key = (str(entry.get("source") or ""), str(entry.get("ref") or ""))
    src = sources.get(key)
    if src is None:
        result.update(status="error", detail="lock 中无 sourceUrl")
        return result
    if src.error:
        result.update(status="error", detail=src.error)
        return result
    try:
        folder = folder_of(entry["skillPath"])
        local_hash = entry["skillFolderHash"]
        if is_tree_sha(local_hash):
            same = tree_sha(src.repo, src.rev, folder) == local_hash
        else:
            root, tmp = checkout_folder(src.repo, src.rev, folder)
            try:
                same = content_hash(tmp) == local_hash
            finally:
                shutil.rmtree(root, ignore_errors=True)
        if same:
            result.update(status="latest", detail="已是最新")
        elif src.pinned:
            result.update(
                status="pinned",
                detail=f"安装时钉在 tag {entry.get('ref')}，需重新 add 才能跟上游",
            )
        else:
            result.update(status="update", detail="上游有更新")
        if deep:
            target = primary_path(name)
            if target and os.path.isdir(target):
                up = upstream_blobs(src.repo, src.rev, folder)
                local = local_blobs(target)
                changed = [p for p, sha in up.items() if local.get(p) != sha]
                if changed:
                    result["detail"] += (
                        f"（安装目录有本地改动: {len(changed)} 个文件，"
                        f"如 {changed[0]}）"
                    )
    except Exception as exc:  # noqa: BLE001
        result.update(status="error", detail=str(exc))
    return result


def group_lock(lock: dict) -> dict[tuple[str, str], list[tuple[str, dict]]]:
    groups: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for name, entry in lock.items():
        key = (str(entry.get("source") or ""), str(entry.get("ref") or ""))
        groups.setdefault(key, []).append((name, entry))
    return groups


def cmd_check(args: argparse.Namespace) -> int:
    lock = read_lock()
    if not lock:
        print("lock 为空或不存在，没有可检查的技能。")
        return 0
    if args.names:
        missing = [n for n in args.names if n not in lock]
        lock = {n: e for n, e in lock.items() if n in args.names}
        for n in missing:
            print(f"跳过: {n} 不在 lock 中（本地/未登记技能）", file=sys.stderr)
    if not lock:
        return 1

    print(
        f"读取 {len(group_lock(lock))} 个上游来源…", end="", file=sys.stderr, flush=True
    )
    started = time.time()
    sources = prepare_sources(lock, jobs=args.jobs)
    print(f"\r{' ' * 40}\r", end="", file=sys.stderr)

    results = [
        check_skill(name, entry, sources, deep=args.deep)
        for _, items in group_lock(lock).items()
        for name, entry in items
    ]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    order = {"update": 0, "pinned": 1, "error": 2, "latest": 3, "unmanaged": 4}
    results.sort(key=lambda r: (order.get(r["status"], 9), r["name"]))
    labels = {
        "update": "可更新",
        "pinned": "已钉 tag",
        "error": "检查失败",
        "latest": "已最新",
        "unmanaged": "无法检查",
    }
    counts = {key: sum(1 for r in results if r["status"] == key) for key in labels}
    modified = [r for r in results if "本地改动" in r["detail"]]
    print(
        f"检查 {len(results)} 个技能（{time.time() - started:.1f}s）："
        f"可更新 {counts['update']}，已最新 {counts['latest']}，"
        f"已钉 tag {counts['pinned']}，无法检查 {counts['unmanaged']}，"
        f"失败 {counts['error']}"
        + (f"，本地改动 {len(modified)}" if modified else "")
        + "\n"
    )
    show = [r for r in results if r["status"] != "latest" or "本地改动" in r["detail"]]
    if show:
        print_table(
            ["技能", "来源", "状态", "说明"],
            [
                [
                    r["name"],
                    r["source"],
                    "本地改动"
                    if "本地改动" in r["detail"] and r["status"] == "latest"
                    else labels.get(r["status"], r["status"]),
                    short(r["detail"], 70),
                ]
                for r in show
            ],
        )
        if counts["update"]:
            print(
                "\n更新命令: skillmgr update [名称...]（等价 npx skills update -g -y）"
            )
        if modified:
            print("本地改动会在下次 update 时丢失：请把改动提回源仓库。")
    else:
        print("全部已是最新。")
    return 1 if counts["error"] else 0


# ---------------------------------------------------------------- 来源识别


def http_json(url: str, headers: dict | None = None) -> dict | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "skillmgr", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
    ):
        return None


def http_text(url: str, headers: dict | None = None) -> str | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "skillmgr", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None


def github_json(path: str) -> dict | None:
    data = http_json(f"https://api.github.com/{path}")
    if data is not None:
        return data
    if shutil.which("gh"):
        proc = run(["gh", "api", path], timeout=60)
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                return None
    return None


def local_git_evidence(path: str) -> dict | None:
    """技能目录在某个本地 git 仓库里 → 返回远端与仓库内相对路径。"""
    real = os.path.realpath(path)
    proc = git("-C", real, "rev-parse", "--show-toplevel", timeout=20)
    if proc.returncode != 0:
        return None
    top = proc.stdout.strip()
    if os.path.realpath(top) in {os.path.realpath(r) for r in ROOTS.values()}:
        return None
    remote = git("-C", top, "remote", "get-url", "origin", timeout=20)
    rel = os.path.relpath(real, top).replace(os.sep, "/")
    return {
        "top": top,
        "remote": remote.stdout.strip() if remote.returncode == 0 else "",
        "rel": rel,
        "is_symlink": os.path.islink(path),
    }


def remote_slug(remote: str) -> str:
    """git remote → owner/repo（仅 GitHub）。"""
    if not remote:
        return ""
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", remote.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower())}


def similarity(a: str, b: str) -> float:
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def find_skill_md(source: str, skill_name: str) -> str | None:
    """在候选仓库里定位技能目录的 SKILL.md 路径（GitHub tree API）。"""
    data = github_json(f"repos/{source}/git/trees/HEAD?recursive=1")
    if not data:
        return None
    candidates = []
    for item in data.get("tree", []):
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if not path.lower().endswith("skill.md"):
            continue
        parts = path.split("/")
        if parts[-2:-1] and parts[-2].lower() == skill_name.lower():
            candidates.append(path)
    if candidates:
        return sorted(candidates, key=len)[0]
    for item in data.get("tree", []):
        if item.get("type") == "blob" and item.get("path", "").lower() == "skill.md":
            return "SKILL.md"
    return None


def verify_candidate(source: str, skill_name: str, local_desc: str) -> dict:
    """确认候选仓库里确实有这个技能，并比较描述相似度。"""
    path = find_skill_md(source, skill_name)
    if not path:
        return {
            "exists": False,
            "verified": False,
            "reason": "仓库里找不到同名技能目录",
        }
    raw = http_text(f"https://raw.githubusercontent.com/{source}/HEAD/{path}")
    if raw is None:
        return {"exists": True, "verified": False, "reason": "无法读取候选 SKILL.md"}
    remote_name, remote_desc = "", ""
    m = FRONTMATTER.match(raw)
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("name:"):
                remote_name = line.split(":", 1)[1].strip().strip("\"'")
            if line.startswith("description:"):
                remote_desc = line.split(":", 1)[1].strip().strip("\"'")
    score = similarity(local_desc, remote_desc)
    return {
        "exists": True,
        "verified": bool(remote_name.lower() == skill_name.lower() and score >= 0.35),
        "score": round(score, 2),
        "remote_name": remote_name,
        "path": path,
        "reason": "" if score >= 0.35 else "描述相似度低，可能同名不同物",
    }


def skills_sh_search(name: str) -> list[dict]:
    url = "https://skills.sh/api/search?" + urllib.parse.urlencode({"q": name})
    data = http_json(url)
    if not data:
        return []
    hits = []
    for item in data.get("skills", []):
        skill_id = str(item.get("skillId") or "")
        if skill_id.lower() == name.lower():
            hits.append(
                {
                    "source": item.get("source"),
                    "skill": skill_id,
                    "installs": item.get("installs", 0),
                }
            )
    return sorted(hits, key=lambda x: -int(x.get("installs") or 0))


def load_resolve_cache() -> dict:
    try:
        with open(RESOLVE_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_resolve_cache(cache: dict) -> None:
    os.makedirs(CACHE, exist_ok=True)
    tmp = RESOLVE_CACHE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RESOLVE_CACHE)
    except OSError:
        pass


def resolve_unregistered(
    name: str, path: str, desc: str, cache: dict, refresh: bool
) -> dict:
    """按「本地 git → skills.sh → 候选验证」顺序判定未登记技能的来源。"""
    evidence = local_git_evidence(path)
    if evidence:
        return {
            "verdict": "local-repo",
            "confidence": "high",
            "detail": f"本地仓库 {evidence['top']}"
            + (f"（远端 {evidence['remote']}）" if evidence["remote"] else ""),
            "evidence": evidence,
            "candidates": [],
        }

    key = hashlib.sha1(f"{name}\n{desc}".encode()).hexdigest()[:16]
    cached = cache.get(key)
    if (
        cached
        and not refresh
        and time.time() - cached.get("checkedAt", 0) < RESOLVE_TTL
    ):
        return cached["result"]

    hits = skills_sh_search(name)
    candidates: list[dict] = []
    if hits[:5]:
        with ThreadPoolExecutor(max_workers=min(5, len(hits[:5]))) as pool:
            checks = pool.map(
                lambda hit: {**hit, **verify_candidate(hit["source"], name, desc)},
                hits[:5],
            )
            candidates = list(checks)
    existing = [c for c in candidates if c.get("exists")]
    verified = [c for c in existing if c.get("verified")]
    if verified:
        best = verified[0]
        result = {
            "verdict": "exact-verified",
            "confidence": "high",
            "detail": f"skills.sh 命中并验证: {best['source']}（{best['installs']} 次安装）",
            "candidates": verified + [c for c in candidates if c not in verified],
        }
    elif existing:
        result = {
            "verdict": "candidates",
            "confidence": "low",
            "detail": f"{len(existing)} 个同名候选存在但描述不符，需人工确认",
            "candidates": existing,
        }
    elif candidates:
        result = {
            "verdict": "not-found",
            "confidence": "none",
            "detail": "skills.sh 索引有同名条目但仓库里已不存在，按本地自建处理",
            "candidates": [],
        }
    else:
        result = {
            "verdict": "not-found",
            "confidence": "none",
            "detail": "skills.sh 无同名技能，按本地自建处理",
            "candidates": [],
        }
    cache[key] = {"checkedAt": time.time(), "result": result}
    return result


# ---------------------------------------------------------------- scan


def collect_roots() -> tuple[dict[str, dict[str, str]], list[tuple[str, str, str]]]:
    """返回 {name: {tag: path}} 与断链清单 [(tag, entry, target)]。"""
    found: dict[str, dict[str, str]] = {}
    broken: list[tuple[str, str, str]] = []
    for tag, root in ROOTS.items():
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            path = os.path.join(root, entry)
            if os.path.islink(path) and not os.path.exists(path):
                broken.append((tag, entry, os.readlink(path)))
                continue
            if os.path.isdir(path):
                found.setdefault(entry, {})[tag] = path
    return found, broken


def build_scan(resolve: bool, refresh: bool, ls: dict[str, dict] | None = None) -> dict:
    lock = read_lock()
    ls = npx_ls() if ls is None else ls
    roots, broken = collect_roots()
    cache = load_resolve_cache() if resolve else {}

    buckets = {
        "managed": [],
        "vendor": [],
        "duplicate": [],
        "resolvable": [],
        "selfbuilt": [],
        "abnormal": [],
    }

    for tag, entry, target in broken:
        buckets["abnormal"].append(
            {
                "name": entry,
                "reason": "断链",
                "detail": f"{tag}: {ROOTS[tag]}/{entry} → {target}",
                "action": f"rm {ROOTS[tag]}/{entry}",
            }
        )

    # 预处理未登记技能：并行解析，避免逐个串行等网络
    pending = []
    for name in sorted(set(roots) - set(lock)):
        if name in VENDOR_SKILLS:
            continue
        paths = roots[name]
        path = paths.get("agents") or paths[next(iter(paths))]
        fm_name, desc = parse_frontmatter(path)
        if fm_name and fm_name != name:
            continue  # 结构异常，先修 name
        pending.append((name, path, desc))
    resolutions: dict[str, dict] = {}
    if resolve and pending:
        with ThreadPoolExecutor(max_workers=min(6, len(pending))) as pool:
            resolved = pool.map(
                lambda item: resolve_unregistered(
                    item[0], item[1], item[2], cache, refresh
                ),
                pending,
            )
            resolutions = {item[0]: res for item, res in zip(pending, resolved)}

    for name in sorted(set(lock) | set(roots)):
        entry = lock.get(name, {})
        paths = roots.get(name, {})
        reals = {tag: os.path.realpath(p) for tag, p in paths.items()}
        fm_name, desc = parse_frontmatter(primary_path(name)) if paths else ("", "")
        base = {
            "name": name,
            "source": entry.get("source")
            or (ls.get(name, {}) or {}).get("source")
            or "",
            "paths": paths,
            "description": short(desc or "", 50),
        }

        if not paths:
            buckets["abnormal"].append(
                {
                    **base,
                    "reason": "lock 有登记但磁盘不存在",
                    "detail": entry.get("source") or "",
                    "action": f"npx -y skills@latest update -g {name} -y",
                }
            )
            continue
        if not os.path.isfile(os.path.join(paths[next(iter(paths))], "SKILL.md")):
            buckets["abnormal"].append(
                {
                    **base,
                    "reason": "缺少 SKILL.md",
                    "action": f"npx -y skills@latest remove -g {name} -y",
                }
            )
            continue
        if fm_name and fm_name != name:
            buckets["abnormal"].append(
                {
                    **base,
                    "reason": f"name '{fm_name}' 与目录名不一致",
                    "detail": "npx skills 用 name 作目录名",
                    "action": "改源仓库 frontmatter 后重新 add",
                }
            )
            continue

        if name in VENDOR_SKILLS:
            buckets["vendor"].append({**base, "action": VENDOR_SKILLS[name]})
            continue

        if len(set(reals.values())) > 1:
            keep = paths.get("agents") or paths[next(iter(paths))]
            drop = [
                p
                for t, p in paths.items()
                if os.path.realpath(p) != os.path.realpath(keep)
            ]
            buckets["duplicate"].append(
                {
                    **base,
                    "keep": keep,
                    "drop": drop,
                    "action": f"rm -rf {' '.join(drop)}",
                }
            )
            continue

        if entry.get("source"):
            buckets["managed"].append(
                {**base, "action": f"npx -y skills@latest update -g {name} -y"}
            )
            continue

        # 未登记来源
        info = resolutions.get(name) or {
            "verdict": "skipped",
            "confidence": "none",
            "detail": "未联网识别（--no-resolve）" if not resolve else "未完成识别",
            "candidates": [],
        }
        row = {
            **base,
            "verdict": info["verdict"],
            "confidence": info["confidence"],
            "detail": info["detail"],
            "candidates": info.get("candidates", []),
        }
        if info["verdict"] in ("exact-verified", "candidates"):
            best = info["candidates"][0]
            if info["verdict"] == "exact-verified":
                row["action"] = (
                    f"npx -y skills@latest remove -g {name} -y && "
                    f"npx -y skills@latest add {best['source']} -g -s {best['skill']} "
                    "-a opencode claude-code -y"
                )
            else:
                row["action"] = (
                    f"npx -y skills@latest use {best['source']}@{best['skill']}"
                )
            buckets["resolvable"].append(row)
        elif info["verdict"] == "local-repo":
            evidence = info.get("evidence", {})
            slug = remote_slug(evidence.get("remote", ""))
            if slug:
                row["action"] = (
                    f"# 推送到 {slug} 后: npx -y skills@latest add {slug} -g -s {name} -y"
                )
            else:
                row["action"] = (
                    f"# 为该仓库建远端后: npx -y skills@latest add <owner/repo> -g -s {name} -y"
                )
            buckets["selfbuilt"].append(row)
        else:
            row["action"] = (
                f"# 纳入 zenanswer/agent-skills 后: "
                f"npx -y skills@latest add zenanswer/agent-skills -g -s {name} -y"
            )
            buckets["selfbuilt"].append(row)

    if resolve:
        save_resolve_cache(cache)

    return {
        "summary": {
            "managed": len(buckets["managed"]),
            "vendor": len(buckets["vendor"]),
            "duplicate": len(buckets["duplicate"]),
            "resolvable": len(buckets["resolvable"]),
            "selfbuilt": len(buckets["selfbuilt"]),
            "abnormal": len(buckets["abnormal"]),
        },
        "buckets": buckets,
    }


def cmd_scan(args: argparse.Namespace) -> int:
    started = time.time()
    result = build_scan(resolve=not args.no_resolve, refresh=args.refresh)
    buckets, summary = result["buckets"], result["summary"]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"体检完成（{time.time() - started:.1f}s）\n")
    if buckets["abnormal"]:
        print("【异常】先处理，否则会互相干扰")
        print_table(
            ["技能", "问题", "说明", "建议命令"],
            [
                [r["name"], r["reason"], short(r.get("detail", ""), 40), r["action"]]
                for r in buckets["abnormal"]
            ],
        )
        print()
    if buckets["duplicate"]:
        print("【重复副本】同一技能在多个 agent 目录各有一份（内容不同）")
        print_table(
            ["技能", "保留", "建议删除"],
            [[r["name"], r["keep"], " ".join(r["drop"])] for r in buckets["duplicate"]],
        )
        print()
    if buckets["resolvable"]:
        print("【未登记 · 已识别来源】建议交给 npx skills 接管")
        print_table(
            ["技能", "识别结果", "置信度", "建议命令"],
            [
                [r["name"], short(r["detail"], 46), r["confidence"], r["action"]]
                for r in buckets["resolvable"]
            ],
        )
        print()
    if buckets["selfbuilt"]:
        print("【未登记 · 自建/未知】建议纳入自建仓库后用 npx skills 管理")
        print_table(
            ["技能", "判断依据", "建议命令"],
            [
                [r["name"], short(r["detail"], 46), r["action"]]
                for r in buckets["selfbuilt"]
            ],
        )
        print()
    if buckets["vendor"]:
        print("【厂商管理】保持各自官方安装器，不要用 npx 覆盖")
        print_table(
            ["技能", "刷新命令"],
            [[r["name"], r["action"]] for r in buckets["vendor"]],
        )
        print()
    print("【官方管理】无需动作，用 `npx skills update -g` 统一更新")
    print(
        f"  {summary['managed']} 个: "
        + ", ".join(r["name"] for r in buckets["managed"][:8])
        + (" …" if summary["managed"] > 8 else "")
    )
    print(
        f"\n合计: 官方 {summary['managed']} / 厂商 {summary['vendor']} / "
        f"重复 {summary['duplicate']} / 可接管 {summary['resolvable']} / "
        f"自建 {summary['selfbuilt']} / 异常 {summary['abnormal']}"
    )
    if (
        summary["duplicate"]
        or summary["resolvable"]
        or summary["selfbuilt"]
        or summary["abnormal"]
    ):
        print("建议顺序: 异常 → 重复副本 → 可接管来源 → 自建技能")
    return 1 if summary["abnormal"] else 0


# ---------------------------------------------------------------- doctor


def cmd_doctor(args: argparse.Namespace) -> int:
    lock = read_lock()
    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    roots, broken = collect_roots()
    for tag, entry, target in broken:
        errors.append(f"断链: {tag}/{entry} → {target}")

    for name, paths in sorted(roots.items()):
        reals = {os.path.realpath(p) for p in paths.values()}
        if len(reals) > 1:
            message = f"同名技能存在 {len(reals)} 份不同副本: {name}"
            if name in lock:
                warnings.append(message + "（只保留 ~/.agents/skills 下那份）")
            else:
                infos.append(
                    message + "（未登记来源，通常是厂商安装器分别写入各 agent 目录）"
                )
        for tag, path in paths.items():
            if not os.path.isfile(os.path.join(path, "SKILL.md")):
                errors.append(f"{tag}/{name}: 缺少 SKILL.md")
                continue
            fm_name, desc = parse_frontmatter(path)
            if not fm_name or not desc:
                errors.append(f"{tag}/{name}: frontmatter 缺 name/description")
            elif fm_name != name:
                warnings.append(
                    f"{tag}/{name}: name '{fm_name}' 与目录名不一致"
                    "（npx skills 用 name 作目录名）"
                )

    for name, entry in lock.items():
        if not primary_path(name):
            warnings.append(
                f"{name}: lock 有登记但磁盘不存在 → npx skills update -g {name} -y"
            )

    if args.deep and lock:
        print("与上游比对本地改动…", end="", file=sys.stderr, flush=True)
        sources = prepare_sources(lock, jobs=args.jobs)
        print("\r" + " " * 40 + "\r", end="", file=sys.stderr)
        for name, entry in lock.items():
            if skip_reason(entry):
                continue
            res = check_skill(name, entry, sources, deep=True)
            if "本地改动" in res["detail"]:
                warnings.append(f"{name}: 安装目录有本地改动（更新会覆盖，请改源仓库）")
            elif res["status"] == "error":
                infos.append(f"{name}: 无法比对上游（{res['detail']}）")

    for label, items in (("ERROR", errors), ("WARN", warnings), ("INFO", infos)):
        for item in items:
            print(f"{label:5} {item}")
    if not (errors or warnings):
        print("未发现结构性问题。")
    print(f"\n合计: ERROR {len(errors)} / WARN {len(warnings)} / INFO {len(infos)}")
    return 1 if errors else 0


# ---------------------------------------------------------------- 官方命令封装


def cmd_find(args: argparse.Namespace) -> int:
    require_npx()
    return subprocess.run([*NPX, "find", *args.query]).returncode


def cmd_add(args: argparse.Namespace) -> int:
    require_npx()
    if not args.source:
        die("用法: skillmgr add <owner/repo> [-s 技能名...] [-a agent...]")
    cmd = [*NPX, "add", args.source, "-g", "-y"]
    if args.skill:
        cmd += ["-s", *args.skill]
    if args.agent:
        cmd += ["-a", *args.agent]
    cmd += args.npx_args
    return subprocess.run(cmd).returncode


def cmd_update(args: argparse.Namespace) -> int:
    require_npx()
    return subprocess.run([*NPX, "update", "-g", "-y", *args.names]).returncode


def cmd_install_cli(args: argparse.Namespace) -> int:
    target_dir = os.path.join(HOME, ".local", "bin")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "skillmgr")
    shutil.copy2(os.path.abspath(__file__), target)
    os.chmod(target, 0o755)
    print(f"已安装 → {target}")
    if target_dir not in os.environ.get("PATH", "").split(":"):
        print(f"提示: 把 {target_dir} 加入 PATH 后可直接使用 skillmgr")
    return 0


# ---------------------------------------------------------------- 入口


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="skillmgr",
        description="盘点 / 体检 / 查来源 / 安装 agent skills（只走官方工具）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inventory", help="已安装清单")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("check", help="只读检查上游更新")
    p.add_argument("names", nargs="*", help="只检查这些技能（默认全部）")
    p.add_argument("--json", action="store_true")
    p.add_argument("--deep", action="store_true", help="同时检测安装目录的本地改动")
    p.add_argument("--jobs", type=int, default=6, help="并行预取的来源数（默认 6）")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("scan", help="体检并给出整理建议（识别未登记来源）")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-resolve", action="store_true", help="不联网识别未登记来源")
    p.add_argument("--refresh", action="store_true", help="忽略来源识别缓存")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("doctor", help="结构性问题排障")
    p.add_argument(
        "--deep", action="store_true", help="与上游比对，检测安装目录本地改动"
    )
    p.add_argument("--jobs", type=int, default=6)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("find", help="搜索技能（npx skills find）")
    p.add_argument("query", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("add", help="安装技能（npx skills add -g）")
    p.add_argument("source", help="owner/repo 或 git URL")
    p.add_argument("-s", "--skill", nargs="+", help="只装这些技能")
    p.add_argument(
        "-a", "--agent", nargs="+", help="目标 agent，如 opencode claude-code"
    )
    p.add_argument(
        "--npx-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="原样透传给 npx skills add 的额外参数",
    )
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("update", help="更新技能（npx skills update -g -y）")
    p.add_argument("names", nargs="*")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("install-cli", help="复制脚本到 ~/.local/bin/skillmgr")
    p.set_defaults(func=cmd_install_cli)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
