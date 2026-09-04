/**
 * The single place this app talks to the server.
 *
 * Two properties matter here and both are security properties, not conveniences:
 *
 *   1. The access token lives for 15 minutes. When it expires this module
 *      refreshes ONCE and replays the original request. Concurrent 401s share
 *      the same in-flight refresh, so a dashboard that fires five requests at
 *      once does not burn five refresh tokens and rotate itself out of a session.
 *
 *   2. A 403 is never retried. It means consent is absent or revoked, and the
 *      correct behaviour is to show the user that they cannot see this - not
 *      to try again with a fresher token, which would work exactly as often.
 */

const BASE = "/api";
const KEY = "aira.session";

let session = load();
let refreshing = null;
const listeners = new Set();

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}

function save(next) {
  session = next;
  try {
    if (next) localStorage.setItem(KEY, JSON.stringify(next));
    else localStorage.removeItem(KEY);
  } catch {
    /* private-mode browsers: the app still works, it just forgets on reload */
  }
  listeners.forEach((fn) => fn(session));
}

export function getSession() {
  return session;
}

export function onSession(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

async function raw(path, { method = "GET", body, token, raw: isRaw } = {}) {
  // A FormData body must be handed to fetch untouched: the browser generates
  // the multipart boundary and sets Content-Type itself, and setting it by
  // hand produces a request the server cannot parse.
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const res = await fetch(BASE + path, {
    method,
    headers: {
      ...(body && !isForm ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: isForm ? body : body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return null;

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    throw new ApiError(
      res.status,
      typeof detail === "string" ? detail : detail?.[0]?.msg || res.statusText
    );
  }
  return data;
}

async function refresh() {
  if (!session?.refresh_token) throw new ApiError(401, "session expired");
  if (!refreshing) {
    refreshing = raw("/auth/refresh", {
      method: "POST",
      body: { refresh_token: session.refresh_token },
    })
      .then((next) => {
        save({ ...session, ...next });
        return next;
      })
      .catch((err) => {
        save(null);
        throw err;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

export async function api(path, opts = {}) {
  const token = session?.access_token;
  try {
    return await raw(path, { ...opts, token });
  } catch (err) {
    if (err.status !== 401 || !session?.refresh_token) throw err;
    const next = await refresh();
    return raw(path, { ...opts, token: next.access_token });
  }
}

export const get = (p) => api(p);
export const post = (p, body) => api(p, { method: "POST", body });

export async function login(identifier, password) {
  const next = await raw("/auth/login", {
    method: "POST",
    body: { identifier, password },
  });
  save(next);
  return next;
}

export async function signupPatient(body) {
  const next = await raw("/auth/signup/patient", { method: "POST", body });
  save(next);
  return next;
}

export async function signupDoctor(body) {
  const next = await raw("/auth/signup/doctor", { method: "POST", body });
  save(next);
  return next;
}

export async function logout() {
  try {
    // The server revokes every refresh token this user holds, not just this
    // browser's - logging out on a shared phone must end the session on it.
    if (session?.access_token) await api("/auth/logout", { method: "POST" });
  } catch {
    /* the server may already have revoked it; the local session goes either way */
  }
  save(null);
}
