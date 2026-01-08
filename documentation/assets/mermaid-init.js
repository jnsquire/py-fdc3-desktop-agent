(() => {
  // Render Mermaid diagrams from elements with class="mermaid".
  // This is intentionally minimal to avoid coupling to a specific theme.
  const init = () => {
    if (!window.mermaid) return;
    window.mermaid.initialize({ startOnLoad: true });

    const ensureLightbox = () => {
      let overlay = document.querySelector(".mermaid-lightbox");
      if (overlay) return overlay;

      overlay = document.createElement("div");
      overlay.className = "mermaid-lightbox";
      overlay.setAttribute("role", "dialog");
      overlay.setAttribute("aria-modal", "true");
      overlay.setAttribute("aria-label", "Mermaid diagram viewer");

      overlay.innerHTML = `
        <div class="mermaid-lightbox__dialog" tabindex="-1">
          <div class="mermaid-lightbox__hint">ESC or click outside to close</div>
          <div class="mermaid-lightbox__content"></div>
        </div>
      `;

      const dialog = overlay.querySelector(".mermaid-lightbox__dialog");
      const content = overlay.querySelector(".mermaid-lightbox__content");

      const close = () => {
        overlay.classList.remove("is-open");
        document.body.classList.remove("mermaid-lightbox-open");
        content.replaceChildren();
      };

      overlay.addEventListener("click", (event) => {
        // Close when clicking the shaded backdrop.
        if (event.target === overlay) close();
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && overlay.classList.contains("is-open")) {
          close();
        }
      });

      // Stop clicks inside the dialog from bubbling to the backdrop.
      dialog.addEventListener("click", (event) => event.stopPropagation());

      document.body.appendChild(overlay);
      return overlay;
    };

    const openLightboxFor = (sourceMermaidEl) => {
      const svg = sourceMermaidEl.querySelector("svg");
      if (!svg) return;

      const overlay = ensureLightbox();
      const dialog = overlay.querySelector(".mermaid-lightbox__dialog");
      const content = overlay.querySelector(".mermaid-lightbox__content");

      // Clone the rendered SVG so we don't disturb the page layout.
      const clone = svg.cloneNode(true);
      // Ensure it can exceed the dialog width and be scrollable.
      clone.style.maxWidth = "none";
      clone.style.width = "max-content";

      content.replaceChildren(clone);
      document.body.classList.add("mermaid-lightbox-open");
      overlay.classList.add("is-open");

      // Focus for keyboard users.
      dialog.focus();
      dialog.scrollTop = 0;
      dialog.scrollLeft = 0;
    };

    const attachExpandHandlers = () => {
      for (const el of document.querySelectorAll(".mermaid")) {
        if (el.dataset.mermaidExpandable === "1") continue;
        el.dataset.mermaidExpandable = "1";
        el.tabIndex = 0;
        el.setAttribute(
          "aria-label",
          "Mermaid diagram. Click to open viewer.",
        );

        el.addEventListener("click", () => openLightboxFor(el));
        el.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openLightboxFor(el);
          }
        });
      }
    };

    // Mermaid renders asynchronously; attach handlers now and once more shortly
    // after, so the rendered SVG is already in place.
    attachExpandHandlers();
    window.setTimeout(attachExpandHandlers, 0);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
