"""增量提取流式 JSON 对象中某个顶层字符串字段的内容。"""

from __future__ import annotations

_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class JSONStringFieldStream:
    """逐块喂入 JSON 文本，返回目标顶层字符串字段新增的已解码文本。

    只关心根对象第一层的 `field`；嵌套结构与其他字段会被跳过。
    输入允许在任意位置截断（包括转义序列中间）。
    """

    def __init__(self, field: str) -> None:
        self._field = field
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._unicode: list[str] | None = None
        self._high_surrogate: int | None = None
        self._role = "other"  # key | target | other：当前字符串的角色
        self._key_chars: list[str] = []
        self._last_key = ""
        self._expect_value = False

    def feed(self, chunk: str) -> str:
        out: list[str] = []
        for ch in chunk:
            if self._in_string:
                self._feed_string_char(ch, out)
            else:
                self._feed_structural_char(ch)
        return "".join(out)

    def _feed_structural_char(self, ch: str) -> None:
        if ch == '"':
            self._in_string = True
            if self._depth == 1 and self._expect_value:
                self._role = "target" if self._last_key == self._field else "other"
                self._expect_value = False
            elif self._depth == 1:
                self._role = "key"
                self._key_chars = []
            else:
                self._role = "other"
        elif ch in "{[":
            self._depth += 1
        elif ch in "}]":
            self._depth -= 1
        elif ch == ":" and self._depth == 1:
            self._expect_value = True
        elif ch == "," and self._depth == 1:
            self._expect_value = False

    def _feed_string_char(self, ch: str, out: list[str]) -> None:
        if self._unicode is not None:
            self._unicode.append(ch)
            if len(self._unicode) == 4:
                digits = "".join(self._unicode)
                self._unicode = None
                try:
                    self._emit(self._decode_code_unit(int(digits, 16)), out)
                except ValueError:
                    pass
            return
        if self._escape:
            self._escape = False
            if ch == "u":
                self._unicode = []
            else:
                self._emit(_SIMPLE_ESCAPES.get(ch, ch), out)
            return
        if ch == "\\":
            self._escape = True
        elif ch == '"':
            self._in_string = False
            if self._role == "key":
                self._last_key = "".join(self._key_chars)
        else:
            self._emit(ch, out)

    def _decode_code_unit(self, code: int) -> str:
        if 0xD800 <= code <= 0xDBFF:
            self._high_surrogate = code
            return ""
        if 0xDC00 <= code <= 0xDFFF and self._high_surrogate is not None:
            high, self._high_surrogate = self._high_surrogate, None
            return chr(0x10000 + ((high - 0xD800) << 10) + (code - 0xDC00))
        self._high_surrogate = None
        return chr(code)

    def _emit(self, text: str, out: list[str]) -> None:
        if not text:
            return
        if self._role == "target":
            out.append(text)
        elif self._role == "key":
            self._key_chars.append(text)
