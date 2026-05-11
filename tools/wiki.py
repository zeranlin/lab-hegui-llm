#!/usr/bin/env python3
"""LLM Wiki 本地维护命令。

Commands:
  ingest <path>     为 raw 文件创建来源笔记，并更新索引/日志。
  query <text>      检索 wiki Markdown 文件。
  lint              检查常见 wiki 结构问题。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw"
WIKI_DIR = ROOT / "wiki"
LOG_FILE = WIKI_DIR / "log.md"
INDEX_FILE = WIKI_DIR / "index.md"
SOURCES_DIR = WIKI_DIR / "50-语料与摘录"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def slugify(name: str) -> str:
    base = Path(name).stem.strip()
    base = re.sub(r"[\\/:*?\"<>|]+", "-", base)
    base = re.sub(r"\s+", "-", base)
    return base[:120] or "source"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.write_text("# LLM Wiki 日志\n\n类型:: 日志\n状态:: 有效\n", encoding="utf-8")
    stamp = datetime.now().strftime("%Y-%m-%d")
    moment = datetime.now().strftime("%H:%M")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## [{stamp}] ingest | {message}\n\n- 时间：{moment}\n")


def append_index_source(note: Path, source: Path) -> None:
    if not INDEX_FILE.exists():
        return
    body = INDEX_FILE.read_text(encoding="utf-8")
    marker = "## 来源笔记"
    line = f"- [[{rel(note)[:-3]}]] - 来源笔记：`{rel(source)}`"
    if line in body:
        return
    if marker not in body:
        body = body.rstrip() + f"\n\n{marker}\n\n"
    body = body.rstrip() + f"\n{line}\n"
    INDEX_FILE.write_text(body, encoding="utf-8")


def ingest(path_text: str) -> int:
    source = Path(path_text)
    if not source.is_absolute():
        source = ROOT / source
    source = source.resolve()

    if not source.exists():
        print(f"missing source: {source}", file=sys.stderr)
        return 1
    if not source.is_file():
        print(f"source is not a file: {source}", file=sys.stderr)
        return 1
    try:
        source.relative_to(RAW_DIR.resolve())
    except ValueError:
        print("source must be under raw/", file=sys.stderr)
        return 1

    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(source.name)
    note = SOURCES_DIR / f"{slug}.md"
    counter = 2
    while note.exists():
        note = SOURCES_DIR / f"{slug}-{counter}.md"
        counter += 1

    size = source.stat().st_size
    digest = file_sha256(source)
    now = datetime.now().strftime("%Y-%m-%d")
    content = f"""# {source.name}

类型:: 来源
状态:: 待抽取
来源文件:: {rel(source)}
文件大小:: {size}
sha256:: {digest}
入库日期:: {now}

## 来源摘要

待补充：文件类型、采购项目、采购方式、采购人、代理机构、预算金额。

## 抽取任务

- [ ] 项目基本信息
- [ ] 供应商资格条件
- [ ] 技术参数和采购需求
- [ ] 评分办法
- [ ] 合同条款
- [ ] 政府采购政策条款
- [ ] 疑似风险条款

## 证据摘录

> 待补充原文摘录，保留页码、章节号或条款号。

## 相关笔记

- [[wiki/60-提示词/条款抽取提示词]]
- [[wiki/60-提示词/招标文件合规审查总提示词]]
"""
    note.write_text(content, encoding="utf-8")
    append_index_source(note, source)
    append_log(f"{source.name}")
    print(rel(note))
    return 0


def query(text: str) -> int:
    pattern = text.lower()
    matches: list[str] = []
    for path in sorted(WIKI_DIR.rglob("*.md")):
        body = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(body.splitlines(), start=1):
            if pattern in line.lower():
                matches.append(f"{rel(path)}:{lineno}: {line.strip()}")
    if not matches:
        print("no matches")
        return 1
    print("\n".join(matches))
    return 0


def collect_wiki_targets() -> set[str]:
    targets: set[str] = set()
    for path in WIKI_DIR.rglob("*.md"):
        stem = rel(path)[:-3]
        wiki_relative = path.relative_to(WIKI_DIR).as_posix()[:-3]
        targets.add(stem)
        targets.add(wiki_relative)
        targets.add(Path(stem).name)
    return targets


def lint() -> int:
    problems: list[str] = []
    if not (ROOT / "AGENTS.md").exists():
        problems.append("missing AGENTS.md")
    if not INDEX_FILE.exists():
        problems.append("missing wiki/index.md")
    if not LOG_FILE.exists():
        problems.append("missing wiki/log.md")

    targets = collect_wiki_targets()
    wikilink_re = re.compile(r"\[\[(.+?)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
    inbound: dict[str, int] = {target: 0 for target in targets}
    for path in sorted(WIKI_DIR.rglob("*.md")):
        body = path.read_text(encoding="utf-8", errors="ignore")
        for match in wikilink_re.finditer(body):
            target = match.group(1).strip()
            if target not in targets:
                problems.append(f"broken wikilink in {rel(path)}: [[{target}]]")
            else:
                inbound[target] = inbound.get(target, 0) + 1
        if path.name not in {"index.md", "log.md"} and "::" not in body[:500]:
            problems.append(f"missing metadata fields near top: {rel(path)}")
        if path.name == "index.md" and " - " not in body:
            problems.append("wiki/index.md should list pages with one-line summaries")

    if LOG_FILE.exists():
        log_body = LOG_FILE.read_text(encoding="utf-8", errors="ignore")
        if "## [" not in log_body:
            problems.append("wiki/log.md should use parseable headings like `## [YYYY-MM-DD] ingest | title`")

    if INDEX_FILE.exists():
        index_body = INDEX_FILE.read_text(encoding="utf-8", errors="ignore")
        indexed_pages = {match.group(1).strip() for match in wikilink_re.finditer(index_body)}
        for path in sorted(WIKI_DIR.rglob("*.md")):
            if path.name in {"index.md", "log.md"}:
                continue
            target = rel(path)[:-3]
            wiki_relative = path.relative_to(WIKI_DIR).as_posix()[:-3]
            basename = Path(target).name
            if target not in indexed_pages and wiki_relative not in indexed_pages and basename not in indexed_pages:
                problems.append(f"page missing from wiki/index.md: {rel(path)}")

    if problems:
        print("\n".join(problems))
        return 1
    print("lint ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki 本地维护工具")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = sub.add_parser("ingest", help="为 raw 文件创建来源笔记")
    ingest_cmd.add_argument("path")

    query_cmd = sub.add_parser("query", help="search wiki markdown")
    query_cmd.add_argument("text")

    sub.add_parser("lint", help="check wiki hygiene")

    args = parser.parse_args()
    if args.command == "ingest":
        return ingest(args.path)
    if args.command == "query":
        return query(args.text)
    if args.command == "lint":
        return lint()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
