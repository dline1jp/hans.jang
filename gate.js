var SUPABASE_URL = "https://vlvblacfffkalojefjwp.supabase.co";
var SUPABASE_ANON_KEY = "sb_publishable_C4BZUGCN_QyMZkVe3PIysQ_ZkqosPCL";

function loadPass() {
  return fetch(SUPABASE_URL + "/rest/v1/premium_pass?select=pass&order=created_at.desc&limit=1", {
    headers: {
      apikey: SUPABASE_ANON_KEY,
      Authorization: "Bearer " + SUPABASE_ANON_KEY
    }
  }).then(function (res) {
    if (!res.ok) throw new Error("load");
    return res.json();
  }).then(function (rows) {
    var pass = rows && rows[0] && rows[0].pass;
    if (!pass) throw new Error("empty");
    return String(pass);
  });
}
function safeNext(raw) {
  if (!raw || raw.indexOf("\\") !== -1) return "";
  try {
    var u = new URL(raw, location.origin);
    if (u.origin !== location.origin) return "";
    if (u.pathname.indexOf("/Premium/") !== 0) return "";
    if (u.pathname === "/Premium/" || u.pathname === "/Premium/index.html") return "";
    return u.pathname + u.search;
  } catch (e) {
    return "";
  }
}
function showMenu() {
  var gate = document.getElementById("gate");
  var menu = document.getElementById("menu");
  if (gate) gate.style.display = "none";
  if (menu) menu.style.display = "block";
}
function unlockPremium() {
  var input = document.getElementById("pw");
  loadPass().then(function (pass) {
    if (!input || input.value !== pass) {
      alert("비밀번호가 틀립니다");
      return;
    }
    localStorage.setItem("hans-premium", pass);
    var next = safeNext(new URLSearchParams(location.search).get("next"));
    location.href = next || "/Premium/";
  }).catch(function () {
    alert("잠시 후 다시 입력해 주세요.");
  });
}
(function () {
  var path = location.pathname;
  var gate = path === "/Premium" || path === "/Premium/" || path === "/Premium/index.html";
  if (!gate) {
    if (path.indexOf("/Premium/") !== 0) return;
    document.documentElement.style.visibility = "hidden";
    loadPass().then(function (pass) {
      if (localStorage.getItem("hans-premium") !== pass) {
        location.replace("/Premium/?next=" + encodeURIComponent(path + location.search));
        return;
      }
      document.documentElement.style.visibility = "";
    }).catch(function () {
      location.replace("/Premium/");
    });
    return;
  }
  document.addEventListener("DOMContentLoaded", function () {
    var input = document.getElementById("pw");
    if (input) {
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") unlockPremium();
      });
    }
    loadPass().then(function (pass) {
      if (localStorage.getItem("hans-premium") === pass) showMenu();
    }).catch(function () {
      alert("잠시 후 다시 입력해 주세요.");
    });
  });
})();
