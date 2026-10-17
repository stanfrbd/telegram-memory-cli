"use strict";

// The API remains the security boundary. This gate avoids showing a workspace
// that cannot load, and restores an explicitly remembered credential on reload.
export function createAuthController({ loadWorkspace, notice }) {
  const $ = (id) => document.getElementById(id);
  const storageKey = "tgmem-api-token";
  let token = "",
    authorized = false,
    canGoBack = false;
  try {
    token = localStorage.getItem(storageKey) || "";
  } catch {
    /* Storage may be disabled. */
  }

  function message(text, error = false) {
    $("auth-message").textContent = text;
    $("auth-message").className = error ? "auth-message error" : "auth-message";
  }
  function gate(
    text = "Enter the API token configured on your Telegram Memory server.",
  ) {
    $("workspace").hidden = true;
    $("auth-gate").hidden = false;
    $("auth-form").hidden = false;
    $("auth-submit").disabled = false;
    $("auth-forget").hidden = !token;
    $("auth-back").hidden = !canGoBack;
    message(text);
  }
  function forget() {
    token = "";
    authorized = false;
    canGoBack = false;
    try {
      localStorage.removeItem(storageKey);
    } catch {
      /* Memory is still cleared. */
    }
    $("auth-token").value = "";
    gate("Saved API token cleared. Enter a token to reconnect.");
  }
  async function verify(candidate) {
    const response = await fetch("/api/status", {
      headers: candidate ? { Authorization: `Bearer ${candidate}` } : {},
    });
    if (!response.ok) {
      const error = Error(
        response.status === 401
          ? "Invalid API token. Please try again."
          : `Server returned HTTP ${response.status}.`,
      );
      error.status = response.status;
      throw error;
    }
  }
  async function unlock(candidate, remember) {
    await verify(candidate);
    token = candidate;
    authorized = true;
    canGoBack = false;
    let persisted = true;
    if (remember && token) {
      try {
        localStorage.setItem(storageKey, token);
      } catch {
        persisted = false;
      }
    }
    $("auth-token").value = "";
    $("auth-gate").hidden = true;
    $("workspace").hidden = false;
    await loadWorkspace();
    if (!persisted)
      notice(
        "Connected. Browser storage is unavailable; the token is kept for this page only.",
      );
  }
  $("auth-form").onsubmit = async (event) => {
    event.preventDefault();
    $("auth-submit").disabled = true;
    message("Checking API token…");
    try {
      await unlock($("auth-token").value.trim(), true);
    } catch (error) {
      message(error.message, true);
    } finally {
      $("auth-submit").disabled = false;
    }
  };
  $("auth-forget").onclick = forget;
  $("auth-back").onclick = () => {
    authorized = true;
    canGoBack = false;
    $("auth-gate").hidden = true;
    $("workspace").hidden = false;
  };
  $("auth").onclick = () => {
    canGoBack = authorized;
    authorized = false;
    gate("Update your remembered API token, or forget it on this browser.");
    $("auth-token").focus();
  };

  return {
    get token() {
      return token;
    },
    get authorized() {
      return authorized;
    },
    lock() {
      forget();
      message(
        "The server rejected your API token. Enter the current token to reconnect.",
        true,
      );
    },
    async start() {
      $("workspace").hidden = true;
      $("auth-gate").hidden = false;
      $("auth-form").hidden = true;
      message("Checking server access…");
      try {
        const response = await fetch("/api/auth");
        if (!response.ok)
          throw Error(`Cannot check server access (HTTP ${response.status}).`);
        const settings = await response.json();
        if (!settings.token_required) {
          await unlock(token, false);
          return;
        }
        if (token) {
          try {
            await unlock(token, false);
            return;
          } catch (error) {
            if (error.status === 401) {
              forget();
              gate(
                "Your saved API token is no longer valid. Enter the current token.",
              );
              return;
            }
            throw error;
          }
        }
        gate();
      } catch (error) {
        gate();
        message(error.message, true);
      }
    },
  };
}
