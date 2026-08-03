(() => {
  "use strict";

  const authApiBase =
    window.location.protocol === "file:"
      ? "http://127.0.0.1:5000"
      : window.location.origin;

  let authClient = null;
  let authEnabled = false;
  let exchangeToken = "";
  let exchangePromise = null;

  function element(id) {
    return document.getElementById(id);
  }

  function authApiUrl(path) {
    return `${authApiBase}${path}`;
  }

  function setAuthStatus(message, isError = false) {
    const status = element("authStatus");
    if (!status) return;
    status.textContent = message;
    status.className = `mt-4 min-h-5 text-sm ${
      isError ? "text-red-600" : "text-slate-600"
    }`;
  }

  function setSubmitting(isSubmitting) {
    const button = element("authSubmitBtn");
    if (!button) return;
    button.disabled = isSubmitting;
    button.textContent = isSubmitting ? "กำลังเข้าสู่ระบบ..." : "เข้าสู่ระบบ";
  }

  function showLogin(message = "กรุณาเข้าสู่ระบบเพื่อใช้งาน") {
    element("authGate")?.classList.remove("hidden");
    element("appHeader")?.classList.add("hidden");
    element("appContent")?.classList.add("hidden");
    setAuthStatus(message);
  }

  function showApplication(user = null) {
    element("authGate")?.classList.add("hidden");
    element("appHeader")?.classList.remove("hidden");
    element("appContent")?.classList.remove("hidden");
    const email = element("authUserEmail");
    if (email) {
      email.textContent = user?.email || (authEnabled ? "ผู้ใช้งาน" : "โหมดภายในเครื่อง");
      email.title = email.textContent;
    }
  }

  async function parseResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) return {};
    return response.json();
  }

  async function exchangeBackendSession(accessToken) {
    if (exchangePromise && exchangeToken === accessToken) {
      return exchangePromise;
    }

    exchangeToken = accessToken;
    exchangePromise = (async () => {
      const response = await fetch(authApiUrl("/api/auth/session"), {
        method: "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
        credentials: "include",
      });
      const payload = await parseResponse(response);
      if (!response.ok || !payload.ok) {
        throw new Error("Backend session exchange failed");
      }
      return payload.user || null;
    })();

    try {
      return await exchangePromise;
    } finally {
      exchangePromise = null;
    }
  }

  async function clearBackendSession() {
    try {
      await fetch(authApiUrl("/api/auth/logout"), {
        method: "POST",
        credentials: "include",
      });
    } catch (error) {
      console.warn("Unable to clear backend session", error);
    }
  }

  async function applySession(supabaseSession) {
    if (!authEnabled) {
      showApplication();
      return;
    }
    if (!supabaseSession?.access_token) {
      await clearBackendSession();
      showLogin();
      return;
    }

    try {
      setAuthStatus("กำลังยืนยันสิทธิ์...");
      const user = await exchangeBackendSession(supabaseSession.access_token);
      showApplication(user || supabaseSession.user);
    } catch (error) {
      console.error("Authentication session error", error);
      await authClient?.auth.signOut({ scope: "local" });
      await clearBackendSession();
      showLogin("ไม่สามารถยืนยันสิทธิ์กับเซิร์ฟเวอร์ได้");
    }
  }

  async function handleLogin(event) {
    event.preventDefault();
    if (!authClient) return;

    const email = element("authEmail")?.value.trim() || "";
    const passwordInput = element("authPassword");
    const password = passwordInput?.value || "";
    setSubmitting(true);
    setAuthStatus("กำลังตรวจสอบบัญชี...");

    try {
      const { data, error } = await authClient.auth.signInWithPassword({
        email,
        password,
      });
      if (error || !data.session) {
        throw new Error("Invalid login");
      }
      if (passwordInput) passwordInput.value = "";
      await applySession(data.session);
    } catch (error) {
      console.warn("Login failed", error);
      setAuthStatus("อีเมลหรือรหัสผ่านไม่ถูกต้อง", true);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleLogout() {
    const button = element("authSignOutBtn");
    if (button) button.disabled = true;
    await clearBackendSession();
    if (authClient) {
      await authClient.auth.signOut({ scope: "local" });
    }
    window.location.reload();
  }

  async function initializeAuth() {
    element("authLoginForm")?.addEventListener("submit", handleLogin);
    element("authSignOutBtn")?.addEventListener("click", handleLogout);

    if (window.location.protocol === "file:") {
      setAuthStatus("กรุณาเปิดเว็บไซต์ผ่าน Flask server", true);
      return;
    }

    try {
      const configResponse = await fetch(authApiUrl("/api/config"), {
        credentials: "include",
        cache: "no-store",
      });
      const config = await parseResponse(configResponse);
      if (!configResponse.ok || !config.auth) {
        throw new Error("Invalid public config");
      }

      authEnabled = Boolean(config.auth.enabled);
      if (!authEnabled) {
        showApplication();
        return;
      }
      if (!window.supabase?.createClient) {
        throw new Error("Supabase client did not load");
      }
      if (!config.auth.supabase_url || !config.auth.publishable_key) {
        throw new Error("Supabase Auth config is incomplete");
      }

      authClient = window.supabase.createClient(
        config.auth.supabase_url,
        config.auth.publishable_key,
        {
          auth: {
            persistSession: true,
            autoRefreshToken: true,
            detectSessionInUrl: true,
          },
        },
      );

      authClient.auth.onAuthStateChange((_event, nextSession) => {
        window.setTimeout(() => {
          void applySession(nextSession);
        }, 0);
      });

      const { data, error } = await authClient.auth.getSession();
      if (error) throw error;
      await applySession(data.session);
    } catch (error) {
      console.error("Unable to initialize authentication", error);
      setAuthStatus("โหลดระบบเข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่", true);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    void initializeAuth();
  });
})();
