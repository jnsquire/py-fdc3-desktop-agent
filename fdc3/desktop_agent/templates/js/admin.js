'use strict';

let currentEditingId = null;

document.addEventListener('DOMContentLoaded', () => {
  loadLaunchConfigs();
  const form = document.getElementById('launchConfigForm');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await saveLaunchConfig();
    });
  }
});

async function loadLaunchConfigs() {
  try {
    const response = await fetch('/graphql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: `
            query {
                launchConfigs {
                    appId
                    command
                    args
                    env { key value }
                    cwd
                    timeout
                }
            }
        `,
      }),
    });

    const result = await response.json();
    if (result.errors) {
      showStatus('Error loading configurations: ' + result.errors[0].message, 'error');
      return;
    }

    displayLaunchConfigs(result.data.launchConfigs);
  } catch (error) {
    showStatus('Error loading configurations: ' + error.message, 'error');
  }
}

function displayLaunchConfigs(configs) {
  const container = document.getElementById('launchConfigs');
  container.innerHTML = '';

  if (!configs || configs.length === 0) {
    container.innerHTML = '<p>No launch configurations found.</p>';
    return;
  }

  configs.forEach((config) => {
    const div = document.createElement('div');
    div.className = 'launch-config';
    div.innerHTML = `
                    <h3>${config.appId}</h3>
                    <p><strong>Command:</strong> ${config.command}</p>
                    <p><strong>Args:</strong> ${config.args.join(' ')}</p>
                    <p><strong>Environment:</strong> ${config.env.map((e) => `${e.key}=${e.value}`).join(', ')}</p>
                    <p><strong>CWD:</strong> ${config.cwd || 'Current directory'}</p>
                    <p><strong>Timeout:</strong> ${config.timeout}s</p>
                    <div class="actions">
                        <button onclick="editLaunchConfig('${config.appId}')">Edit</button>
                        <button class="danger" onclick="deleteLaunchConfig('${config.appId}')">Delete</button>
                    </div>
                `;
    container.appendChild(div);
  });
}

async function saveLaunchConfig() {
  const formData = getFormData();

  try {
    const response = await fetch('/graphql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: `
                            mutation CreateLaunchConfig($config: LaunchConfigInput!) {
                                createLaunchConfig(config: $config) {
                                    appId
                                }
                            }
                        `,
        variables: { config: formData },
      }),
    });

    const result = await response.json();
    if (result.errors) {
      showStatus('Error saving configuration: ' + result.errors[0].message, 'error');
      return;
    }

    showStatus('Configuration saved successfully!', 'success');
    document.getElementById('launchConfigForm').reset();
    currentEditingId = null;
    loadLaunchConfigs();
  } catch (error) {
    showStatus('Error saving configuration: ' + error.message, 'error');
  }
}

async function deleteLaunchConfig(appId) {
  if (!confirm(`Are you sure you want to delete the launch configuration for "${appId}"?`)) {
    return;
  }

  try {
    const response = await fetch('/graphql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: `
                            mutation DeleteLaunchConfig($appId: String!) {
                                deleteLaunchConfig(appId: $appId)
                            }
                        `,
        variables: { appId },
      }),
    });

    const result = await response.json();
    if (result.errors) {
      showStatus('Error deleting configuration: ' + result.errors[0].message, 'error');
      return;
    }

    showStatus('Configuration deleted successfully!', 'success');
    loadLaunchConfigs();
  } catch (error) {
    showStatus('Error deleting configuration: ' + error.message, 'error');
  }
}

function editLaunchConfig(appId) {
  showStatus('Edit functionality would load the configuration into the form', 'info');
}

function getFormData() {
  const envVars = [];
  document.querySelectorAll('.env-var').forEach((envVar) => {
    const key = envVar.querySelector('.env-key').value.trim();
    const value = envVar.querySelector('.env-value').value.trim();
    if (key && value) {
      envVars.push({ key, value });
    }
  });

  return {
    appId: document.getElementById('appId').value.trim(),
    command: document.getElementById('command').value.trim(),
    args: document
      .getElementById('args')
      .value.split('\n')
      .map((arg) => arg.trim())
      .filter((arg) => arg),
    env: envVars,
    cwd: document.getElementById('cwd').value.trim(),
    timeout: parseInt(document.getElementById('timeout').value) || 30,
  };
}

function addEnvVar() {
  const envVars = document.getElementById('envVars');
  const div = document.createElement('div');
  div.className = 'env-var';
  div.innerHTML = `
                <input type="text" placeholder="KEY" class="env-key">
                <input type="text" placeholder="VALUE" class="env-value">
                <button type="button" onclick="removeEnvVar(this)">Remove</button>
            `;
  envVars.appendChild(div);
}

function removeEnvVar(button) {
  button.parentElement.remove();
}

async function raiseIntent() {
  const intent = document.getElementById('intentName').value.trim();
  const contextText = document.getElementById('intentContext').value.trim();
  let context = null;
  if (contextText) {
    try {
      context = JSON.parse(contextText);
    } catch (e) {
      showStatus('Invalid JSON for context: ' + e.message, 'error');
      return;
    }
  }

  try {
    const response = await fetch('/admin/raise-intent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent, context }),
    });
    const result = await response.json();
    if (result.error) {
      showStatus('Raise intent failed: ' + result.error, 'error');
      document.getElementById('raiseResult').textContent = JSON.stringify(result);
      return;
    }

    document.getElementById('raiseResult').textContent = JSON.stringify(result, null, 2);
    showStatus('Intent raised. Targets: ' + (result.targets || []).length, 'success');
  } catch (e) {
    showStatus('Error raising intent: ' + e.message, 'error');
  }
}

// Expose functions used by inline handlers
window.editLaunchConfig = editLaunchConfig;
window.deleteLaunchConfig = deleteLaunchConfig;
window.addEnvVar = addEnvVar;
window.removeEnvVar = removeEnvVar;
window.raiseIntent = raiseIntent;
