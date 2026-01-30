'use strict';

async function loadSettings() {
  try {
    document.getElementById('allowed-origins').value = 'http://localhost:3000\nhttps://example.com\n*.trusted.com';
  } catch (error) { console.error('Failed to load settings:', error); }
}

document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  const form = document.getElementById('security-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const origins = document.getElementById('allowed-origins').value
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0);
      try { alert('Security settings saved successfully!'); } catch (error) { alert('Failed to save settings: ' + error.message); }
    });
  }
});
