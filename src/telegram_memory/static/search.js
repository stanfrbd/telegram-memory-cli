"use strict";

const $ = (id) => document.getElementById(id);
const sourceLabels = {
  index: "Local index",
  saved: "Telegram · saved channels",
  account: "Telegram · my conversations",
  public: "Telegram · public posts",
};
const sourceHints = {
  index:
    "Search messages already indexed on this server. No Telegram request. Separate words may appear anywhere; use quotes for an exact phrase.",
  saved:
    "Search Telegram directly in your saved channels, or the selected channel. Returned messages are also indexed locally.",
  account:
    "Search Telegram conversations accessible to your account. This does not search every public channel. Returned messages are indexed locally.",
  public:
    "Search public posts on Telegram, including channels you have not saved. Free quota only; Premium may be required. Returned messages are indexed locally.",
};
const commonMimes = {
  "application/pdf": "PDF documents",
  "image/jpeg": "JPEG images",
  "image/png": "PNG images",
  "image/webp": "WebP images",
  "image/gif": "GIF images",
  "video/mp4": "MP4 video",
  "video/webm": "WebM video",
  "audio/mpeg": "MP3 audio",
  "audio/ogg": "OGG audio / voice",
  "audio/mp4": "M4A audio",
  "text/plain": "Plain text",
  "text/csv": "CSV files",
  "application/json": "JSON files",
  "application/zip": "ZIP archives",
  "application/x-7z-compressed": "7-Zip archives",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
    "Word documents",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
    "Excel spreadsheets",
};

export function createSearchController({
  json,
  post,
  el,
  messageCard,
  stats,
  waitJob,
  notice,
}) {
  let offset = 0,
    generation = 0,
    busy = false,
    remote = null,
    localRequest = 0;
  const pageSize = 50;
  const filters = [
    "channel",
    "media",
    "mime",
    "after",
    "before",
    "min-size",
    "max-size",
    "favorites",
    "downloaded",
  ];

  function status(text, state = "") {
    $("search-status").textContent = text;
    $("search-status").className = "search-status " + state;
    $("results").setAttribute("aria-busy", String(state === "busy"));
  }
  function controls() {
    const source = $("source").value;
    $("source-help").textContent = sourceHints[source];
    $("search-submit").textContent =
      source === "index" ? "Search index" : "Search Telegram";
    $("channel").disabled = ["account", "public"].includes(source);
    $("search-submit").disabled = busy;
    $("filter-help").textContent =
      source === "index"
        ? "Filters apply to the local index."
        : "Filters apply to returned messages only. They do not search deeper into Telegram history.";
  }
  function queryParameters() {
    const values = new URLSearchParams({
      q: $("query").value,
      limit: pageSize,
      offset,
    });
    for (const [name, id] of [
      ["channel", "channel"],
      ["media", "media"],
      ["mime_type", "mime"],
      ["after", "after"],
      ["before", "before"],
      ["min_size", "min-size"],
      ["max_size", "max-size"],
    ]) {
      if ($(id).value) values.set(name, $(id).value);
    }
    if ($("favorites").checked) values.set("favorite", "true");
    if ($("downloaded").checked) values.set("downloaded", "true");
    return values;
  }
  function render(rows, hasMore, label) {
    $("results").replaceChildren(...rows.map(messageCard));
    if (!rows.length)
      $("results").append(
        el(
          "div",
          "No matching messages. Try fewer filters, different words, or another search source.",
          "empty",
        ),
      );
    $("result-title").textContent =
      `${label} · ${rows.length}${hasMore ? "+" : ""}`;
    $("previous").disabled = busy || offset === 0;
    $("next").disabled = busy || !hasMore;
    $("page").textContent = `Page ${Math.floor(offset / pageSize) + 1}`;
  }
  function filterRemote(item) {
    const media = $("media").value,
      mime = (item.mime_type || "").toLowerCase();
    if (
      ["image", "audio", "video"].includes(media) &&
      !mime.startsWith(media + "/")
    )
      return false;
    if (
      media === "document" &&
      (!item.file_name || /^(image|audio|video)\//.test(mime))
    )
      return false;
    if (media === "text" && item.file_name) return false;
    if ($("mime").value && mime !== $("mime").value) return false;
    if ($("favorites").checked && !item.favorite) return false;
    if ($("downloaded").checked && !item.file_path) return false;
    if (
      $("min-size").value &&
      (item.file_size == null || item.file_size < Number($("min-size").value))
    )
      return false;
    if (
      $("max-size").value &&
      (item.file_size == null || item.file_size > Number($("max-size").value))
    )
      return false;
    if (
      $("after").value &&
      (!item.sent_at || item.sent_at.slice(0, 10) < $("after").value)
    )
      return false;
    if (
      $("before").value &&
      (!item.sent_at || item.sent_at.slice(0, 10) > $("before").value)
    )
      return false;
    return true;
  }
  function renderRemote() {
    if (!remote) return;
    const matches = remote.results.filter(filterRemote);
    busy = false;
    render(
      matches.slice(offset, offset + pageSize),
      matches.length > offset + pageSize,
      sourceLabels[remote.scope] || "Telegram",
    );
    const errors = remote.errors || [];
    const parts = [
      `Query “${remote.query || ""}”: ${remote.results.length} messages returned by Telegram; ${matches.length} match your filters. Saved in the local index.`,
    ];
    if (remote.truncated || remote.results.length >= (remote.limit || 100))
      parts.push(
        `Result limit reached (${remote.limit || 100}). Narrow your query for other matches.`,
      );
    if (remote.note) parts.push(remote.note);
    if (errors.length)
      parts.push(
        `${errors.length} source(s) failed; results may be incomplete.`,
      );
    status(parts.join(" "), errors.length ? "warning" : "");
    $("search-errors").replaceChildren();
    if (errors.length) {
      const details = el("details"),
        summary = el("summary", "Sources that could not be searched");
      details.append(
        summary,
        ...errors.map((error) =>
          el("p", `${error.channel}: ${error.error}`, "hint"),
        ),
      );
      $("search-errors").append(details);
    }
    controls();
  }
  async function searchLocal() {
    const request = ++localRequest;
    busy = true;
    controls();
    status("Searching the local index… No Telegram request.", "busy");
    try {
      const data = await json("/api/search?" + queryParameters());
      if (request !== localRequest || $("source").value !== "index") return;
      busy = false;
      render(data.results, data.has_more, "Local index");
      status(
        "Results from this server's index only. Switch the source to search Telegram directly.",
      );
    } finally {
      if (request === localRequest) {
        busy = false;
        controls();
      }
    }
  }
  async function submit() {
    const request = ++generation;
    offset = 0;
    remote = null;
    $("search-errors").replaceChildren();
    if ($("source").value === "index") return searchLocal();
    const scope = $("source").value,
      query = $("query").value.trim();
    if (!query) {
      status(
        "Enter a query to search Telegram. Use the local index to browse without a query.",
        "error",
      );
      return;
    }
    busy = true;
    controls();
    $("results").replaceChildren();
    $("previous").disabled = true;
    $("next").disabled = true;
    $("result-title").textContent = sourceLabels[scope];
    status(`Submitting search to ${sourceLabels[scope]}…`, "busy");
    try {
      const job = await post(
        {
          saved: "/api/search/remote",
          account: "/api/search/account",
          public: "/api/search/public",
        }[scope],
        {
          query,
          channel: scope === "saved" ? $("channel").value || null : null,
          limit: 100,
        },
      );
      const finished = await waitJob(job.job_id, (job) => {
        if (request === generation)
          status(
            job.status === "queued"
              ? "Telegram search queued. Waiting for the account's other tasks…"
              : `Searching ${sourceLabels[scope]}… Results will appear here automatically.`,
            "busy",
          );
      });
      if (request !== generation) return;
      remote = { ...finished.result, scope, query };
      await metadata();
      if (request !== generation) return;
      renderRemote();
      await stats();
    } catch (error) {
      if (request === generation) {
        status(`Telegram search failed: ${error.message}`, "error");
        $("results").replaceChildren(
          el(
            "div",
            "No results were substituted from the local index. You can retry or choose another source.",
            "empty",
          ),
        );
      }
    } finally {
      if (request === generation) {
        busy = false;
        controls();
      }
    }
  }
  async function metadata() {
    const data = await json("/api/search/metadata");
    const selected = $("mime").value;
    const types = [
      ...new Set([...Object.keys(commonMimes), ...data.mime_types]),
    ].sort();
    $("mime").replaceChildren(
      new Option("Any MIME type", ""),
      ...types.map(
        (mime) =>
          new Option(
            commonMimes[mime] ? `${commonMimes[mime]} · ${mime}` : mime,
            mime,
          ),
      ),
    );
    $("mime").value = selected;
    const channel = $("channel").value;
    const saved = await json("/api/channels");
    const indexed = data.channels.filter(
      (item) =>
        !saved.some(
          (ref) =>
            ref.replace(/^@/, "").toLowerCase() ===
              item.channel_name.toLowerCase() || ref === item.channel_id,
        ),
    );
    const reference = (item) =>
      /^\d+$/.test(item.channel_id)
        ? `-100${item.channel_id}`
        : item.channel_id;
    const refs = new Set(saved);
    for (const item of indexed) refs.add(reference(item));
    $("channel").replaceChildren(
      new Option("All sources", ""),
      ...saved.map((ref) => new Option(ref, ref)),
      ...indexed.map(
        (item) => new Option(`${item.channel_name} (indexed)`, reference(item)),
      ),
    );
    if (!refs.has(channel) && channel)
      $("channel").append(new Option(channel, channel));
    $("channel").value = channel;
  }
  function fail(error) {
    busy = false;
    controls();
    status(error.message, "error");
    notice(error.message, true);
  }
  $("search-form").onsubmit = (event) => {
    event.preventDefault();
    submit().catch(fail);
  };
  $("source").onchange = () => {
    ++generation;
    ++localRequest;
    busy = false;
    remote = null;
    offset = 0;
    controls();
    $("search-errors").replaceChildren();
    $("results").replaceChildren();
    $("previous").disabled = true;
    $("next").disabled = true;
    $("result-title").textContent = sourceLabels[$("source").value];
    $("page").textContent = "";
    status(sourceHints[$("source").value]);
    if ($("source").value === "index") searchLocal().catch(fail);
  };
  for (const id of filters)
    $(id).onchange = () => {
      offset = 0;
      if (id === "channel" && remote && $("source").value === "saved") {
        remote = null;
        $("results").replaceChildren();
        status(
          "Source channel changed. Run Search Telegram to search this channel.",
        );
      } else if (remote) renderRemote();
      else if ($("source").value === "index") searchLocal().catch(fail);
    };
  $("reset-filters").onclick = () => {
    for (const id of filters) {
      if ($(id).type === "checkbox") $(id).checked = false;
      else $(id).value = "";
    }
    offset = 0;
    if (remote) renderRemote();
    else if ($("source").value === "index") searchLocal().catch(fail);
  };
  for (const [id, direction] of [
    ["previous", -1],
    ["next", 1],
  ])
    $(id).onclick = () => {
      offset = Math.max(0, offset + direction * pageSize);
      if (remote) renderRemote();
      else searchLocal().catch(fail);
    };
  controls();
  return {
    get busy() {
      return busy;
    },
    get isRemote() {
      return $("source").value !== "index";
    },
    metadata,
    async refresh() {
      await metadata();
      if (!busy && $("source").value === "index") await searchLocal();
    },
    showRemote(outcome) {
      ++generation;
      ++localRequest;
      busy = false;
      offset = 0;
      remote = {
        ...outcome,
        scope:
          outcome.scope === "public-posts"
            ? "public"
            : outcome.scope || "saved",
      };
      $("source").value = remote.scope;
      $("query").value = remote.query || "";
      renderRemote();
    },
  };
}
