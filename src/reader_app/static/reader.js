(() => {
  const surface = document.getElementById("readingSurface");
  if (!surface) return;
  const prose = document.getElementById("prose");
  const bar = document.getElementById("progressBar");
  const label = document.getElementById("progressLabel");
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const bookId = surface.dataset.bookId;
  const chapterId = surface.dataset.chapterId ? Number(surface.dataset.chapterId) : null;
  const saved = Number(surface.dataset.progress || 0);
  let annotations = JSON.parse(document.getElementById("annotationData").textContent);
  let pendingSelection = null;
  let lastSent = saved;
  let timer;
  let preferenceTimer;

  const apiRequest = async (url, options) => {
    const response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "Request failed");
    }
    return response.status === 204 ? null : response.json();
  };
  const escapeHtml = (value) => value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
  const colorOptions = (selected) => ["yellow", "green", "blue", "pink"].map((color) =>
    `<option value="${color}" ${color === selected ? "selected" : ""}>${color[0].toUpperCase() + color.slice(1)}</option>`
  ).join("");
  const preferenceControls = {
    theme: document.getElementById("readerTheme"),
    font_family: document.getElementById("readerFont"),
    font_size: document.getElementById("readerFontSize"),
    line_height: document.getElementById("readerLineHeight"),
    column_width: document.getElementById("readerColumnWidth"),
  };
  const applyPreferences = (preferences) => {
    surface.classList.remove("theme-light", "theme-sepia", "theme-dark", "font-serif", "font-sans");
    surface.classList.add(`theme-${preferences.theme}`, `font-${preferences.font_family}`);
    surface.style.setProperty("--reader-font-size", `${preferences.font_size}px`);
    surface.style.setProperty("--reader-line-height", String(preferences.line_height / 100));
    document.querySelector(".reader-page").style.setProperty("--reader-width", `${preferences.column_width}px`);
  };
  const currentPreferences = () => ({
    theme: preferenceControls.theme.value,
    font_family: preferenceControls.font_family.value,
    font_size: Number(preferenceControls.font_size.value),
    line_height: Number(preferenceControls.line_height.value),
    column_width: Number(preferenceControls.column_width.value),
  });
  const initialPreferences = {
    theme: surface.dataset.theme,
    font_family: surface.dataset.fontFamily,
    font_size: Number(surface.dataset.fontSize),
    line_height: Number(surface.dataset.lineHeight),
    column_width: Number(surface.dataset.columnWidth),
  };
  Object.entries(preferenceControls).forEach(([key, control]) => {
    control.value = initialPreferences[key];
    control.addEventListener("input", () => {
      const preferences = currentPreferences();
      applyPreferences(preferences);
      clearTimeout(preferenceTimer);
      preferenceTimer = setTimeout(() => {
        apiRequest("/reader/preferences", {
          method: "POST", body: JSON.stringify(preferences),
        }).catch(() => {});
      }, 350);
    });
  });
  applyPreferences(initialPreferences);

  const textPoint = (offset) => {
    const walker = document.createTreeWalker(prose, NodeFilter.SHOW_TEXT);
    let node;
    let consumed = 0;
    while ((node = walker.nextNode())) {
      const next = consumed + node.data.length;
      if (offset <= next) return { node, offset: Math.max(0, offset - consumed) };
      consumed = next;
    }
    return null;
  };
  const applyHighlight = (annotation) => {
    const start = textPoint(annotation.start_offset);
    const end = textPoint(annotation.end_offset);
    if (!start || !end) return;
    const range = document.createRange();
    range.setStart(start.node, start.offset);
    range.setEnd(end.node, end.offset);
    const mark = document.createElement("mark");
    mark.className = `reader-highlight ${annotation.color}`;
    mark.dataset.annotationId = annotation.id;
    try {
      mark.appendChild(range.extractContents());
      range.insertNode(mark);
    } catch (_) {
      // A malformed legacy anchor should never prevent the book from opening.
    }
  };
  const renderHighlights = () => {
    prose.querySelectorAll("mark.reader-highlight").forEach((mark) => mark.replaceWith(...mark.childNodes));
    prose.normalize();
    [...annotations].sort((a, b) => b.start_offset - a.start_offset).forEach(applyHighlight);
  };
  const renderList = () => {
    const list = document.getElementById("annotationList");
    list.innerHTML = annotations.length ? annotations.map((item) => `
      <section class="annotation-item ${item.color}" data-id="${item.id}">
        <blockquote>“${escapeHtml(item.selected_text)}”</blockquote>
        <label>Color<select data-field="color">${colorOptions(item.color)}</select></label>
        <label>Note<textarea data-field="note" rows="3">${escapeHtml(item.note)}</textarea></label>
        <div class="editor-actions"><button data-action="delete">Delete</button><button data-action="update" class="primary">Save</button></div>
      </section>`).join("") : '<p class="muted">No highlights yet.</p>';
  };
  const offsetsForSelection = (selection) => {
    if (!selection.rangeCount || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    if (!prose.contains(range.commonAncestorContainer)) return null;
    const before = document.createRange();
    before.selectNodeContents(prose);
    before.setEnd(range.startContainer, range.startOffset);
    const selectedText = range.toString();
    const startOffset = before.toString().length;
    return { start_offset: startOffset, end_offset: startOffset + selectedText.length, selected_text: selectedText };
  };

  prose.addEventListener("mouseup", () => {
    pendingSelection = offsetsForSelection(window.getSelection());
    if (!pendingSelection || !pendingSelection.selected_text.trim()) return;
    document.getElementById("selectionPreview").textContent = `“${pendingSelection.selected_text.slice(0, 240)}”`;
    document.getElementById("newAnnotation").hidden = false;
    document.getElementById("selectionHint").hidden = true;
  });
  document.getElementById("cancelAnnotation").addEventListener("click", () => {
    pendingSelection = null;
    document.getElementById("newAnnotation").hidden = true;
    document.getElementById("selectionHint").hidden = false;
  });
  document.getElementById("saveAnnotation").addEventListener("click", async () => {
    if (!pendingSelection) return;
    try {
      const created = await apiRequest(`/reader/${bookId}/annotations`, {
        method: "POST",
        body: JSON.stringify({
          ...pendingSelection,
          chapter_id: chapterId,
          color: document.getElementById("newColor").value,
          note: document.getElementById("newNote").value,
        }),
      });
      annotations.push(created);
      pendingSelection = null;
      document.getElementById("newNote").value = "";
      document.getElementById("newAnnotation").hidden = true;
      document.getElementById("selectionHint").hidden = false;
      window.getSelection().removeAllRanges();
      renderHighlights();
      renderList();
    } catch (error) {
      alert(error.message);
    }
  });
  document.getElementById("saveVocabulary").addEventListener("click", async () => {
    if (!pendingSelection) return;
    const allText = prose.textContent;
    const contextStart = Math.max(0, pendingSelection.start_offset - 120);
    const contextEnd = Math.min(allText.length, pendingSelection.end_offset + 120);
    try {
      await apiRequest(`/reader/${bookId}/vocabulary`, {
        method: "POST",
        body: JSON.stringify({
          start_offset: pendingSelection.start_offset,
          end_offset: pendingSelection.end_offset,
          chapter_id: chapterId,
          term: pendingSelection.selected_text,
          language: document.getElementById("newLanguage").value,
          definition: document.getElementById("newDefinition").value,
          note: document.getElementById("newNote").value,
          context: allText.slice(contextStart, contextEnd).trim(),
        }),
      });
      pendingSelection = null;
      document.getElementById("newNote").value = "";
      document.getElementById("newDefinition").value = "";
      document.getElementById("newAnnotation").hidden = true;
      document.getElementById("selectionHint").hidden = false;
      window.getSelection().removeAllRanges();
      document.getElementById("selectionHint").textContent = "Vocabulary saved. Select more text to continue.";
    } catch (error) {
      alert(error.message);
    }
  });
  document.getElementById("annotationList").addEventListener("click", async (event) => {
    const action = event.target.dataset.action;
    if (!action) return;
    const item = event.target.closest(".annotation-item");
    const id = Number(item.dataset.id);
    try {
      if (action === "delete") {
        await apiRequest(`/reader/${bookId}/annotations/${id}`, { method: "DELETE" });
        annotations = annotations.filter((annotation) => annotation.id !== id);
      } else {
        const updated = await apiRequest(`/reader/${bookId}/annotations/${id}`, {
          method: "PATCH",
          body: JSON.stringify({
            note: item.querySelector('[data-field="note"]').value,
            color: item.querySelector('[data-field="color"]').value,
          }),
        });
        annotations = annotations.map((annotation) => annotation.id === id ? updated : annotation);
      }
      renderHighlights();
      renderList();
    } catch (error) {
      alert(error.message);
    }
  });

  const setDisplay = (progress) => {
    const percent = Math.round(progress * 100);
    bar.style.width = `${percent}%`;
    label.textContent = `${percent}% read`;
  };
  const currentProgress = () => {
    const maximum = document.documentElement.scrollHeight - window.innerHeight;
    return maximum > 0 ? Math.max(0, Math.min(1, window.scrollY / maximum)) : 1;
  };
  const saveProgress = (progress) => {
    if (Math.abs(progress - lastSent) < 0.002) return;
    lastSent = progress;
    apiRequest(`/reader/${bookId}/progress`, {
      method: "POST", body: JSON.stringify({ progress, chapter_id: chapterId }), keepalive: true,
    }).catch(() => {});
  };
  renderHighlights();
  renderList();
  setDisplay(saved);
  requestAnimationFrame(() => {
    if (surface.dataset.jumpOffset !== undefined) {
      const target = textPoint(Number(surface.dataset.jumpOffset));
      const element = target && target.node.parentElement;
      if (element) {
        element.scrollIntoView({ block: "center" });
        element.classList.add("source-target");
      }
    } else {
      window.scrollTo(0, saved * (document.documentElement.scrollHeight - window.innerHeight));
    }
  });
  window.addEventListener("scroll", () => {
    const progress = currentProgress();
    setDisplay(progress);
    clearTimeout(timer);
    timer = setTimeout(() => saveProgress(progress), 400);
  }, { passive: true });
  window.addEventListener("pagehide", () => saveProgress(currentProgress()));
})();
