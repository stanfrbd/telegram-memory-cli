"use strict";
const $ = (id) => document.getElementById(id);
import { createSearchController } from "/search.js";
import { createAuthController } from "/auth.js";
let auth,
  activeJobs = false;
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
  $("notice").hidden = false;
}
async function api(path, options = {}) {
  const headers = new Headers(options.headers);
  if (auth?.token) headers.set("Authorization", `Bearer ${auth.token}`);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    if (response.status === 401 && auth?.authorized) auth.lock();
    let message;
    try {
      const data = await response.json();
      message =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
    } catch {
      message = response.statusText;
    }
    throw Error(message);
  }
  return response;
}
const json = async (path, options) => (await api(path, options)).json();
const post = (path, body) =>
  json(path, { method: "POST", body: JSON.stringify(body) });
function guard(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (error) {
      notice(error.message, true);
    }
  };
}
function view(name) {
  for (const section of document.querySelectorAll("main section"))
    section.hidden = section.id !== `${name}-view`;
  for (const button of document.querySelectorAll("nav button"))
    button.classList.toggle("active", button.dataset.view === name);
  $("breadcrumb").textContent = name[0].toUpperCase() + name.slice(1);
}
for (const button of document.querySelectorAll("nav button"))
  button.onclick = () => view(button.dataset.view);
async function stats() {
  const data = await json("/api/status");
  $("stats").replaceChildren(
    ...[
      ["Messages indexed", data.stats.messages],
      ["Saved channels", data.saved_channels],
      ["Attachments", data.stats.files],
      ["Saved on server", data.stats.downloads],
    ].map(([label, count]) => {
      const card = el("div", null, "stat");
      card.append(el("span", label), el("strong", count.toLocaleString()));
      return card;
    }),
  );
}
async function channels() {
  const values = await json("/api/channels"),
    selected = $("channel").value;
  $("channel").replaceChildren(
    new Option("All indexed channels", ""),
    ...values.map((c) => new Option(c, c)),
  );
  $("channel").value = selected;
  $("saved-channels").replaceChildren(...values.map((c) => new Option(c, c)));
  $("channels").replaceChildren(
    ...values.map((channel) => {
      const card = el("div", null, "panel inline");
      const text = el("strong", channel);
      text.style.flex = "1";
      const sync = el("button", "Sync");
      sync.onclick = guard(async () =>
        queued(await post("/api/sync", { channel })),
      );
      const remove = el("button", "Remove");
      remove.onclick = guard(async () => {
        await json("/api/channels", {
          method: "DELETE",
          body: JSON.stringify({ channel }),
        });
        await channels();
        await stats();
      });
      card.append(text, sync, remove);
      return card;
    }),
  );
  if (!values.length)
    $("channels").append(
      el("div", "No saved channels yet. Add your first source above.", "empty"),
    );
}
$("channel-form").onsubmit = guard(async (event) => {
  event.preventDefault();
  await post("/api/channels", { channel: $("new-channel").value.trim() });
  $("new-channel").value = "";
  await channels();
  await stats();
});
function bytes(value) {
  if (value == null) return "";
  return value >= 1048576
    ? (value / 1048576).toFixed(1) + " MB"
    : (value / 1024).toFixed(1) + " KB";
}
async function waitJob(jobId, update = () => {}) {
  while (true) {
    const job = await json("/api/jobs/" + jobId);
    update(job);
    if (job.status === "completed") return job;
    if (!["queued", "running"].includes(job.status))
      throw Error(job.error || `Task ${job.status}.`);
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
}
async function saveFile(item, downloadUrl = null) {
  const response = await api(
    downloadUrl ||
      "/api/downloads/file?" +
        new URLSearchParams({
          channel: item.channel_id,
          message_id: item.message_id,
        }),
  );
  const url = URL.createObjectURL(await response.blob());
  const link = el("a");
  link.href = url;
  link.download = item.file_name || "download";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
function telegramReference(item) {
  return /^\d+$/.test(item.channel_id)
    ? `-100${item.channel_id}`
    : item.channel_id;
}
function messageCard(item) {
  const card = el("article", null, "card"),
    top = el("div", null, "card-top");
  top.append(
    el("span", item.channel_name, "channel-tag"),
    el("span", `#${item.message_id}`),
    el("span", item.sent_at ? new Date(item.sent_at).toLocaleString() : ""),
  );
  card.append(top);
  if (item.text) card.append(el("p", item.text));
  if (item.file_name)
    card.append(
      el(
        "div",
        `${item.file_name}  ·  ${item.mime_type || "File"}  ·  ${bytes(item.file_size)}`,
        "attachment",
      ),
    );
  const actions = el("div", null, "actions"),
    favorite = el("button", item.favorite ? "★ Favorited" : "☆ Favorite");
  favorite.onclick = guard(async () => {
    favorite.disabled = true;
    try {
      const result = await post("/api/favorites", {
        channel: item.channel_id,
        message_id: item.message_id,
        favorite: !item.favorite,
      });
      item.favorite = result.favorite;
      favorite.textContent = item.favorite ? "★ Favorited" : "☆ Favorite";
      if (card.parentElement === $("results") && !searchController.isRemote)
        await searchController.refresh();
    } finally {
      favorite.disabled = false;
    }
  });
  actions.append(favorite);
  if (item.message_url && /^https:\/\/t\.me\//.test(item.message_url)) {
    const link = el("a", "Open in Telegram ↗");
    link.href = item.message_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    actions.append(link);
  }
  if (item.file_name) {
    const device = el("button", "Download to device");
    const server = el(
      "button",
      item.file_path ? "Saved on server" : "Save on server",
    );
    server.disabled = Boolean(item.file_path);
    device.onclick = guard(async () => {
      device.disabled = true;
      try {
        if (item.file_path) await saveFile(item);
        else {
          device.textContent = "Preparing download…";
          const job = await post("/api/downloads", {
            channel: telegramReference(item),
            message_id: item.message_id,
            destination: "browser",
          });
          const outcome = await waitJob(job.job_id, (state) => {
            device.textContent =
              state.status === "queued" ? "Queued…" : "Downloading…";
          });
          device.textContent = "Sending to browser…";
          await saveFile(item, outcome.result.download_url);
        }
        notice("Download sent to your browser.");
      } finally {
        device.disabled = false;
        device.textContent = "Download to device";
      }
    });
    server.onclick = guard(async () => {
      server.disabled = true;
      try {
        const job = await post("/api/downloads", {
          channel: telegramReference(item),
          message_id: item.message_id,
          destination: "server",
        });
        server.textContent = "Saving on server…";
        const outcome = await waitJob(job.job_id);
        item.file_path = outcome.result.path;
        server.textContent = "Saved on server";
        notice("File saved in the server's configured download directory.");
        await stats();
      } finally {
        if (!item.file_path) {
          server.disabled = false;
          server.textContent = "Save on server";
        }
      }
    });
    actions.append(device, server);
  }
  card.append(actions);
  return card;
}
const searchController = createSearchController({
  json,
  post,
  el,
  messageCard,
  stats,
  waitJob,
  notice,
});
function queued(job) {
  notice(
    `Job queued (${job.job_id.slice(0, 8)}). Follow progress in Transfers.`,
  );
  activeJobs = true;
  guard(jobs)();
}
$("sync-all").onclick = guard(async () => {
  const button = $("sync-all");
  button.disabled = true;
  try {
    const job = await post("/api/sync", {});
    const outcome = await waitJob(job.job_id, (state) => {
      button.textContent =
        state.status === "queued"
          ? "Index sync queued…"
          : "Indexing Telegram messages…";
    });
    const count = (outcome.result.results || []).reduce(
      (sum, item) => sum + item.indexed_messages,
      0,
    );
    const errors = outcome.result.errors || [];
    notice(
      `Local index refreshed: ${count} messages read from Telegram. ${errors.length ? `${errors.length} source(s) failed; see Transfers.` : ""}`,
      Boolean(errors.length),
    );
    await stats();
    await searchController.refresh();
  } finally {
    button.disabled = false;
    button.textContent = "↻ Sync saved channels";
  }
});
$("upload-form").onsubmit = guard(async (event) => {
  event.preventDefault();
  const form = event.currentTarget,
    button = form.querySelector("button");
  button.disabled = true;
  try {
    const data = new FormData(form);
    data.set("document", form.elements.document.checked ? "true" : "false");
    queued(await json("/api/uploads", { method: "POST", body: data }));
    form.reset();
    view("transfers");
  } finally {
    button.disabled = false;
  }
});
async function jobs() {
  const rows = await json("/api/jobs");
  const wasActive = activeJobs;
  activeJobs = rows.some((r) => ["queued", "running"].includes(r.status));
  $("jobs").replaceChildren(
    ...rows.map((job) => {
      const card = el("article", null, "card"),
        title = el("div", null, "job-title");
      title.append(el("strong", job.kind), el("span", job.status, "badge"));
      card.append(
        title,
        el("p", `${job.created_at} · ${job.id.slice(0, 8)}`, "hint"),
      );
      if (job.error) card.append(el("p", job.error));
      if (job.result) {
        const details = el("details");
        details.append(
          el("summary", "Task details"),
          el("pre", JSON.stringify(job.result, null, 2), "job-result"),
        );
        card.append(details);
        if (job.result.errors?.length)
          card.append(
            el(
              "p",
              `${job.result.errors.length} source(s) failed. Open task details.`,
              "hint",
            ),
          );
        if (job.result.channels) {
          const show = el("button", "Show discovered channels");
          show.onclick = () => {
            renderDiscovery(job.result.channels);
            view("discover");
          };
          card.append(show);
        }
        if (
          job.result.results &&
          ["search", "account-search", "public-search"].includes(job.kind)
        ) {
          const show = el("button", "Show returned messages");
          show.onclick = () => {
            searchController.showRemote(job.result);
            view("search");
          };
          card.append(show);
        }
      }
      return card;
    }),
  );
  if (!rows.length)
    $("jobs").append(
      el("div", "No transfers yet. Your activity will appear here.", "empty"),
    );
  if (wasActive && !activeJobs) {
    await stats();
    if (!searchController.busy) await searchController.refresh();
    await rules();
    notice("Background tasks finished. Activity is available in Transfers.");
  }
}
async function refresh() {
  await channels();
  await stats();
  await searchController.refresh();
  await jobs();
  await rules();
}
auth = createAuthController({ loadWorkspace: refresh, notice });
guard(() => auth.start())();
setInterval(() => {
  if (auth.authorized) guard(jobs)();
}, 3000);

function renderDiscovery(channels) {
  $("discovery-results").replaceChildren(
    ...channels.map((channel) => {
      const card = el("article", null, "card"),
        add = el("button", "Save channel");
      card.append(
        el("h2", channel.title),
        el("p", `${channel.reference} · ${channel.kind}`),
      );
      add.onclick = guard(async () => {
        await post("/api/channels", { channel: channel.reference });
        await refresh();
        notice("Source saved. Sync it to index its messages.");
      });
      card.append(add);
      return card;
    }),
  );
  if (!channels.length)
    $("discovery-results").append(
      el("div", "Telegram returned no matching public channels.", "empty"),
    );
}
$("discover-form").onsubmit = guard(async (event) => {
  event.preventDefault();
  const job = await post("/api/discover", {
    query: $("discover-query").value,
    limit: 50,
  });
  queued(job);
  const timer = setInterval(async () => {
    try {
      const state = await json("/api/jobs/" + job.job_id);
      if (!["queued", "running"].includes(state.status)) {
        clearInterval(timer);
        if (state.result?.channels) renderDiscovery(state.result.channels);
        if (state.error) notice(state.error, true);
      }
    } catch (error) {
      clearInterval(timer);
      notice(error.message, true);
    }
  }, 1500);
});
$("rule-form").onsubmit = guard(async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  await post("/api/rules", {
    query: form.elements.query.value,
    channel: form.elements.channel.value || null,
    interval: Number(form.elements.interval.value) * 60,
  });
  await rules();
  notice(
    "Monitoring rule created. Keep the server running for scheduled checks.",
  );
});
async function rules() {
  const rows = await json("/api/rules");
  $("rules").replaceChildren(
    ...rows.map((rule) => {
      const card = el("article", null, "card");
      card.append(
        el("h2", rule.query),
        el(
          "p",
          `${rule.channel || "All saved channels"} · every ${rule.interval / 60} min · ${rule.enabled ? "Enabled" : "Paused"}`,
          "hint",
        ),
      );
      if (rule.last_error) card.append(el("p", rule.last_error));
      const actions = el("div", null, "actions");
      for (const [label, fn] of [
        [
          "View matches",
          async () => {
            $("hits-title").textContent = "Matches: " + rule.query;
            const hits = await json("/api/rules/" + rule.id + "/hits");
            $("rule-hits").replaceChildren(...hits.map(messageCard));
            if (!hits.length)
              $("rule-hits").append(el("p", "No matches recorded yet."));
          },
        ],
        [
          "Run now",
          async () => queued(await post("/api/rules/" + rule.id + "/run", {})),
        ],
        [
          rule.enabled ? "Pause" : "Resume",
          async () => {
            await json(
              "/api/rules/" + rule.id + "/enabled?enabled=" + !rule.enabled,
              { method: "PUT" },
            );
            await rules();
          },
        ],
        [
          "Delete",
          async () => {
            await json("/api/rules/" + rule.id, { method: "DELETE" });
            await rules();
          },
        ],
      ]) {
        const button = el("button", label);
        button.onclick = guard(fn);
        actions.append(button);
      }
      card.append(actions);
      return card;
    }),
  );
}
