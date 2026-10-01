document.addEventListener("DOMContentLoaded", () => {
  // === LOGIN FORM LOGIC ===
  const loginForm = document.getElementById("login-form");
  const loginAlert = document.getElementById("login-alert-box");
  const btnLoginSubmit = document.getElementById("btn-login-submit");

  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      loginAlert.style.display = "none";
      btnLoginSubmit.disabled = true;
      btnLoginSubmit.textContent = "認証中...";

      const username = document.getElementById("login-username").value.trim();
      const password = document.getElementById("login-password").value;

      try {
        const resp = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password })
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
          window.location.href = "/";
        } else {
          loginAlert.textContent = data.detail || "ログインに失敗しました。ユーザー名とパスワードを確認してください。";
          loginAlert.style.display = "block";
        }
      } catch (err) {
        loginAlert.textContent = "サーバーとの通信エラーが発生しました。時間をおいて再試行してください。";
        loginAlert.style.display = "block";
      } finally {
        btnLoginSubmit.disabled = false;
        btnLoginSubmit.textContent = "OmusuBI でログイン";
      }
    });
    return; // Stop here if on login page
  }

  // === AUTHENTICATED DASHBOARD LOGIC ===
  const btnLogout = document.getElementById("btn-logout");
  if (btnLogout) {
    btnLogout.addEventListener("click", async () => {
      try {
        await fetch("/api/auth/logout", { method: "POST" });
      } finally {
        window.location.href = "/";
      }
    });
  }

  const linkForm = document.getElementById("link-form");
  const alertBox = document.getElementById("alert-box");
  const btnSubmit = document.getElementById("btn-submit");
  const btnResync = document.getElementById("btn-resync");
  const btnUnlink = document.getElementById("btn-unlink");
  const btnSendInvites = document.getElementById("btn-send-invites");
  const inviteResultBox = document.getElementById("invite-result-box");

  // Parse code from URL params (e.g. ?code=OMUSU-1234)
  const urlParams = new URLSearchParams(window.location.search);
  const codeParam = urlParams.get("code");
  const codeInput = document.getElementById("code");
  if (codeParam && codeInput) {
    codeInput.value = codeParam;
  }

  function showAlert(msg, type = "success") {
    if (!alertBox) return;
    alertBox.textContent = msg;
    alertBox.className = `alert alert-${type}`;
    alertBox.style.display = "block";
  }

  function hideAlert() {
    if (alertBox) alertBox.style.display = "none";
  }

  // Link Discord Code
  if (linkForm) {
    linkForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlert();
      btnSubmit.disabled = true;
      btnSubmit.textContent = "連携処理中...";

      const code = document.getElementById("code").value.trim();

      try {
        const resp = await fetch("/api/link", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code })
        });
        const data = await resp.json();

        if (!resp.ok) {
          showAlert(data.detail || "連携に失敗しました", "error");
        } else {
          showAlert("アカウント連携が正常に完了しました！ページを更新します...", "success");
          setTimeout(() => window.location.reload(), 1200);
        }
      } catch (err) {
        showAlert("サーバーとの通信エラーが発生しました", "error");
      } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = "Discord と連携して権限を同期";
      }
    });
  }

  // Resync permissions
  if (btnResync) {
    btnResync.addEventListener("click", async () => {
      btnResync.disabled = true;
      btnResync.textContent = "🔄 再同期中...";

      try {
        const resp = await fetch("/api/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" }
        });
        const data = await resp.json();
        if (resp.ok) {
          showAlert("権限の再同期が完了しました！ページを更新します...", "success");
          setTimeout(() => window.location.reload(), 1000);
        } else {
          showAlert(data.detail || "同期に失敗しました", "error");
        }
      } catch (err) {
        showAlert("エラーが発生しました", "error");
      } finally {
        btnResync.disabled = false;
        btnResync.textContent = "🔄 権限を再同期";
      }
    });
  }

  // Unlink Discord
  if (btnUnlink) {
    btnUnlink.addEventListener("click", async () => {
      if (!confirm("Discord 連携を解除しますか？Developer ロールも自動的に解除されます。")) return;
      try {
        const resp = await fetch("/api/unlink", {
          method: "POST",
          headers: { "Content-Type": "application/json" }
        });
        if (resp.ok) {
          showAlert("連携を解除しました。ページを更新します...", "success");
          setTimeout(() => window.location.reload(), 1000);
        } else {
          showAlert("解除に失敗しました", "error");
        }
      } catch (err) {
        showAlert("エラーが発生しました", "error");
      }
    });
  }

  // Admin: Send unjoined invites
  if (btnSendInvites) {
    btnSendInvites.addEventListener("click", async () => {
      if (!confirm("サーバー未参加の Developer ロール保持者へ、招待 DM およびメールを一斉送信しますか？")) return;
      btnSendInvites.disabled = true;
      btnSendInvites.textContent = "✉️ 送信中...";

      try {
        const resp = await fetch("/api/admin/invite-unjoined", { method: "POST" });
        const data = await resp.json();

        if (resp.ok) {
          inviteResultBox.style.display = "block";
          inviteResultBox.innerHTML = `
            <strong>送信結果サマリ:</strong><br>
            • 対象ロール: <code>${data.target_role}</code> (保持者 ${data.total_role_users}名)<br>
            • 連携済みユーザー: ${data.linked_users}名<br>
            • 既にサーバー参加済み: ${data.already_in_guild}名<br>
            • 送信クールダウン中: ${data.in_cooldown}名<br>
            • <strong>今回新規招待を送信: ${data.invited_count}名</strong> (DM送信: ${data.dm_sent}通 / メール送信: ${data.email_sent}通)
          `;
        } else {
          alert(data.detail || "送信処理に失敗しました");
        }
      } catch (err) {
        alert("一括送信処理中にエラーが発生しました");
      } finally {
        btnSendInvites.disabled = false;
        btnSendInvites.textContent = "✉️ 未参加者へ招待を一斉送信 (DM + メール)";
      }
    });
  }
});
