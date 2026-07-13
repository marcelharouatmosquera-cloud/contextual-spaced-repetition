"""HTML rendering for the contextual review webview."""

from __future__ import annotations

import json
from html import escape
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .types import ReviewTask, Token


def render_task_html(
    task: ReviewTask,
    dark_mode: bool = False,
    font_size: int = 34,
    progress_completed: int = 0,
    progress_total: int = 0,
    can_undo: bool = False,
    is_favorite: bool = False,
) -> str:
    theme = _theme(dark_mode)
    payload = {
        "sentenceId": task.sentence_id,
        "sentenceText": task.full_text,
        "translation": task.translation or "",
        "targetWords": _target_word_payload(task.target_words),
        "matchingMode": task.matching_mode,
    }
    payload_json = _script_json(payload)
    sentence_html = _render_sentence_tokens(task.tokens, theme)
    completed = max(0, min(int(progress_completed), int(progress_total)))
    total = max(0, int(progress_total))
    progress_html = ""
    if total:
        progress_percent = (completed / total) * 100
        progress_html = """
  <div
    class="session-progress"
    role="progressbar"
    aria-label="Today's review progress"
    aria-valuemin="0"
    aria-valuemax="%s"
    aria-valuenow="%s"
    style="--review-progress: %.4f%%"
  >
    <div class="progress-track" aria-hidden="true">
      <div class="progress-fill"></div>
    </div>
  </div>""" % (total, completed, progress_percent)
    undo_disabled = "" if can_undo else " disabled"
    return _page(
        """
<main class="review-shell">
  <button id="favorite" class="compact-action" type="button" title="Save sentence to favorites" aria-label="Save sentence to favorites" aria-pressed="__FAVORITE_PRESSED__">__FAVORITE_SYMBOL__</button>
  <header class="review-header">
    <p class="review-guidance">Read the sentence, then click any highlighted word you forgot.</p>
    <div id="selection-summary" class="selection-summary" aria-live="polite"></div>
  </header>
  <section id="sentence" class="sentence" aria-live="polite">__SENTENCE__</section>
  <div id="context-translation-tooltip" class="context-translation-tooltip" role="status" hidden></div>
  <section class="sentence-audio-controls">
    <button id="speak-sentence" class="compact-action" type="button" title="Read this sentence using an online voice">&#x1F50A; Read sentence</button>
    <span id="tts-status" class="tts-status" aria-live="polite"></span>
  </section>
  <section id="solution" class="solution" hidden>
    <div class="solution-block">
      <h2>Sentence Translation</h2>
      <div id="translation" class="translation"></div>
      <button id="translate-sentence" class="inline-action" type="button" hidden>Translate Sentence</button>
    </div>
    <div id="target-word-section" class="solution-block">
      <h2>Target Words</h2>
      <ul id="target-words" class="target-words"></ul>
    </div>
  </section>
  <footer class="actions">
    <button id="undo" class="compact-action" type="button" title="Previous sentence (Ctrl+Z)" aria-label="Previous sentence"__UNDO_DISABLED__>&#x21B6;</button>
    <button id="show-solution" class="primary-action" type="button">Show Solution</button>
    <button id="lookup" type="button" disabled>Look Up</button>
    <button id="submit" class="primary-action" type="button" disabled>Grade &amp; Next</button>
  </footer>
  __PROGRESS__
</main>
<script>
const task = __TASK__;
const sentence = document.getElementById("sentence");
const contextTranslationTooltip = document.getElementById("context-translation-tooltip");
const solution = document.getElementById("solution");
const translation = document.getElementById("translation");
const translateSentence = document.getElementById("translate-sentence");
const targetWordSection = document.getElementById("target-word-section");
const targetWords = document.getElementById("target-words");
const showSolution = document.getElementById("show-solution");
const lookup = document.getElementById("lookup");
const submit = document.getElementById("submit");
const selectionSummary = document.getElementById("selection-summary");
const undo = document.getElementById("undo");
const favorite = document.getElementById("favorite");
const speakSentence = document.getElementById("speak-sentence");
const ttsStatus = document.getElementById("tts-status");
const textColor = "__TEXT_COLOR__";
const unknownColor = "__UNKNOWN_COLOR__";
const contextTranslationCache = new Map();
let contextHoverTimer = null;
let contextHoverRequest = 0;
let contextHoverNode = null;

function forceReadable(node, color) {
  node.style.setProperty("color", color, "important");
  node.style.setProperty("-webkit-text-fill-color", color, "important");
  node.style.setProperty("text-shadow", "none", "important");
}

function setup() {
  forceReadable(document.documentElement, textColor);
  forceReadable(document.body, textColor);
  forceReadable(sentence, textColor);
  forceReadable(solution, textColor);
  document.querySelectorAll(".word").forEach((span) => {
    forceReadable(span, textColor);
  });
  document.querySelectorAll(".word.target").forEach((span) => {
    span.tabIndex = 0;
    span.setAttribute("role", "button");
    span.setAttribute("aria-pressed", "false");
    span.setAttribute("aria-label", `Mark unknown: ${span.textContent}`);
    span.addEventListener("click", () => {
      toggleUnknown(span);
    });
    span.addEventListener("keydown", (event) => {
      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        event.stopPropagation();
        span.click();
      }
    });
  });
  document.querySelectorAll(".word.context").forEach((span) => {
    span.addEventListener("mouseenter", () => scheduleContextTranslation(span));
    span.addEventListener("mouseleave", () => cancelContextTranslation(span));
  });
  renderSolution();
  syncReviewControls();
}

function renderSolution() {
  const hasTranslation = Boolean(task.translation);
  translation.textContent = hasTranslation ? task.translation : "No stored sentence translation.";
  translateSentence.hidden = hasTranslation;
  renderTargetWords();
}

function renderTargetWords() {
  const words = Array.isArray(task.targetWords) ? task.targetWords : [];
  targetWords.textContent = "";
  targetWordSection.hidden = words.length === 0;
  words.forEach((item) => {
    const row = document.createElement("li");
    const details = document.createElement("span");
    const fieldList = document.createElement("div");
    const word = document.createElement("strong");
    const schedule = document.createElement("span");
    const marker = document.createElement("button");
    word.textContent = item.word || "Target word";
    details.className = "target-details";
    fieldList.className = "solution-fields";
    schedule.className = "target-schedule";
    schedule.textContent = scheduleText(item);
    details.appendChild(word);
    if (schedule.textContent) {
      details.appendChild(document.createTextNode(" "));
      details.appendChild(schedule);
    }
    renderSolutionFields(fieldList, item);
    details.appendChild(fieldList);
    marker.type = "button";
    marker.className = "mark-unknown";
    marker.dataset.cardId = item.cardId || "";
    marker.setAttribute("aria-pressed", "false");
    marker.setAttribute("aria-label", `Mark ${item.word || "target word"} as forgotten`);
    marker.addEventListener("click", () => {
      toggleUnknownForCardId(marker.dataset.cardId);
    });
    row.appendChild(details);
    row.appendChild(marker);
    targetWords.appendChild(row);
  });
  syncTargetWordButtons();
}

function renderSolutionFields(container, item) {
  const fields = Array.isArray(item.solutionFields) ? item.solutionFields : [];
  if (!fields.length) {
    const fallback = document.createElement("div");
    fallback.className = "solution-field";
    fallback.textContent = item.definition || "No configured solution fields contain content.";
    container.appendChild(fallback);
    return;
  }
  fields.forEach((field) => {
    const row = document.createElement("div");
    const label = document.createElement("span");
    const value = document.createElement("span");
    row.className = `solution-field solution-field-${field.display || "text"}`;
    label.className = "solution-field-label";
    label.textContent = `${field.label || field.field || "Field"}:`;
    value.className = "solution-field-value";
    row.appendChild(label);
    row.appendChild(value);
    if (field.display === "image") {
      renderImages(value, field.media);
    } else if (field.display === "audio") {
      renderAudio(value, field.media, Boolean(field.autoplay));
    } else {
      value.textContent = field.text || "Not available";
    }
    container.appendChild(row);
  });
}

function renderImages(container, sources) {
  const media = Array.isArray(sources) ? sources : [];
  if (!media.length) {
    container.textContent = "No image available.";
    return;
  }
  media.forEach((source) => {
    const image = document.createElement("img");
    image.src = source;
    image.alt = "";
    image.loading = "lazy";
    container.appendChild(image);
  });
}

function renderAudio(container, sources, autoplay) {
  const media = Array.isArray(sources) ? sources : [];
  if (!media.length) {
    container.textContent = "No audio available.";
    return;
  }
  media.forEach((source, index) => {
    const audio = document.createElement("button");
    audio.type = "button";
    audio.className = "media-play";
    audio.textContent = media.length > 1 ? `Play audio ${index + 1}` : "Play audio";
    audio.dataset.source = source;
    audio.addEventListener("click", () => {
      playMediaSource(source);
    });
    if (autoplay && index === 0) {
      audio.dataset.autoplay = "true";
    }
    container.appendChild(audio);
  });
}

function playMediaSource(source) {
  if (!source) {
    return;
  }
  pycmd(JSON.stringify({ action: "play_media", source }));
}

function scheduleText(item) {
  const good = item.goodInterval || "";
  const again = item.againInterval || "";
  if (good && again) {
    return `(Good: ${good} / Again: ${again})`;
  }
  if (good) {
    return `(Good: ${good})`;
  }
  if (again) {
    return `(Again: ${again})`;
  }
  return "";
}

showSolution.addEventListener("click", () => {
  revealSolution();
});

undo.addEventListener("click", () => {
  if (!undo.disabled) {
    pycmd(JSON.stringify({ action: "undo" }));
  }
});

favorite.addEventListener("click", () => {
  favorite.disabled = true;
  pycmd(JSON.stringify({ action: "toggle_favorite" }));
});

window.contextualFavoriteChanged = (saved, error) => {
  favorite.disabled = false;
  if (error) {
    favorite.title = error;
    return;
  }
  favorite.textContent = saved ? "★" : "☆";
  favorite.setAttribute("aria-pressed", saved ? "true" : "false");
  favorite.setAttribute(
    "aria-label",
    saved ? "Remove sentence from favorites" : "Save sentence to favorites"
  );
  favorite.title = saved ? "Remove sentence from favorites" : "Save sentence to favorites";
};

speakSentence.addEventListener("click", () => {
  if (speakSentence.disabled) {
    return;
  }
  speakSentence.disabled = true;
  speakSentence.textContent = "Preparing audio…";
  ttsStatus.textContent = "Uses the internet";
  pycmd(JSON.stringify({ action: "speak_sentence" }));
});

window.contextualTtsFinished = (error) => {
  speakSentence.disabled = false;
  speakSentence.textContent = "🔊 Read sentence";
  ttsStatus.textContent = error || "Playing";
  if (!error) {
    window.setTimeout(() => {
      if (ttsStatus.textContent === "Playing") {
        ttsStatus.textContent = "";
      }
    }, 1600);
  }
};

lookup.addEventListener("click", () => {
  const words = selectedUnknownTargets().map((node) => node.dataset.word).filter(Boolean);
  const unique = Array.from(new Set(words));
  if (unique.length) {
    pycmd(JSON.stringify({ action: "lookup", words: unique }));
  }
});

translateSentence.addEventListener("click", () => {
  if (translateSentence.disabled) {
    return;
  }
  translateSentence.disabled = true;
  translateSentence.textContent = "Translating…";
  pycmd(JSON.stringify({
    action: "translate_sentence",
    sentence: task.sentenceText || "",
    request_id: 0
  }));
});

function scheduleContextTranslation(span) {
  window.clearTimeout(contextHoverTimer);
  contextHoverNode = span;
  const word = (span.dataset.word || span.textContent || "").trim();
  if (!word) {
    return;
  }
  if (contextTranslationCache.has(word)) {
    showContextTranslation(span, contextTranslationCache.get(word));
    return;
  }
  const requestId = ++contextHoverRequest;
  contextHoverTimer = window.setTimeout(() => {
    if (contextHoverNode !== span) {
      return;
    }
    showContextTranslation(span, "Translating…", true);
    pycmd(JSON.stringify({
      action: "hover_translate",
      text: word,
      request_id: requestId
    }));
  }, 180);
}

function cancelContextTranslation(span) {
  if (contextHoverNode !== span) {
    return;
  }
  window.clearTimeout(contextHoverTimer);
  contextHoverNode = null;
  contextTranslationTooltip.hidden = true;
}

function showContextTranslation(span, text, loading = false) {
  contextTranslationTooltip.textContent = text;
  contextTranslationTooltip.classList.toggle("loading", loading);
  contextTranslationTooltip.hidden = false;
  const wordRect = span.getBoundingClientRect();
  const tooltipRect = contextTranslationTooltip.getBoundingClientRect();
  const left = Math.max(8, Math.min(
    window.innerWidth - tooltipRect.width - 8,
    wordRect.left + (wordRect.width - tooltipRect.width) / 2
  ));
  const below = wordRect.bottom + 9;
  const top = below + tooltipRect.height <= window.innerHeight - 8
    ? below
    : Math.max(8, wordRect.top - tooltipRect.height - 9);
  contextTranslationTooltip.style.left = `${left}px`;
  contextTranslationTooltip.style.top = `${top}px`;
}

window.contextualTranslationFinished = (kind, requestId, sourceText, translatedText, error) => {
  if (kind === "sentence") {
    translateSentence.disabled = false;
    translateSentence.textContent = error ? "Try Translation Again" : "Translate Sentence";
    if (error) {
      translation.textContent = error;
      translateSentence.hidden = false;
    } else {
      translation.textContent = translatedText;
      translateSentence.hidden = true;
    }
    return;
  }
  if (kind !== "hover" || requestId !== contextHoverRequest || !contextHoverNode) {
    return;
  }
  const currentWord = (
    contextHoverNode.dataset.word || contextHoverNode.textContent || ""
  ).trim();
  if (currentWord !== sourceText) {
    return;
  }
  const displayText = error || translatedText;
  if (!error) {
    contextTranslationCache.set(sourceText, translatedText);
  }
  showContextTranslation(contextHoverNode, displayText, false);
};

submit.addEventListener("click", () => {
  submitAnswer();
});

function toggleUnknown(span) {
  setUnknownState(span, !span.classList.contains("unknown"));
  syncReviewControls();
}

function toggleUnknownForCardId(cardId) {
  const nodes = targetNodesForCardId(cardId);
  const shouldMarkUnknown = nodes.some((node) => !node.classList.contains("unknown"));
  nodes.forEach((node) => {
    setUnknownState(node, shouldMarkUnknown);
  });
  syncReviewControls();
}

function setUnknownState(span, isUnknown) {
  span.classList.toggle("unknown", isUnknown);
  span.setAttribute("aria-pressed", isUnknown ? "true" : "false");
  if (isUnknown) {
    forceReadable(span, unknownColor);
  } else {
    forceReadable(span, textColor);
  }
}

function revealSolution() {
  if (!solution.hidden) {
    return;
  }
  solution.hidden = false;
  showSolution.hidden = true;
  submit.disabled = false;
  playAutoplayAudio();
  syncReviewControls();
  submit.focus();
}

function playAutoplayAudio() {
  const button = solution.querySelector('.media-play[data-autoplay="true"]');
  if (button) {
    playMediaSource(button.dataset.source || "");
  }
}

function submitAnswer() {
  if (submit.disabled) {
    return;
  }
  submit.disabled = true;
  const targetNodes = Array.from(document.querySelectorAll(".word.target"));
  const unknownNodes = selectedUnknownTargets();
  const unknownNodeSet = new Set(unknownNodes);
  const knownNodes = targetNodes.filter((node) => !unknownNodeSet.has(node));
  const unknown = unknownNodes
    .map((node) => node.dataset.key)
    .filter(Boolean);
  const known = knownNodes
    .map((node) => node.dataset.key)
    .filter(Boolean);
  const unknownCardIds = cardIdsForNodes(unknownNodes);
  const knownCardIds = cardIdsForNodes(knownNodes);
  const unique = Array.from(new Set(unknown));
  const uniqueKnown = Array.from(new Set(known));
  const uniqueCardIds = Array.from(new Set(unknownCardIds));
  const uniqueKnownCardIds = Array.from(new Set(knownCardIds));
  pycmd(JSON.stringify({
    action: "submit",
    unknown_keys: unique,
    known_keys: uniqueKnown,
    unknown_card_ids: uniqueCardIds,
    known_card_ids: uniqueKnownCardIds
  }));
}

function selectedUnknownTargets() {
  return Array.from(document.querySelectorAll(".word.target.unknown"));
}

function cardIdsForNodes(nodes) {
  const ids = [];
  nodes.forEach((node) => {
    cardIdsForNode(node).forEach((cardId) => {
      ids.push(cardId);
    });
  });
  return ids;
}

function cardIdsForNode(node) {
  return (node.dataset.cardIds || node.dataset.cardId || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function targetNodesForCardId(cardId) {
  const targetCardId = String(cardId || "").trim();
  if (!targetCardId) {
    return [];
  }
  return Array.from(document.querySelectorAll(".word.target")).filter((node) => {
    return cardIdsForNode(node).includes(targetCardId);
  });
}

function syncReviewControls() {
  syncLookupState();
  syncTargetWordButtons();
  syncSelectionSummary();
}

function syncTargetWordButtons() {
  document.querySelectorAll(".mark-unknown").forEach((button) => {
    const nodes = targetNodesForCardId(button.dataset.cardId);
    const isUnknown = nodes.length > 0 && nodes.every((node) => node.classList.contains("unknown"));
    button.disabled = nodes.length === 0;
    button.classList.toggle("unknown", isUnknown);
    button.setAttribute("aria-pressed", isUnknown ? "true" : "false");
    button.textContent = isUnknown ? "Marked forgotten" : "Mark forgotten";
    button.setAttribute(
      "aria-label",
      `${isUnknown ? "Mark remembered" : "Mark forgotten"}: ${button.closest("li")?.querySelector("strong")?.textContent || "target word"}`
    );
  });
}

function syncLookupState() {
  lookup.disabled = selectedUnknownTargets().length === 0;
}

function syncSelectionSummary() {
  const targets = Array.from(document.querySelectorAll(".word.target"));
  const unknownTargets = selectedUnknownTargets();
  const totalCardIds = new Set(cardIdsForNodes(targets));
  const unknownCardIds = new Set(cardIdsForNodes(unknownTargets));
  const total = totalCardIds.size || targets.length;
  const unknown = unknownCardIds.size || unknownTargets.length;
  const known = Math.max(0, total - unknown);
  if (!total) {
    selectionSummary.textContent = "No linked cards in this sentence.";
    return;
  }
  selectionSummary.textContent = `${unknown} Again · ${known} Good · Space/Enter to ${solution.hidden ? "show the solution" : "grade and continue"}`;
}

document.addEventListener("keydown", (event) => {
  if (event.repeat) {
    return;
  }
  if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "z") {
    event.preventDefault();
    pycmd(JSON.stringify({ action: "undo" }));
    return;
  }
  if (isInteractiveShortcutTarget(event.target)) {
    return;
  }
  if (event.key === " " || event.key === "Enter") {
    event.preventDefault();
    if (!solution.hidden) {
      submitAnswer();
    } else {
      revealSolution();
    }
    return;
  }
  if (/^[1-9]$/.test(event.key)) {
    const targets = Array.from(document.querySelectorAll(".word.target"));
    const target = targets[Number(event.key) - 1];
    if (target) {
      target.click();
    }
  }
});

function isInteractiveShortcutTarget(target) {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("button, input, select, textarea, [contenteditable='true'], .word.target"));
}

setup();
</script>
""".replace("__TASK__", payload_json)
        .replace("__SENTENCE__", sentence_html)
        .replace("__PROGRESS__", progress_html)
        .replace("__UNDO_DISABLED__", undo_disabled)
        .replace("__FAVORITE_PRESSED__", "true" if is_favorite else "false")
        .replace("__FAVORITE_SYMBOL__", "&#x2605;" if is_favorite else "&#x2606;")
        .replace("__TEXT_COLOR__", theme["fg"])
        .replace("__UNKNOWN_COLOR__", theme["unknown_fg"]),
        theme,
        font_size,
    )


def render_message_html(
    title: str,
    message: str,
    dark_mode: bool = False,
    font_size: int = 34,
    action_label: Optional[str] = None,
    action: Optional[str] = None,
    extra_actions: Optional[Sequence[Tuple[str, str]]] = None,
    show_refresh: bool = True,
) -> str:
    action_html = _action_button(action_label, action, primary=True)
    for label, action_name in extra_actions or ():
        action_html += "\n    " + _action_button(label, action_name)
    refresh_html = (
        '<button type="button" onclick="pycmd(JSON.stringify({ action: \'next\' }))">Refresh</button>'
        if show_refresh
        else ""
    )
    buttons_html = "\n    ".join(part for part in (refresh_html, action_html) if part)
    actions_html = (
        '<footer class="actions">\n    %s\n  </footer>' % buttons_html
        if buttons_html
        else ""
    )
    return _page(
        """
<main class="message-shell">
  <h1>%s</h1>
  <p>%s</p>
  %s
</main>
"""
        % (escape(title), escape(message), actions_html),
        _theme(dark_mode),
        font_size,
    )


def _action_button(label: Optional[str], action: Optional[str], primary: bool = False) -> str:
    if label and action:
        css_class = ' class="primary-action"' if primary else ""
        return '<button type="button"%s data-action="%s" onclick="pycmd(JSON.stringify({ action: this.dataset.action }))">%s</button>' % (
            css_class,
            escape(action, quote=True),
            escape(label),
        )
    return ""


def _target_word_payload(target_words: Sequence[Any]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for item in target_words:
        payload.append(
            {
                "cardId": getattr(item, "card_id", 0),
                "word": getattr(item, "target_word", "") or "",
                "definition": getattr(item, "definition", "") or "",
                "solutionFields": _solution_field_payload(
                    getattr(item, "solution_fields", ()) or ()
                ),
                "goodInterval": getattr(item, "good_interval", "") or "",
                "againInterval": getattr(item, "again_interval", "") or "",
            }
        )
    return payload


def _solution_field_payload(fields: Sequence[Any]) -> List[Dict[str, Any]]:
    return [
        {
            "field": getattr(item, "field", "") or "",
            "label": getattr(item, "label", "") or "",
            "display": getattr(item, "display", "text") or "text",
            "text": getattr(item, "text", "") or "",
            "media": list(getattr(item, "media", ()) or ()),
            "autoplay": bool(getattr(item, "autoplay", False)),
        }
        for item in fields
    ]


def _script_json(payload: Dict[str, Any]) -> str:
    return (
        json.dumps(payload, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _render_sentence_tokens(tokens: List[Token], theme: Dict[str, str]) -> str:
    parts: List[str] = []
    for token in tokens:
        if not token.is_word:
            parts.append(escape(token.text))
            continue
        classes = "word target" if token.is_target else "word context"
        style = (
            "color:%s !important;"
            "-webkit-text-fill-color:%s !important;"
            "text-shadow:none !important;"
        ) % (theme["fg"], theme["fg"])
        card_ids = ",".join(str(card_id) for card_id in token.card_ids)
        first_card_id = str(token.card_ids[0]) if token.card_ids else ""
        parts.append(
            '<span class="%s" data-key="%s" data-lemma="%s" data-word="%s" data-card-id="%s" data-card-ids="%s" style="%s">%s</span>'
            % (
                classes,
                escape(token.match_key or token.lemma, quote=True),
                escape(token.lemma, quote=True),
                escape(token.lookup_text or token.text, quote=True),
                escape(first_card_id, quote=True),
                escape(card_ids, quote=True),
                style,
                escape(token.text),
            )
        )
    return "".join(parts)


def _theme(dark_mode: bool) -> Dict[str, str]:
    if dark_mode:
        return {
            "scheme": "dark",
            "bg": "#1f2125",
            "fg": "#f2f4f8",
            "muted": "#c3cad4",
            "accent": "#2c7f88",
            "target": "#9ec5ff",
            "unknown_bg": "#5b2424",
            "unknown_fg": "#ffd8d8",
            "border": "#555d68",
            "button_bg": "#2a2d33",
            "disabled_fg": "#9aa4b2",
        }
    return {
        "scheme": "light",
        "bg": "#f6f7f2",
        "fg": "#1f2933",
        "muted": "#4f5b67",
        "accent": "#1f6f78",
        "target": "#0b559f",
        "unknown_bg": "#ffd7d7",
        "unknown_fg": "#7d1515",
        "border": "#a8b0b8",
        "button_bg": "#ffffff",
        "disabled_fg": "#6b7280",
    }


def _page(body: str, theme: Dict[str, str], font_size: int) -> str:
    before = """
<style>
:root {
  color-scheme: __SCHEME__;
  --bg: __BG__;
  --fg: __FG__;
  --muted: __MUTED__;
  --accent: __ACCENT__;
  --target: __TARGET__;
  --unknown-bg: __UNKNOWN_BG__;
  --unknown-fg: __UNKNOWN_FG__;
  --border: __BORDER__;
  --button-bg: __BUTTON_BG__;
  --disabled-fg: __DISABLED_FG__;
  --sentence-size: __FONT_SIZE__px;
}

html,
body {
  margin: 0;
  min-height: 100%;
  background: var(--bg) !important;
  color: var(--fg) !important;
  -webkit-text-fill-color: var(--fg) !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

[hidden] {
  display: none !important;
}

.review-shell,
.message-shell {
  box-sizing: border-box;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 28px;
  padding: 48px 56px;
}

.review-shell {
  justify-content: flex-start;
  padding-bottom: 64px;
}

.message-shell {
  justify-content: center;
}

.message-shell > p {
  white-space: pre-line;
}

.review-header,
.sentence,
.sentence-audio-controls,
.solution,
.review-shell > .actions {
  box-sizing: border-box;
  width: min(980px, 100%);
  margin-left: auto;
  margin-right: auto;
}

.review-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px 24px;
  flex-wrap: wrap;
}

.review-guidance,
.selection-summary {
  margin: 0;
  color: var(--muted) !important;
  -webkit-text-fill-color: var(--muted) !important;
  font-size: 14px;
  line-height: 1.4;
}

.selection-summary {
  font-weight: 650;
}

.session-progress {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 4;
  box-sizing: border-box;
  padding: 10px 14px 12px;
  background: linear-gradient(to bottom, transparent, var(--bg) 45%);
  pointer-events: none;
}

.progress-track {
  width: 100%;
  height: 6px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--border) 38%, transparent);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.12);
}

.progress-fill {
  position: relative;
  width: var(--review-progress);
  height: 100%;
  min-width: 0;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent), var(--target));
  box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 45%, transparent);
  transition: width 220ms ease-out;
}

.progress-fill::after {
  content: "";
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 18px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.42));
}

.sentence {
  max-width: 980px;
  color: var(--fg) !important;
  -webkit-text-fill-color: var(--fg) !important;
  font-size: var(--sentence-size);
  line-height: 1.55;
  font-weight: 520;
}

.sentence-audio-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: -18px;
}

.tts-status {
  color: var(--muted) !important;
  -webkit-text-fill-color: var(--muted) !important;
  font-size: 13px;
}

.word {
  border-radius: 6px;
  color: inherit !important;
  -webkit-text-fill-color: inherit !important;
  padding: 2px 4px;
  margin: 0 1px;
}

.word.target {
  cursor: pointer;
}

.word.context {
  cursor: help;
}

.word.target:hover,
.word.target:focus {
  background: rgba(47, 111, 115, 0.14);
  outline: none;
}

.word.target {
  color: var(--fg) !important;
  -webkit-text-fill-color: var(--fg) !important;
  box-shadow: inset 0 -3px 0 rgba(23, 78, 166, 0.28);
}

.word.unknown {
  background: var(--unknown-bg);
  color: var(--unknown-fg) !important;
  -webkit-text-fill-color: var(--unknown-fg) !important;
}

.context-translation-tooltip {
  position: fixed;
  z-index: 10;
  box-sizing: border-box;
  max-width: min(320px, calc(100vw - 16px));
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--button-bg) !important;
  color: var(--fg) !important;
  -webkit-text-fill-color: var(--fg) !important;
  box-shadow: 0 5px 18px rgba(0, 0, 0, 0.22);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  pointer-events: none;
}

.context-translation-tooltip.loading {
  color: var(--muted) !important;
  -webkit-text-fill-color: var(--muted) !important;
  font-weight: 500;
}

.solution {
  max-width: 980px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.solution-block h2 {
  margin: 0 0 6px;
  color: var(--fg) !important;
  -webkit-text-fill-color: var(--fg) !important;
  font-size: 15px;
  line-height: 1.3;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0;
}

.translation,
.target-words {
  color: var(--muted) !important;
  -webkit-text-fill-color: var(--muted) !important;
  font-size: 22px;
  line-height: 1.45;
}

.target-words {
  list-style: disc;
  margin: 0;
  padding-left: 24px;
}

.target-words li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  margin: 4px 0;
}

.target-details {
  min-width: 0;
  flex: 1 1 520px;
}

.solution-fields {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 7px;
}

.solution-field {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.solution-field-label {
  flex: 0 0 auto;
  color: var(--fg) !important;
  -webkit-text-fill-color: var(--fg) !important;
  font-size: 14px;
  font-weight: 700;
}

.solution-field-value {
  min-width: 0;
  color: var(--muted) !important;
  -webkit-text-fill-color: var(--muted) !important;
  white-space: pre-wrap;
}

.solution-field-image .solution-field-value {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.solution-field-image img {
  max-width: min(320px, 70vw);
  max-height: 240px;
  border-radius: 8px;
  object-fit: contain;
}

.media-play {
  padding: 6px 10px;
  font-size: 13px;
}

.target-words strong {
  color: var(--fg) !important;
  -webkit-text-fill-color: var(--fg) !important;
}

.target-schedule {
  color: var(--fg) !important;
  -webkit-text-fill-color: var(--fg) !important;
  font-size: 15px;
  font-weight: 700;
  white-space: nowrap;
}

.mark-unknown {
  padding: 5px 9px;
  font-size: 13px;
  line-height: 1.2;
}

.mark-unknown.unknown {
  background: var(--unknown-bg) !important;
  border-color: var(--unknown-fg);
  color: var(--unknown-fg) !important;
  -webkit-text-fill-color: var(--unknown-fg) !important;
}

.inline-action {
  margin-top: 10px;
  padding: 7px 11px;
  font-size: 13px;
}

.compact-action {
  padding: 7px 11px;
  font-size: 13px;
}

#undo {
  position: fixed;
  top: 14px;
  left: 14px;
  z-index: 5;
  width: 30px;
  height: 30px;
  padding: 0;
  border-radius: 999px;
  font-size: 17px;
  line-height: 1;
}

#favorite {
  position: fixed;
  top: 14px;
  right: 14px;
  z-index: 5;
  width: 30px;
  height: 30px;
  padding: 0;
  border-radius: 999px;
  font-size: 18px;
  line-height: 1;
}

.actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.review-shell > .actions {
  position: sticky;
  bottom: 0;
  z-index: 2;
  padding: 14px 0;
  background: var(--bg);
}

button {
  appearance: none;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--button-bg) !important;
  color: var(--fg) !important;
  -webkit-text-fill-color: var(--fg) !important;
  font-size: 15px;
  font-weight: 600;
  padding: 10px 16px;
  cursor: pointer;
}

button.primary-action {
  background: var(--accent) !important;
  border-color: var(--accent);
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
}

button:focus-visible,
.word.target:focus-visible {
  outline: 3px solid var(--target);
  outline-offset: 2px;
}

button:disabled {
  cursor: default;
  color: var(--disabled-fg) !important;
  -webkit-text-fill-color: var(--disabled-fg) !important;
  opacity: 0.72;
}

h1 {
  margin: 0;
  font-size: 28px;
}

p {
  margin: 0;
  color: var(--muted) !important;
  -webkit-text-fill-color: var(--muted) !important;
  font-size: 17px;
  line-height: 1.5;
  max-width: 780px;
}

@media (max-width: 680px) {
  .review-shell,
  .message-shell {
    gap: 20px;
    padding: 28px 22px;
  }

  .sentence {
    font-size: max(24px, calc(var(--sentence-size) * 0.82));
  }

  .actions button {
    flex: 1 1 140px;
  }
}
</style>
"""
    for key, value in {
        "__SCHEME__": theme["scheme"],
        "__BG__": theme["bg"],
        "__FG__": theme["fg"],
        "__MUTED__": theme["muted"],
        "__ACCENT__": theme["accent"],
        "__TARGET__": theme["target"],
        "__UNKNOWN_BG__": theme["unknown_bg"],
        "__UNKNOWN_FG__": theme["unknown_fg"],
        "__BORDER__": theme["border"],
        "__BUTTON_BG__": theme["button_bg"],
        "__DISABLED_FG__": theme["disabled_fg"],
        "__FONT_SIZE__": str(int(font_size)),
    }.items():
        before = before.replace(key, value)
    return before + body
