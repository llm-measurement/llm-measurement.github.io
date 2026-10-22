// SPDX-License-Identifier: Apache-2.0
// Code authors: Vijay and Codex
(() => {
  const contacts = {
    email: 'Contact email',
    questions: 'Contact Q&A',
    'show-and-tell': 'Contact Show-and-tell',
  };

  function track(name) {
    if (typeof window.plausible === 'function') {
      // Never include clipboard text, element IDs, queries, hashes or link targets.
      try {
        window.plausible(name, {
          url: window.location.origin + window.location.pathname,
          props: { path: window.location.pathname },
        });
      } catch {
        // Analytics must not prevent copying or following a contact link.
      }
    }
  }

  function copyEvent(pre, text) {
    if (pre.hasAttribute('data-review')) return 'Copy verification command';
    if (pre.hasAttribute('data-config')) return 'Copy configuration';
    if (text.includes('install-fleetdiff.sh') || text.includes('pip install') || text.includes('go get ')) {
      return 'Copy install command';
    }
    if (pre.hasAttribute('data-sql') || text.includes('--litellm-db') || text.includes('psql ')) {
      return 'Copy database command';
    }
    if (pre.hasAttribute('data-run')) return 'Copy example command';
    return 'Copy analysis command';
  }

  document.querySelectorAll('a[data-contact]').forEach(link => {
    const name = contacts[link.dataset.contact];
    if (name) link.addEventListener('click', () => track(name));
  });

  document.querySelectorAll('main pre:not(.output)').forEach(pre => {
    const code = pre.querySelector('code');
    if (!code) return;
    const name = copyEvent(pre, code.textContent);
    const wrapper = document.createElement('div');
    wrapper.className = 'command-block';
    const tools = document.createElement('div');
    tools.className = 'command-tools';
    const status = document.createElement('span');
    status.className = 'copy-status';
    status.setAttribute('role', 'status');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'copy-command';
    button.textContent = 'Copy';
    button.setAttribute('aria-label', name);
    button.title = name;
    button.addEventListener('click', async () => {
      status.textContent = '';
      try {
        // Copy only the displayed code, preserving whitespace and final newlines.
        await navigator.clipboard.writeText(code.textContent);
        status.textContent = 'Copied';
        track(name);
      } catch {
        status.textContent = 'Copy unavailable; select the text to copy.';
      }
    });
    tools.append(status, button);
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.append(tools, pre);
  });
})();
