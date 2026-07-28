"""Anki template field inspection shared by setup and runtime routing."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List, Set


class _VisibleTemplateParser(HTMLParser):
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.hidden_stack: List[bool] = []
        self.visible_text: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if str(tag or "").casefold() in self._VOID_TAGS:
            return
        attributes = {str(key).casefold(): str(value or "") for key, value in attrs}
        classes = set(attributes.get("class", "").casefold().split())
        style = re.sub(r"\s+", "", attributes.get("style", "").casefold())
        hidden = (
            bool(self.hidden_stack and self.hidden_stack[-1])
            or "hidden" in classes
            or "hidden" in attributes
            or "display:none" in style
            or "visibility:hidden" in style
        )
        self.hidden_stack.append(hidden)

    def handle_startendtag(self, tag: str, attrs) -> None:
        # Self-closing elements cannot contain template text and must not alter
        # the surrounding hidden/visible stack.
        return

    def handle_endtag(self, tag: str) -> None:
        if str(tag or "").casefold() in self._VOID_TAGS:
            return
        if self.hidden_stack:
            self.hidden_stack.pop()

    def handle_data(self, data: str) -> None:
        if not self.hidden_stack or not self.hidden_stack[-1]:
            self.visible_text.append(data)


def visible_question_field_names(qfmt: str) -> Set[str]:
    """Return fields whose values are visibly rendered by a question template."""
    parser = _VisibleTemplateParser()
    try:
        parser.feed(str(qfmt or ""))
        parser.close()
    except Exception:
        return set()
    visible_template = " ".join(parser.visible_text)
    names: Set[str] = set()
    for match in re.finditer(r"{{\s*([^{}]+?)\s*}}", visible_template):
        expression = match.group(1).strip()
        if expression[:1] in {"#", "/", "^"}:
            # Section markers control whether their body is rendered; they do
            # not display the referenced field value themselves.
            continue
        filters = [part.strip().casefold() for part in expression.split(":")[:-1]]
        if any(item in {"hint", "type"} for item in filters):
            # These filters render a control or input box, not the field value.
            continue
        if ":" in expression:
            expression = expression.rsplit(":", 1)[-1].strip()
        if expression and expression.casefold() not in {
            "tags",
            "frontside",
            "deck",
            "subdeck",
            "card",
        }:
            names.add(expression)
    return names
