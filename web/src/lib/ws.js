/**
 * Live updates.
 *
 * Four events, listed in api/ws.py. Everything here is best-effort by design:
 * a missed frame must never be the reason a red flag goes unseen, so every
 * handler in this app re-fetches from REST rather than trusting the payload
 * as the source of truth. The socket is a hint that something changed.
 */

import { useEffect, useRef } from "react";
import { getSession } from "./api";

export function useLiveUpdates(onEvent) {
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    const token = getSession()?.access_token;
    if (!token) return;

    let socket;
    let retry;
    let closed = false;
    let attempt = 0;

    const open = () => {
      if (closed) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(
        `${proto}://${location.host}/ws?token=${encodeURIComponent(
          getSession()?.access_token || ""
        )}`
      );

      socket.onmessage = (ev) => {
        try {
          const { event, payload } = JSON.parse(ev.data);
          handler.current?.(event, payload);
        } catch {
          /* ignore anything that is not our envelope */
        }
      };

      socket.onopen = () => {
        attempt = 0;
      };

      socket.onclose = () => {
        if (closed) return;
        // Backoff caps at 15s. A ward full of tablets reconnecting after a
        // router blip must not become a self-inflicted denial of service.
        attempt = Math.min(attempt + 1, 5);
        retry = setTimeout(open, Math.min(1000 * 2 ** attempt, 15000));
      };
    };

    open();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, []);
}
