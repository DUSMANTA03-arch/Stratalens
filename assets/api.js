let refreshing;
export async function api(path, options = {}, retry = true) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (
    response.status === 401 &&
    retry &&
    !["/api/auth/login", "/api/auth/refresh", "/api/auth/logout"].includes(
      path,
    ) &&
    !path.includes("/sample")
  ) {
    refreshing ||= fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
    }).finally(() => {
      refreshing = null;
    });
    if ((await refreshing).ok) return api(path, options, false);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(
      typeof body.detail === "string"
        ? body.detail
        : Array.isArray(body.detail)
          ? body.detail.map((e) => e.msg).join("; ")
          : `Request failed (${response.status}).`,
    );
    error.status = response.status;
    throw error;
  }
  if (response.headers.get("content-type")?.includes("application/pdf"))
    return response.blob();
  return response.json();
}
export const post = (path, data) =>
  api(path, {
    method: "POST",
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
  });
export function notice(message) {
  const node = document.querySelector("#notice");
  node.textContent = message;
  node.classList.toggle("hidden", !message);
  if (message) node.scrollIntoView({ block: "nearest" });
}
export function action(fn) {
  return async (event) => {
    const b = event?.currentTarget;
    if (b?.tagName === "BUTTON") b.disabled = true;
    try {
      notice("");
      await fn(event);
    } catch (e) {
      notice(e.message);
    } finally {
      if (b?.tagName === "BUTTON") b.disabled = false;
    }
  };
}
