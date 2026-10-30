document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const statusDot = document.getElementById('statusDot');
  const statusText = document.getElementById('statusText');
  const statsText = document.getElementById('statsText');
  const btnOpenChatGPT = document.getElementById('btnOpenChatGPT');
  const btnNewChat = document.getElementById('btnNewChat');
  const btnRestartBrowser = document.getElementById('btnRestartBrowser');
  const btnClearChat = document.getElementById('btnClearChat');

  // Account Status Elements
  const accountBadge = document.getElementById('accountBadge');
  const accountIcon = document.getElementById('accountIcon');
  const accountLabel = document.getElementById('accountLabel');
  const accStatusVal = document.getElementById('accStatusVal');
  const accUserVal = document.getElementById('accUserVal');
  const accPlanVal = document.getElementById('accPlanVal');
  const accHint = document.getElementById('accHint');
  const btnRefreshAccount = document.getElementById('btnRefreshAccount');

  const modelSelect = document.getElementById('modelSelect');
  const streamToggle = document.getElementById('streamToggle');
  const autoNewChatToggle = document.getElementById('autoNewChatToggle');
  const systemPrompt = document.getElementById('systemPrompt');
  const promptInput = document.getElementById('promptInput');
  const charCount = document.getElementById('charCount');
  const btnSend = document.getElementById('btnSend');
  const chatHistory = document.getElementById('chatHistory');
  const emptyNotice = document.getElementById('emptyNotice');

  // Inspector & Tabs
  const tabButtons = document.querySelectorAll('.tab-btn');
  const tabPanes = document.querySelectorAll('.tab-pane');
  const rawRequest = document.getElementById('rawRequest');
  const rawResponse = document.getElementById('rawResponse');
  const btnCopyRequest = document.getElementById('btnCopyRequest');
  const btnCopyResponse = document.getElementById('btnCopyResponse');
  const logsContainer = document.getElementById('logsContainer');
  const btnClearLogs = document.getElementById('btnClearLogs');

  // Character counter
  promptInput.addEventListener('input', () => {
    charCount.innerText = `${promptInput.value.length} characters`;
  });

  // Tab switching
  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      tabButtons.forEach(b => b.classList.remove('active'));
      tabPanes.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const tabKey = btn.getAttribute('data-tab');
      if (tabKey === 'inspector') document.getElementById('paneInspector').classList.add('active');
      else if (tabKey === 'curl') document.getElementById('paneCurl').classList.add('active');
      else if (tabKey === 'logs') document.getElementById('paneLogs').classList.add('active');
    });
  });

  // Copy buttons
  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      const text = document.getElementById(targetId)?.innerText;
      if (text) {
        navigator.clipboard.writeText(text);
        btn.innerText = 'Copied';
        setTimeout(() => btn.innerText = 'Copy', 1500);
      }
    });
  });

  btnCopyRequest.addEventListener('click', () => {
    navigator.clipboard.writeText(rawRequest.innerText);
    btnCopyRequest.innerText = 'Copied';
    setTimeout(() => btnCopyRequest.innerText = 'Copy', 1500);
  });

  btnCopyResponse.addEventListener('click', () => {
    navigator.clipboard.writeText(rawResponse.innerText);
    btnCopyResponse.innerText = 'Copied';
    setTimeout(() => btnCopyResponse.innerText = 'Copy', 1500);
  });

  // Open ChatGPT in new tab
  btnOpenChatGPT.addEventListener('click', () => {
    window.open('https://chatgpt.com', '_blank');
  });

  // Clear Chat History
  btnClearChat.addEventListener('click', () => {
    chatHistory.innerHTML = '';
    if (emptyNotice) chatHistory.appendChild(emptyNotice);
    statsText.innerText = 'Cleared';
  });

  // Clear Logs
  btnClearLogs.addEventListener('click', () => {
    logsContainer.innerHTML = '';
  });

  // Update Account UI
  function updateAccountUI(account) {
    if (!account) return;
    if (account.is_logged_in) {
      accountBadge.className = 'account-pill logged-in';
      accountIcon.innerText = '✅';
      accountLabel.innerText = account.name || 'Logged In Account';
      accStatusVal.innerText = 'Logged In';
      accUserVal.innerText = account.name || account.email || 'OpenAI User';
      accPlanVal.innerText = account.plan || 'Plus / Standard';
      accHint.innerHTML = '✅ <strong>Session Active:</strong> Logged into <strong>' + (account.name || 'OpenAI Account') + '</strong>. Session stored in <code>chatgpt_profile</code>.';
    } else {
      accountBadge.className = 'account-pill guest';
      accountIcon.innerText = '👤';
      accountLabel.innerText = 'Guest Mode';
      accStatusVal.innerText = 'Guest (Not Logged In)';
      accUserVal.innerText = 'None (Anonymous)';
      accPlanVal.innerText = 'Free Web Tier';
      accHint.innerHTML = '💡 <strong>Guest Mode:</strong> Prompts run anonymously. To use your Plus/Team account, click <em>Open ChatGPT</em> and log in once.';
    }
  }

  // Refresh Account Button
  btnRefreshAccount.addEventListener('click', async () => {
    btnRefreshAccount.disabled = true;
    btnRefreshAccount.innerText = 'Checking...';
    try {
      const res = await fetch('/api/account');
      if (res.ok) {
        const acc = await res.json();
        updateAccountUI(acc);
      }
    } catch (e) {
      console.error(e);
    } finally {
      btnRefreshAccount.disabled = false;
      btnRefreshAccount.innerText = 'Refresh';
    }
  });

  // Status Polling
  let seenLogs = new Set();
  async function pollStatus() {
    try {
      const res = await fetch('/health');
      if (!res.ok) throw new Error('Status request failed');
      const data = await res.json();
      const browser = data.browser || {};

      if (browser.busy) {
        statusDot.className = 'status-dot busy';
        statusText.innerText = 'ChatGPT Busy';
      } else if (browser.initialized) {
        statusDot.className = 'status-dot online';
        statusText.innerText = 'Browser Ready';
      } else {
        statusDot.className = 'status-dot';
        statusText.innerText = 'Initializing...';
      }

      if (browser.account) {
        updateAccountUI(browser.account);
      }

      if (browser.logs && browser.logs.length) {
        browser.logs.forEach(log => {
          if (!seenLogs.has(log)) {
            seenLogs.add(log);
            const line = document.createElement('div');
            line.className = 'log-entry';
            if (log.includes('[ERROR]')) line.classList.add('error');
            else if (log.includes('[WARNING]')) line.classList.add('warning');
            else if (log.includes('[INFO]')) line.classList.add('info');
            line.innerText = log;
            logsContainer.appendChild(line);
            logsContainer.scrollTop = logsContainer.scrollHeight;
          }
        });
      }
    } catch (err) {
      statusDot.className = 'status-dot offline';
      statusText.innerText = 'Bridge Offline';
    }
  }

  setInterval(pollStatus, 2000);
  pollStatus();

  // Reset New Chat
  btnNewChat.addEventListener('click', async () => {
    btnNewChat.disabled = true;
    btnNewChat.innerText = 'Resetting...';
    try {
      await fetch('/api/new-chat', { method: 'POST' });
      statsText.innerText = 'New chat created';
    } catch (e) {
      console.error(e);
    } finally {
      btnNewChat.disabled = false;
      btnNewChat.innerText = 'New Chat';
    }
  });

  // Restart Browser
  btnRestartBrowser.addEventListener('click', async () => {
    btnRestartBrowser.disabled = true;
    btnRestartBrowser.innerText = 'Restarting...';
    try {
      await fetch('/api/restart-browser', { method: 'POST' });
      statsText.innerText = 'Browser restarted';
    } catch (e) {
      console.error(e);
    } finally {
      btnRestartBrowser.disabled = false;
      btnRestartBrowser.innerText = 'Restart Browser';
    }
  });

  // Render Message Bubble
  function appendMessage(role, content) {
    if (emptyNotice && emptyNotice.parentElement) {
      emptyNotice.remove();
    }
    const row = document.createElement('div');
    row.className = `message-row ${role}`;

    const author = document.createElement('div');
    author.className = 'message-author';
    author.innerText = role === 'user' ? 'USER' : `ASSISTANT (${modelSelect.value})`;

    const body = document.createElement('div');
    body.className = 'message-body';
    body.innerHTML = marked.parse(content || '');

    row.appendChild(author);
    row.appendChild(body);
    chatHistory.appendChild(row);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return body;
  }

  // Send Prompt Execution
  async function sendPrompt() {
    const text = promptInput.value.trim();
    if (!text || btnSend.disabled) return;

    const sys = systemPrompt.value.trim();
    const model = modelSelect.value;
    const isStream = streamToggle.checked;
    const isNewChat = autoNewChatToggle.checked;

    appendMessage('user', text);
    promptInput.value = '';
    charCount.innerText = '0 characters';
    btnSend.disabled = true;
    btnSend.innerText = 'Generating...';

    const messages = [];
    if (sys) {
      messages.push({ role: 'system', content: sys });
    }
    messages.push({ role: 'user', content: text });

    const payload = {
      model: model,
      messages: messages,
      stream: isStream,
      new_chat: isNewChat
    };

    // Update Raw Request Inspector
    rawRequest.innerText = JSON.stringify(payload, null, 2);
    rawResponse.innerText = isStream ? "// Waiting for SSE chunks...\n" : "// Waiting for JSON response...\n";

    const startTime = performance.now();
    statsText.innerText = 'Executing request...';
    const assistantBubble = appendMessage('assistant', isStream ? '...' : 'Generating...');

    try {
      const response = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer not-needed'
        },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        throw new Error(errJson.detail || `HTTP Error ${response.status}`);
      }

      if (isStream) {
        let accumulatedText = '';
        rawResponse.innerText = '';
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          rawResponse.innerText += chunk;
          rawResponse.scrollTop = rawResponse.scrollHeight;

          const lines = chunk.split('\n');
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;
            const dataStr = trimmed.slice(6);
            if (dataStr === '[DONE]') break;

            try {
              const parsed = JSON.parse(dataStr);
              const deltaContent = parsed.choices?.[0]?.delta?.content;
              if (deltaContent) {
                accumulatedText += deltaContent;
                assistantBubble.innerHTML = marked.parse(accumulatedText);
                chatHistory.scrollTop = chatHistory.scrollHeight;
              }
            } catch (err) {
              // ignore parse errors on partial chunks
            }
          }
        }
      } else {
        const data = await response.json();
        rawResponse.innerText = JSON.stringify(data, null, 2);
        const content = data.choices?.[0]?.message?.content || '';
        assistantBubble.innerHTML = marked.parse(content);
        chatHistory.scrollTop = chatHistory.scrollHeight;
      }

      const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
      statsText.innerText = `Completed in ${elapsed}s`;

    } catch (err) {
      assistantBubble.innerHTML = `<span style="color: var(--danger); font-weight: 500;">Error: ${err.message}</span>`;
      rawResponse.innerText = `Error: ${err.message}`;
      statsText.innerText = 'Request failed';
    } finally {
      btnSend.disabled = false;
      btnSend.innerText = 'Send (Enter)';
    }
  }

  btnSend.addEventListener('click', sendPrompt);
  promptInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendPrompt();
    }
  });
});
