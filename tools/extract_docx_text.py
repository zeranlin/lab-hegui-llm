#!/usr/bin/env python3
"""Extract readable text from Word files.

DOCX extraction reads document.xml directly, including table cells.
Legacy DOC extraction uses antiword when available, with textutil fallback.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def node_text(node: ET.Element) -> str:
    parts: list[str] = []
    for text in node.findall(".//w:t", NS):
        if text.text:
            parts.append(text.text)
    return "".join(parts).strip()


ROOT = Path(__file__).resolve().parents[1]


def extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find("w:body", NS)
    if body is None:
        return ""

    lines: list[str] = []
    for child in body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = node_text(child)
            if text:
                lines.append(text)
        elif tag == "tbl":
            for row in child.findall(".//w:tr", NS):
                cells = [node_text(cell) for cell in row.findall("./w:tc", NS)]
                cells = [cell for cell in cells if cell]
                if cells:
                    lines.append(" | ".join(cells))
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def extract_doc(path: Path) -> str:
    antiword = shutil.which("antiword")
    if antiword:
        result = subprocess.run(
            [antiword, str(path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.decode("utf-8", errors="replace").strip() + "\n"

    textutil = shutil.which("textutil")
    if textutil:
        result = subprocess.run(
            [textutil, "-convert", "txt", "-stdout", str(path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.decode("utf-8", errors="replace").strip() + "\n"

    raise RuntimeError(f"cannot extract legacy DOC file: {path}")


def extract_word(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".doc":
        return extract_doc(path)
    raise ValueError(f"unsupported Word file: {path}")


def output_path(source: Path, out_dir: Path) -> Path:
    try:
        relative = source.resolve().relative_to((ROOT / "raw" / "招标文件").resolve())
        return out_dir / relative.with_suffix(".txt")
    except ValueError:
        return out_dir / f"{source.stem}.txt"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("word_file", nargs="+")
    parser.add_argument("--out-dir", default="raw/抽取文本")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in args.word_file:
        source = Path(item)
        text = extract_word(source)
        target = output_path(source, out_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"{source} -> {target} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
