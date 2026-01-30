'use strict';

function showStatus(message, type) {
  const status = document.getElementById('status');
  if (!status) return;
  status.textContent = message;
  status.className = `status ${type}`;
  status.style.display = 'block';
  setTimeout(() => {
    status.style.display = 'none';
  }, 5000);
}

function toggleEventContext(button) {
  const pre = button.parentElement.querySelector('.event-context');
  if (!pre) return;
  if (pre.style.display === 'none') {
    pre.style.display = 'block';
    button.textContent = 'Hide JSON';
  } else {
    pre.style.display = 'none';
    button.textContent = 'Show JSON';
  }
}

// Export to global scope for inline handlers
window.showStatus = showStatus;
window.toggleEventContext = toggleEventContext;
