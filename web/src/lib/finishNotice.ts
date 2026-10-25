/** Tells the user a long answer finished while they were in another tab: a short chime and a desktop notification. */

const KEY = "tribos_finish_notice_v1";

export function finishNoticeEnabled(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

/** Turns the notice on or off; turning it on asks for notification permission (a user gesture is required). */
export async function setFinishNotice(on: boolean): Promise<void> {
  try {
    window.localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // the default (on) applies
  }
  if (on && typeof Notification !== "undefined" && Notification.permission === "default") {
    try {
      await Notification.requestPermission();
    } catch {
      // the chime still plays
    }
  }
}

function chime(): void {
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const notes = [880, 1318.5]; // A5 then E6: two soft notes
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const t = ctx.currentTime + i * 0.14;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.08, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.45);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.5);
    });
    window.setTimeout(() => void ctx.close(), 1200);
  } catch {
    // audio is optional
  }
}

/** Called when an answer finishes: only acts when the page is hidden and the run took a while (at least `minSeconds`). */
export function noticeFinished(title: string, body: string, seconds: number, minSeconds = 20): void {
  if (typeof document === "undefined" || !document.hidden || seconds < minSeconds || !finishNoticeEnabled()) return;
  chime();
  if (typeof Notification !== "undefined" && Notification.permission === "granted") {
    try {
      const n = new Notification(title, { body: body.slice(0, 180), icon: "/tribos/icon-192.png", tag: "tribos-answer" });
      n.onclick = () => {
        window.focus();
        n.close();
      };
    } catch {
      // the chime has played
    }
  }
}
