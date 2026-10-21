(() => {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js").catch(() => {});
    });
  }

  let installPrompt = null;
  const isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
  const isIOS = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  if (isStandalone) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "chamalink-install-button";
  button.textContent = "Install ChamaLink";
  button.setAttribute("aria-label", "Install ChamaLink on this device");
  Object.assign(button.style, {
    position: "fixed", right: "16px", bottom: "calc(16px + env(safe-area-inset-bottom))",
    zIndex: "9999", border: "0", borderRadius: "999px", padding: "12px 18px",
    background: "#0F5B3A", color: "#fff", font: "600 14px system-ui, sans-serif",
    boxShadow: "0 8px 24px #092d1b40", cursor: "pointer", display: "none"
  });
  document.body.appendChild(button);

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    button.style.display = "block";
  });

  if (isIOS) {
    button.style.display = "block";
    button.addEventListener("click", () => window.alert("To add ChamaLink to your phone, tap Share, then choose Add to Home Screen."));
  } else {
    button.addEventListener("click", async () => {
      if (!installPrompt) return;
      installPrompt.prompt();
      await installPrompt.userChoice;
      installPrompt = null;
      button.style.display = "none";
    });
  }

  window.addEventListener("appinstalled", () => { button.style.display = "none"; });
})();
