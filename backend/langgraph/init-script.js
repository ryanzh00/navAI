(() => {
    // proof it's running
    window.__NAVAI_INIT_SCRIPT__ = "ran";
  
    const mark = () => {
      try {
        if (document.documentElement) {
          document.documentElement.setAttribute("data-navai-init", "1");
        }
      } catch {}
  
      try {
        // localStorage can throw on opaque origins / special pages
        localStorage.setItem("navai_spawned", "true");
      } catch {}
    };
  
    // Try immediately (might work on some pages)
    mark();
  
    // Ensure it runs once DOM exists
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", mark, { once: true });
    } else {
      mark();
    }
  
    // Extra safety: next tick (covers odd timing cases)
    setTimeout(mark, 0);
  })();
  