# -*- coding: utf-8 -*-
"""发出前整理微信回复：识别 Markdown 结构，转成普通文本后一次发完。"""

from __future__ import annotations

import re


class WeChatPlainTextFormatter:
    """把 LLM Markdown 转成微信可用的普通文本。

    不全局删除 `|`，只在识别到 Markdown Table（含 separator 行）时改写表格。
    """

    _TABLE_SEP = re.compile(
        r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$"
    )
    _HEADING = re.compile(r"^#{1,6}\s*", re.M)
    _BOLD = re.compile(r"\*\*(.+?)\*\*")
    _BOLD_US = re.compile(r"__(.+?)__")
    _ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
    _INLINE_CODE = re.compile(r"`([^`]+)`")
    _LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    _QUOTE = re.compile(r"^>\s?", re.M)
    _FENCE = re.compile(r"```[^\n]*\n?(.*?)```", re.DOTALL)

    def format(self, text):
        if not text:
            return ""
        s = str(text).replace("\r\n", "\n").replace("\r", "\n")
        s, code_blocks = self._extract_code_fences(s)
        s = self._convert_tables(s)
        s = self._strip_inline_markdown(s)
        s = self._restore_code_blocks(s, code_blocks)
        s = s.replace("```", "")
        s = re.sub(r"[ \t]+\n", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()

    def _extract_code_fences(self, text):
        blocks = []

        def repl(match):
            blocks.append((match.group(1) or "").strip("\n"))
            return "\n<<<WECHAT_CODE_%d>>>\n" % (len(blocks) - 1)

        return self._FENCE.sub(repl, text), blocks

    def _restore_code_blocks(self, text, blocks):
        s = text
        for idx, body in enumerate(blocks):
            s = s.replace("<<<WECHAT_CODE_%d>>>" % idx, body)
        return s

    def _convert_tables(self, text):
        lines = text.split("\n")
        out = []
        i = 0
        n = len(lines)
        while i < n:
            if (
                i + 1 < n
                and self._looks_like_table_row(lines[i])
                and self._TABLE_SEP.match(lines[i + 1])
            ):
                header = self._split_row(lines[i])
                i += 2
                body = []
                while i < n and self._looks_like_table_row(lines[i]):
                    body.append(self._split_row(lines[i]))
                    i += 1
                converted = self._format_table(header, body)
                if converted:
                    out.append(converted)
                continue
            if self._TABLE_SEP.match(lines[i]):
                i += 1
                continue
            out.append(lines[i])
            i += 1
        return "\n".join(out)

    def _looks_like_table_row(self, line):
        if not line or not line.strip():
            return False
        if self._TABLE_SEP.match(line):
            return False
        return "|" in line

    def _split_row(self, line):
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [cell.strip() for cell in s.split("|")]

    def _format_table(self, header, body):
        if not body:
            labels = [cell for cell in header if cell]
            return "\n".join(labels)
        blocks = []
        for row in body:
            parts = []
            width = max(len(header), len(row))
            for idx in range(width):
                name = header[idx] if idx < len(header) else ""
                value = row[idx] if idx < len(row) else ""
                if name:
                    parts.append("%s：%s" % (name, value))
                elif value:
                    parts.append(value)
            if parts:
                blocks.append("\n".join(parts))
        return "\n\n".join(blocks)

    def _strip_inline_markdown(self, text):
        s = self._INLINE_CODE.sub(r"\1", text)
        s = self._BOLD.sub(r"\1", s)
        s = self._BOLD_US.sub(r"\1", s)
        s = self._ITALIC.sub(r"\1", s)
        s = self._HEADING.sub("", s)
        s = self._LINK.sub(r"\1", s)
        s = self._QUOTE.sub("", s)
        s = s.replace("**", "").replace("__", "")
        return s


_FORMATTER = WeChatPlainTextFormatter()


def strip_markdown_for_wechat(text):
    """微信不渲染 Markdown，发出前转成普通文本。"""
    return _FORMATTER.format(text)


def split_message_with_context(text):
    """只把拍一拍/撤回标记拆成独立动作，正文一次发完，不再按换行或 $ 分段。"""
    if not text:
        return []
    tickle_pattern = r"(\[tickle\]|\[tickle_self\]|\[recall\])"
    chunks = re.split(tickle_pattern, text)
    result_parts = []
    text_buf = []
    for chunk in chunks:
        if not chunk:
            continue
        if chunk in ("[tickle]", "[tickle_self]", "[recall]"):
            joined = "".join(text_buf).strip()
            if joined:
                result_parts.append(joined)
            text_buf = []
            result_parts.append(chunk)
            continue
        text_buf.append(chunk.replace("\\n", "\n"))
    joined = "".join(text_buf).strip()
    if joined:
        result_parts.append(joined)
    return [p for p in result_parts if p]
