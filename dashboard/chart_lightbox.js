(function () {
  var doc = window.parent && window.parent.document ? window.parent.document : document;
  var FLAG = "agenticChartLightbox";
  var OVERLAY_ID = "agentic-chart-lightbox";

  function el(tag, className) {
    var node = doc.createElement(tag);
    if (className) node.className = className;
    return node;
  }

  function captionFor(img) {
    var title = (img.getAttribute("data-title") || img.getAttribute("alt") || "").trim();
    if (title && title !== "0") return title;
    var figure = img.closest("figure");
    if (figure) {
      var cap = figure.querySelector("figcaption");
      if (cap && cap.textContent) return cap.textContent.trim();
    }
    var root = img.closest('[data-testid="stImage"]');
    if (root) {
      var stCap = root.querySelector('[data-testid="stImageCaption"]');
      if (stCap && stCap.textContent) {
        var text = stCap.textContent.trim();
        if (text) return text;
      }
    }
    return "图表";
  }

  function findChartImg(target, ev) {
    var path = ev && ev.composedPath ? ev.composedPath() : [];
    if (!path.length && target) path = [target];
    for (var i = 0; i < path.length; i++) {
      var node = path[i];
      if (!node || !node.querySelector) continue;
      if (node.tagName === "IMG" && node.classList && node.classList.contains("agentic-viz-chart")) {
        return node;
      }
      if (node.classList && node.classList.contains("agentic-viz-figure")) {
        var own = node.querySelector("img.agentic-viz-chart");
        if (own) return own;
      }
      var testid = node.getAttribute && node.getAttribute("data-testid");
      if (testid === "stImage" || testid === "stImageContainer") {
        var fromHost = node.querySelector("img");
        if (fromHost) return fromHost;
      }
      var images = node.querySelectorAll('[data-testid="stImage"] img');
      if (images.length === 1) return images[0];
      if (images.length > 1) return null;
    }
    return null;
  }

  function sanitizeFilename(name) {
    var cleaned = String(name || "chart")
      .replace(/[\\/:*?"<>|]+/g, "_")
      .replace(/\s+/g, "_")
      .replace(/^\.+/, "")
      .slice(0, 80);
    var stem = cleaned || "chart";
    return stem.toLowerCase().endsWith(".png") ? stem : stem + ".png";
  }

  async function downloadImage(src, filename) {
    var a = el("a");
    a.setAttribute("download", filename);
    try {
      var res = await fetch(src);
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      a.href = url;
      doc.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (_err) {
      a.href = src;
      a.target = "_blank";
      a.rel = "noopener";
      doc.body.appendChild(a);
      a.click();
      a.remove();
    }
  }

  function closeLightbox() {
    var overlay = doc.getElementById(OVERLAY_ID);
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    var large = overlay.querySelector(".agentic-lightbox-img");
    if (large) large.removeAttribute("src");
    doc.body.classList.remove("agentic-lightbox-open");
  }

  function openLightbox(img) {
    var overlay = ensureOverlay();
    var title = captionFor(img);
    overlay.dataset.filename = sanitizeFilename(title);
    overlay.querySelector(".agentic-lightbox-title").textContent = title;
    var large = overlay.querySelector(".agentic-lightbox-img");
    large.src = img.currentSrc || img.src;
    large.alt = title;
    overlay.hidden = false;
    doc.body.classList.add("agentic-lightbox-open");
    overlay.querySelector(".agentic-lightbox-close").focus();
  }

  function ensureOverlay() {
    var overlay = doc.getElementById(OVERLAY_ID);
    if (overlay && overlay.querySelector(".agentic-lightbox-stage")) return overlay;
    if (overlay) overlay.remove();

    overlay = el("div", "agentic-lightbox");
    overlay.id = OVERLAY_ID;
    overlay.hidden = true;

    var dialog = el("div", "agentic-lightbox-dialog");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", "图表预览");

    var toolbar = el("div", "agentic-lightbox-toolbar");
    var title = el("p", "agentic-lightbox-title");
    var actions = el("div", "agentic-lightbox-actions");

    var downloadBtn = el("button", "agentic-lightbox-download");
    downloadBtn.type = "button";
    downloadBtn.textContent = "下载 PNG";

    var closeBtn = el("button", "agentic-lightbox-close");
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "关闭");
    closeBtn.textContent = "关闭";

    var large = el("img", "agentic-lightbox-img");
    large.alt = "";
    var stage = el("div", "agentic-lightbox-stage");
    stage.appendChild(large);

    actions.appendChild(downloadBtn);
    actions.appendChild(closeBtn);
    toolbar.appendChild(title);
    toolbar.appendChild(actions);
    dialog.appendChild(toolbar);
    dialog.appendChild(stage);
    overlay.appendChild(dialog);
    doc.body.appendChild(overlay);

    overlay.addEventListener("click", function (ev) {
      if (ev.target === overlay) closeLightbox();
    });
    closeBtn.addEventListener("click", closeLightbox);
    downloadBtn.addEventListener("click", function () {
      var src = large.currentSrc || large.src;
      if (!src) return;
      downloadImage(src, overlay.dataset.filename || "chart.png");
    });
    return overlay;
  }

  function onDocClick(ev) {
    var overlay = doc.getElementById(OVERLAY_ID);
    if (overlay && !overlay.hidden) return;
    var img = findChartImg(ev.target, ev);
    if (!img) return;
    ev.preventDefault();
    ev.stopPropagation();
    openLightbox(img);
  }

  try {
    ensureOverlay();
    if (!doc.documentElement.dataset[FLAG]) {
      doc.documentElement.dataset[FLAG] = "1";
      doc.addEventListener("click", onDocClick, true);
      doc.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") closeLightbox();
      });
    }
  } catch (_err) {}
})();
