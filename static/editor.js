'use strict';

const richTags = new Set(['P', 'DIV', 'BR', 'B', 'STRONG', 'I', 'EM', 'U', 'S', 'STRIKE', 'UL', 'OL', 'LI', 'BLOCKQUOTE', 'A']);
const omittedRichTags = new Set(['SCRIPT', 'STYLE', 'TEMPLATE', 'IFRAME', 'OBJECT', 'SVG', 'MATH']);
let draftSelection;

function safeEditorLink(value) {
  try {
    const url = new URL(value);
    if (['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password) {
      return url.href;
    }
  } catch {
    // A link must be an absolute web address.
  }
  return '';
}

function cleanEditorHTML(markup) {
  const source = document.createElement('template');
  source.innerHTML = markup;
  const clean = document.createElement('div');

  function copy(node, target) {
    if (node.nodeType === Node.TEXT_NODE) {
      target.append(document.createTextNode(node.textContent));
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE || omittedRichTags.has(node.tagName) ||
        node.namespaceURI !== 'http://www.w3.org/1999/xhtml') return;
    if (richTags.has(node.tagName)) {
      const element = document.createElement(node.tagName.toLowerCase());
      if (node.tagName === 'A') {
        const href = safeEditorLink(node.getAttribute('href'));
        if (href) element.setAttribute('href', href);
      }
      target.append(element);
      target = element;
    }
    for (const child of node.childNodes) copy(child, target);
  }

  for (const node of source.content.childNodes) copy(node, clean);
  return clean.innerHTML;
}

function richEditor(id, draft, editable) {
  const tools = [
    ['bold', 'Fett', '<b>F</b>'],
    ['italic', 'Kursiv', '<i>K</i>'],
    ['underline', 'Unterstrichen', '<u>U</u>'],
    ['insertUnorderedList', 'Aufzählung', '• Liste'],
    ['insertOrderedList', 'Nummerierte Liste', '1. Liste'],
    ['link', 'Link einfügen', '↗ Link'],
    ['removeFormat', 'Formatierung entfernen', 'Format löschen']
  ];
  const toolbar = editable ? `<div class="rich-toolbar" role="group" aria-label="Textformatierung">${tools.map(([action, label, text]) =>
    `<button type="button" data-format="${action}" aria-label="${label}" title="${label}">${text}</button>`).join('')}</div>` : '';
  const content = draft.html ? cleanEditorHTML(draft.html) : esc(draft.text).replace(/\r?\n/g, '<br>');
  return `<div class="rich-compose">${toolbar}<div class="draft-editor" id="draft-editor"
    contenteditable="${editable}" role="textbox" aria-multiline="true" aria-label="Antwortentwurf"
    data-placeholder="Schreibe deine Antwort …" data-id="${esc(id)}" data-revision="${esc(draft.revision)}" spellcheck="true">${content}</div></div>`;
}

function focusDraftEditor(editor) {
  editor.focus();
  const selection = getSelection();
  if (draftSelection && editor.contains(draftSelection.commonAncestorContainer)) {
    selection.removeAllRanges();
    selection.addRange(draftSelection);
  }
}

function applyDraftFormat(editor, command) {
  focusDraftEditor(editor);
  document.execCommand('styleWithCSS', false, false);
  if (command !== 'link') {
    document.execCommand(command, false, null);
    return true;
  }
  const input = prompt('Link-Adresse eingeben (https://…)');
  if (input === null) return false;
  const link = safeEditorLink(input.trim());
  if (!link) {
    toast('Bitte gib eine gültige Webadresse ein.', true);
    return false;
  }
  focusDraftEditor(editor);
  if (getSelection().isCollapsed) {
    document.execCommand('insertHTML', false, `<a href="${esc(link)}">${esc(link)}</a>`);
  } else {
    document.execCommand('createLink', false, link);
  }
  return true;
}

document.addEventListener('selectionchange', () => {
  const editor = document.getElementById('draft-editor');
  const selection = getSelection();
  if (editor && selection.rangeCount && editor.contains(selection.anchorNode) && editor.contains(selection.focusNode)) {
    draftSelection = selection.getRangeAt(0).cloneRange();
  }
});

document.addEventListener('mousedown', event => {
  if (event.target.closest('[data-format]')) event.preventDefault();
});

document.addEventListener('paste', event => {
  const editor = event.target.closest('#draft-editor[contenteditable="true"]');
  if (!editor) return;
  event.preventDefault();
  const html = event.clipboardData?.getData('text/html');
  const plain = event.clipboardData?.getData('text/plain') || '';
  if (html && html.length <= 400000) {
    const cleaned = cleanEditorHTML(html);
    if (cleaned) {
      document.execCommand('insertHTML', false, cleaned);
      return;
    }
  }
  document.execCommand('insertText', false, plain);
});

document.addEventListener('drop', event => {
  if (event.target.closest('#draft-editor')) event.preventDefault();
});
