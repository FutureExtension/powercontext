"use strict";

const $ = (id) => document.getElementById(id);

async function loadTopics() {
  try {
    const response = await fetch("/api/topics");
    const data = await response.json();
    const select = $("topic");
    const current = select.value;
    select.innerHTML = '<option value="">全部主题</option>';
    for (const [topic, count] of data.topics || []) {
      const option = document.createElement("option");
      option.value = topic;
      option.textContent = `${topic}（${count}）`;
      select.appendChild(option);
    }
    select.value = current;
  } catch (error) {
    $("hint").textContent = "无法读取主题列表：" + error;
  }
}

async function loadProgress() {
  try {
    const response = await fetch("/api/progress");
    const data = await response.json();
    const list = $("progress");
    list.innerHTML = "";
    const items = data.progress || [];
    if (!items.length) {
      list.innerHTML = '<li class="meta">还没有复习记录。检索后点“标记已掌握”即可开始。</li>';
      return;
    }
    for (const item of items) {
      const total = item.mastered + item.open;
      const percent = total ? Math.round((item.mastered / total) * 100) : 0;
      const li = document.createElement("li");
      li.innerHTML =
        `<strong>${item.topic}</strong> ` +
        `<span class="bar"><span style="width:${percent}%"></span></span>` +
        `已掌握 ${item.mastered} / 待复习 ${item.open} / 复习 ${item.reviews} 次`;
      list.appendChild(li);
    }
  } catch (error) {
    $("progress").innerHTML = '<li class="meta">无法读取复习进度。</li>';
  }
}

function renderHits(payload) {
  const list = $("hits");
  list.innerHTML = "";
  const hits = payload.hits || [];
  if (!hits.length) {
    list.innerHTML = '<li class="meta">没有找到相关笔记，换个说法再试。</li>';
    return;
  }
  for (const hit of hits) {
    const li = document.createElement("li");
    li.innerHTML =
      `<div class="title">${hit.title}</div>` +
      `<div class="meta">主题 ${hit.topic} · 来源 ${hit.source_path} · 相关度 ${hit.score.toFixed(4)}</div>` +
      `<div class="snippet">${hit.snippet}</div>`;
    const actions = document.createElement("div");
    actions.className = "actions";
    const mastered = document.createElement("button");
    mastered.textContent = "标记已掌握";
    mastered.onclick = () => mark(hit.topic, hit.note_id, true);
    const open = document.createElement("button");
    open.textContent = "标记待复习";
    open.onclick = () => mark(hit.topic, hit.note_id, false);
    actions.appendChild(mastered);
    actions.appendChild(open);
    li.appendChild(actions);
    list.appendChild(li);
  }
}

async function mark(topic, noteId, mastered) {
  const response = await fetch("/api/mark", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, note_id: noteId, mastered }),
  });
  const data = await response.json();
  $("hint").textContent = `已记录：${data.topic} 现在已掌握 ${data.mastered.length} 条，待复习 ${data.open_notes.length} 条。`;
  await loadProgress();
}

async function ask() {
  const question = $("question").value.trim();
  const topic = $("topic").value;
  if (!question) {
    $("hint").textContent = "请先输入问题。";
    return;
  }
  $("hint").textContent = "检索中…";
  const params = new URLSearchParams({ q: question });
  if (topic) params.set("topic", topic);
  const response = await fetch("/api/ask?" + params.toString());
  const data = await response.json();
  renderHits(data);
  const parts = [];
  parts.push(`命中 ${(data.hits || []).length} 条笔记`);
  if (data.open_notes && data.open_notes.length) {
    parts.push(`该主题还有 ${data.open_notes.length} 条待复习`);
  }
  parts.push(`查询已发出 ${(data.statements || []).length} 条 SQL`);
  $("hint").textContent = parts.join(" · ");
  await loadProgress();
}

$("ask").addEventListener("click", ask);
$("question").addEventListener("keydown", (event) => {
  if (event.key === "Enter") ask();
});

// A link may carry the question, so a result can be shared and reopened.
const params = new URLSearchParams(window.location.search);
if (params.get("q")) {
  $("question").value = params.get("q");
  if (params.get("topic")) {
    const restore = () => {
      $("topic").value = params.get("topic");
      ask();
    };
    setTimeout(restore, 300);
  } else {
    setTimeout(ask, 300);
  }
}

loadTopics();
loadProgress();
