import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import { copyFile, lstat, mkdir, mkdtemp, readFile, readdir, realpath, rename, rm, rmdir, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, relative, sep } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

export const name = "codex-desktop-trace";
export const inject = ["sessionPersistence", "sessions"];

const noticeDir = home => join(home, "storages", "dsh-codex-desktop-trace");
const sessionName = /^session-[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const artifactName = "session.v4.jsonl.zstd";

async function optional(promise) {
  try {
    return await promise;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}

async function atomicText(target, text) {
  const staged = join(dirname(target), basename(target) + "." + randomUUID() + ".tmp");
  try {
    await writeFile(staged, text, { flag: "wx" });
    await rename(staged, target);
  } finally {
    await rm(staged, { force: true });
  }
}

async function digest(path) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest("hex");
}

async function fingerprint(path) {
  const stat = await lstat(path, { bigint: true });
  if (!stat.isFile()) throw new Error("Expected a regular native session file");
  return [stat.size, stat.mtimeNs, stat.ino].join(":");
}

async function publish(home, sourceHome, snapshot, id) {
  if (!sessionName.test(id) || snapshot?.location?.kind !== "jsonl") {
    throw new Error("Completed session has no supported native log");
  }
  const src = snapshot.location.path;
  const [project, session, filename, extra] = relative(join(sourceHome, "sessions"), src).split(sep);
  if (extra !== undefined || !project?.startsWith("--") || !project.endsWith("--")
      || session !== id || filename !== artifactName) {
    throw new Error("Native session log is outside the managed source store");
  }

  const folder = join(home, "sessions", project, id);
  const dest = join(folder, artifactName);
  const ledger = join(folder, ".codex-desktop-trace-sha256");
  const state = noticeDir(home);
  await mkdir(state, { recursive: true });
  const stage = await mkdtemp(join(state, "snapshot-"));
  try {
    const copy = join(stage, artifactName);
    const before = await fingerprint(src);
    await copyFile(src, copy);
    if (before !== await fingerprint(src)) throw new Error("Source changed during snapshot");

    const next = await digest(copy);
    const projectFolder = dirname(folder);
    await mkdir(projectFolder, { recursive: true });
    const realHome = await realpath(home);
    const scope = relative(realHome, await realpath(projectFolder)).split(sep).join("/");
    if (scope !== "sessions/" + project) throw new Error("Unexpected Desktop project folder");
    await mkdir(folder, { recursive: true });
    const sessionFolder = relative(realHome, await realpath(folder)).split(sep).join("/");
    if (sessionFolder !== scope + "/" + id) throw new Error("Unexpected Desktop session folder");
    const oldVersion = await optional(fingerprint(dest));
    const old = oldVersion === undefined ? undefined : await digest(dest);
    const owner = await optional(fingerprint(ledger));
    const previous = owner === undefined ? undefined : await readFile(ledger, "utf8");
    if (old !== undefined && old !== next && old !== previous) {
      throw new Error("Desktop already owns a different revision of this session");
    }
    if (old !== next) {
      if (oldVersion !== await optional(fingerprint(dest))) {
        throw new Error("Desktop session changed during publication");
      }
      await rename(copy, dest);
    }
    await atomicText(ledger, next);
    const notices = join(state, "notices");
    await mkdir(notices, { recursive: true });
    await atomicText(join(notices, id + ".json"), JSON.stringify({ id, nonce: randomUUID() }));
  } finally {
    await rm(join(stage, artifactName), { force: true });
    await rmdir(stage);
  }
}

function publishTurns(ctx, home, sourceHome) {
  const pending = new Map();
  const off = ctx.on("session/event", (session, event) => {
    if (event.type !== "turn/end") return;
    const id = session.header.id;
    const work = (pending.get(id) ?? Promise.resolve()).then(async () => {
      await ctx.sessions.flush(session);
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await publish(home, sourceHome, await ctx.sessionPersistence.stat(id), id);
          return;
        } catch (error) {
          if (attempt === 2) throw error;
          await delay(300 * (attempt + 1));
        }
      }
    }).catch(error => {
      ctx.logger.warn("Desktop trace publication failed for %s: %s", id, error.code ?? error.message);
    });
    pending.set(id, work);
    void work.then(() => {
      if (pending.get(id) === work) pending.delete(id);
    });
  });
  ctx.effect(() => async () => {
    off();
    await Promise.allSettled(pending.values());
  });
}

function refreshDesktop(ctx, home) {
  ctx.inject(["connection", "webServer", "sessionController"], ctx => {
    const state = noticeDir(home);
    const notices = join(state, "notices");
    const handled = new Map();
    let inflight = false;
    let previousError;
    let cookie;
    async function post(path, body) {
      const origin = ctx.webServer.protocol + "//127.0.0.1:" + ctx.webServer.port;
      if (!cookie) {
        const boot = await fetch(ctx.connection.authenticatedUrl(origin), {
          redirect: "manual", signal: AbortSignal.timeout(4000),
        });
        await boot.arrayBuffer();
        cookie = boot.headers.get("set-cookie")?.split(";", 1)[0];
        if (!cookie) throw new Error("Desktop local authentication was unavailable");
      }
      const response = await fetch(origin + "/api/dsh-context/" + path, {
        method: "POST",
        headers: { "content-type": "application/json", cookie },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(8000),
      });
      if (response.status === 401) cookie = undefined;
      if (!response.ok) throw new Error("Context Insights returned HTTP " + response.status);
      const data = await response.json();
      if (data.ok !== true) throw new Error("Context Insights rejected " + path);
      return data.value;
    }
    async function check() {
      if (inflight) return;
      inflight = true;
      try {
        const filenames = await optional(readdir(notices)) ?? [];
        const pending = [];
        for (const file of filenames) {
          const id = file.slice(0, -5);
          if (!file.endsWith(".json") || !sessionName.test(id)) continue;
          const raw = await optional(readFile(join(notices, file), "utf8"));
          if (!raw || handled.get(id) === raw) continue;
          const notice = JSON.parse(raw);
          if (notice.id !== id || typeof notice.nonce !== "string") continue;
          const snapshot = await ctx.sessionPersistence.stat(id);
          if (!snapshot?.location) continue;
          const visible = ctx.sessions.get(id);
          const list = ctx.sessionController.listState;
          const summary = visible ? list.summaryFor(visible) : list.summarizeCold(snapshot);
          pending.push({ id, raw, nonce: notice.nonce, summary });
        }
        if (!pending.length) return;
        await post("backfill", {});
        for (const { id, raw, nonce, summary } of pending) {
          // The Context Insights index and the desktop conversation catalog are independent.
          ctx.emit("api-session/added", summary);
          await atomicText(join(state, "indexed.json"),
            JSON.stringify({ id, nonce, refreshedAt: new Date().toISOString() }));
          handled.set(id, raw);
        }
        previousError = undefined;
      } catch (error) {
        const message = error.code ?? error.message;
        if (message !== previousError) {
          ctx.logger.warn("Could not refresh Desktop Context Insights: %s", message);
          previousError = message;
        }
      } finally {
        inflight = false;
      }
    }
    const timer = setInterval(() => void check(), 2500);
    timer.unref();
    ctx.effect(() => () => clearInterval(timer));
  });
}

export function apply(ctx) {
  const sourceHome = process.env.DSH_HOME || join(homedir(), ".dsh");
  const target = process.env.DSH_TRACE_PUBLISH_HOME;
  if (target) {
    if (!isAbsolute(target) || target === sourceHome) throw new Error("Invalid Desktop trace target");
    publishTurns(ctx, target, sourceHome);
  } else {
    refreshDesktop(ctx, sourceHome);
  }
}
