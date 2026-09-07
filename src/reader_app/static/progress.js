/* Persist only reading positions, scoped by account and immutable book storage ID. */
((root) => {
  class ProgressQueue {
    constructor({ key, storage, send, status, schedule = (fn, ms) => setTimeout(fn, ms), cancel = id => clearTimeout(id) }) {
      Object.assign(this, { key, storage, send, status, schedule, cancel });
      this.pending = this.read();
      this.saving = false;
    }
    read() {
      try {
        const value = JSON.parse(this.storage.getItem(this.key));
        if (value && Number.isFinite(value.progress) && value.progress >= 0 && value.progress <= 1
            && (value.chapter_id === null || Number.isInteger(value.chapter_id))
            && (value.chapter === null || Number.isInteger(value.chapter))
            && typeof value.token === "string") return value;
      } catch (_) { /* Storage may be unavailable in a restricted browser. */ }
      return null;
    }
    update(progress, chapter_id, chapter) {
      const value = { progress, chapter_id, chapter, token: `${Date.now()}-${Math.random()}` };
      this.pending = value;
      try {
        this.storage.setItem(this.key, JSON.stringify(value));
        this.status("Position saved on this device; waiting to sync");
      } catch (_) {
        this.status("Device storage unavailable; keep this page open until synced");
      }
    }
    async flush() {
      if (this.saving || !this.pending) return;
      this.cancel(this.timer);
      const value = this.pending;
      this.saving = true;
      try {
        await this.send(value);
        if (this.pending.token === value.token) {
          this.pending = null;
          try {
            if (this.read()?.token === value.token) this.storage.removeItem(this.key);
          } catch (_) { /* The server has acknowledged the position. */ }
          this.status("Position synced");
        }
      } catch (_) {
        this.status("Position not synced. Retrying…");
        this.timer = this.schedule(() => this.flush(), 3000);
        return;
      } finally {
        this.saving = false;
      }
      if (this.pending) this.flush();
    }
  }
  if (typeof module !== "undefined" && module.exports) module.exports = ProgressQueue;
  else root.ReaderProgressQueue = ProgressQueue;
})(globalThis);
