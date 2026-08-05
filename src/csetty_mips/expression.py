from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn

from .errors import AssemblyError, SourceRef

_TOKEN = re.compile(
    r"\s*(?:(0[xX][0-9A-Fa-f_]+|0[bB][01_]+|0[oO][0-7_]+|[0-9][0-9_]*)"
    r"|([A-Za-z_.$][A-Za-z0-9_.$]*|%hi|%lo)"
    r"|('(?>[^'\\]|\\.)*')"
    r"|(\|\||&&|==|!=|<=|>=|<<|>>|[()!<>+\-*/%&|^~]))"
)
_MAX_TOKENS = 4096
_MAX_DEPTH = 256
_MAX_SHIFT = 1_000_000


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    text: str
    offset: int


def _tokenize(expression: str, source: SourceRef) -> list[_Token]:
    result: list[_Token] = []
    position = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if match is None:
            raise AssemblyError(
                "A101",
                f"invalid expression near {expression[position : position + 12]!r}",
                source.shifted(position),
            )
        if match.group(1) is not None:
            result.append(_Token("integer", match.group(1), position))
        elif match.group(2) is not None:
            result.append(_Token("identifier", match.group(2), position))
        elif match.group(3) is not None:
            result.append(_Token("character", match.group(3), position))
        else:
            result.append(_Token("operator", match.group(4), position))
        if len(result) > _MAX_TOKENS:
            raise AssemblyError(
                "A109", f"expression exceeds {_MAX_TOKENS} tokens", source.shifted(position)
            )
        position = match.end()
    result.append(_Token("end", "", len(expression)))
    return result


class _ExpressionParser:
    def __init__(self, tokens: list[_Token], symbols: Mapping[str, int], source: SourceRef) -> None:
        self._tokens = tokens
        self._symbols = symbols
        self._source = source
        self._index = 0
        self._depth = 0

    @property
    def current(self) -> _Token:
        return self._tokens[self._index]

    def consume(self) -> _Token:
        token = self.current
        self._index += 1
        return token

    def parse(self) -> int:
        value = self.parse_binary(0)
        if self.current.kind != "end":
            raise AssemblyError(
                "A102",
                f"unexpected token {self.current.text!r} in expression",
                self._source.shifted(self.current.offset),
            )
        return value

    def parse_binary(self, minimum_precedence: int, *, evaluate_value: bool = True) -> int:
        left = self.parse_unary(evaluate_value=evaluate_value)
        precedences = {
            "||": 1,
            "&&": 2,
            "|": 3,
            "^": 4,
            "&": 5,
            "==": 6,
            "!=": 6,
            "<": 7,
            "<=": 7,
            ">": 7,
            ">=": 7,
            "<<": 8,
            ">>": 8,
            "+": 9,
            "-": 9,
            "*": 10,
            "/": 10,
            "%": 10,
        }
        while self.current.kind == "operator":
            operator = self.current.text
            precedence = precedences.get(operator)
            if precedence is None or precedence < minimum_precedence:
                break
            self.consume()
            evaluate_right = evaluate_value
            if (operator == "&&" and not left) or (operator == "||" and left):
                evaluate_right = False
            right = self.parse_binary(precedence + 1, evaluate_value=evaluate_right)
            if not evaluate_value:
                left = 0
                continue
            if operator == "+":
                left += right
            elif operator == "-":
                left -= right
            elif operator == "*":
                left *= right
            elif operator == "/":
                if right == 0:
                    self._fail("division by zero in expression")
                left = abs(left) // abs(right) * (-1 if (left < 0) != (right < 0) else 1)
            elif operator == "%":
                if right == 0:
                    self._fail("modulo by zero in expression")
                quotient = abs(left) // abs(right) * (-1 if (left < 0) != (right < 0) else 1)
                left -= quotient * right
            elif operator == "<<":
                if right < 0:
                    self._fail("negative shift count in expression")
                if right > _MAX_SHIFT:
                    self._fail(f"shift count exceeds {_MAX_SHIFT} in expression")
                left <<= right
            elif operator == ">>":
                if right < 0:
                    self._fail("negative shift count in expression")
                if right > _MAX_SHIFT:
                    self._fail(f"shift count exceeds {_MAX_SHIFT} in expression")
                left >>= right
            elif operator == "&":
                left &= right
            elif operator == "^":
                left ^= right
            elif operator == "|":
                left |= right
            elif operator == "==":
                left = int(left == right)
            elif operator == "!=":
                left = int(left != right)
            elif operator == "<":
                left = int(left < right)
            elif operator == "<=":
                left = int(left <= right)
            elif operator == ">":
                left = int(left > right)
            elif operator == ">=":
                left = int(left >= right)
            elif operator == "&&":
                left = int(bool(left) and bool(right))
            elif operator == "||":
                left = int(bool(left) or bool(right))
        return left

    def parse_unary(self, *, evaluate_value: bool = True) -> int:
        self._depth += 1
        if self._depth > _MAX_DEPTH:
            raise AssemblyError(
                "A109",
                f"expression nesting exceeds {_MAX_DEPTH}",
                self._source.shifted(self.current.offset),
            )
        try:
            return self._parse_unary(evaluate_value=evaluate_value)
        finally:
            self._depth -= 1

    def _parse_unary(self, *, evaluate_value: bool) -> int:
        token = self.current
        if token.kind == "operator" and token.text in {"+", "-", "~", "!"}:
            self.consume()
            value = self.parse_unary(evaluate_value=evaluate_value)
            if not evaluate_value:
                return 0
            if token.text == "+":
                return value
            if token.text == "-":
                return -value
            if token.text == "~":
                return ~value
            return int(not value)
        if token.kind == "identifier" and token.text in {"%hi", "%lo"}:
            function = self.consume().text
            self._expect("(")
            value = self.parse_binary(0, evaluate_value=evaluate_value)
            self._expect(")")
            if not evaluate_value:
                return 0
            return (value >> 16) & 0xFFFF if function == "%hi" else value & 0xFFFF
        if token.kind == "operator" and token.text == "(":
            self.consume()
            value = self.parse_binary(0, evaluate_value=evaluate_value)
            self._expect(")")
            return value
        if token.kind == "integer":
            self.consume()
            rendered = token.text.replace("_", "")
            base = 8 if len(rendered) > 1 and rendered.startswith("0") and rendered.isdigit() else 0
            try:
                value = int(rendered, base)
            except ValueError as error:
                raise AssemblyError(
                    "A108",
                    f"invalid integer literal {token.text!r}",
                    self._source.shifted(token.offset),
                ) from error
            return value if evaluate_value else 0
        if token.kind == "character":
            self.consume()
            try:
                value = ast.literal_eval(token.text)
            except (SyntaxError, ValueError) as error:
                raise AssemblyError(
                    "A103", "invalid character literal", self._source.shifted(token.offset)
                ) from error
            if not isinstance(value, str) or len(value) != 1:
                self._fail("character literal must contain exactly one character", token)
            return ord(value) if evaluate_value else 0
        if token.kind == "identifier":
            self.consume()
            try:
                value = self._symbols[token.text]
            except KeyError as error:
                raise AssemblyError(
                    "A104",
                    f"unknown symbol {token.text!r}",
                    self._source.shifted(token.offset),
                ) from error
            return value if evaluate_value else 0
        self._fail("expected a value in expression", token)

    def _expect(self, text: str) -> None:
        if self.current.kind != "operator" or self.current.text != text:
            self._fail(f"expected {text!r} in expression")
        self.consume()

    def _fail(self, message: str, token: _Token | None = None) -> NoReturn:
        selected = token or self.current
        raise AssemblyError("A105", message, self._source.shifted(selected.offset))


def evaluate(expression: str, symbols: Mapping[str, int], source: SourceRef) -> int:
    stripped = expression.strip()
    if not stripped:
        raise AssemblyError("A100", "empty expression", source)
    return _ExpressionParser(_tokenize(stripped, source), symbols, source).parse()


def is_constant(expression: str) -> bool:
    try:
        evaluate(expression, {}, SourceRef("<constant>", 1, 1, expression))
    except AssemblyError:
        return False
    return True
