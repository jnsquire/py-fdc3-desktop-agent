'use strict';

async function loadApps() {
  try {
    const response = await fetch('/graphql', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query: `
                            query {
                                apps {
                                    appId
                                    name
                                    version
                                    description
                                    intents
                                }
                            }
                        `,
      }),
    });

    const data = await response.json();
    displayApps(data.data.apps);
  } catch (error) {
    document.getElementById('apps-list').innerHTML = '<p>Error loading applications: ' + error.message + '</p>';
  }
}

// Client-side search + pagination helpers
let allApps = [];
let currentAppPage = 1;
let appPageSize = 10;

function displayApps(apps) {
  allApps = apps || [];
  currentAppPage = 1;
  renderApps();

  // Wire up controls (idempotent)
  const search = document.getElementById('app-search');
  if (search && !search._bound) {
    search.addEventListener('input', () => {
      currentAppPage = 1;
      renderApps();
    });
    search._bound = true;
  }
  const pageSize = document.getElementById('app-page-size');
  if (pageSize && !pageSize._bound) {
    pageSize.addEventListener('change', () => {
      currentAppPage = 1;
      renderApps();
    });
    pageSize._bound = true;
  }
  const prev = document.getElementById('app-prev');
  const next = document.getElementById('app-next');
  if (prev && !prev._bound) {
    prev.addEventListener('click', () => {
      if (currentAppPage > 1) {
        currentAppPage--;
        renderApps();
      }
    });
    prev._bound = true;
  }
  if (next && !next._bound) {
    next.addEventListener('click', () => {
      currentAppPage++;
      renderApps();
    });
    next._bound = true;
  }
}

function renderApps() {
  const container = document.getElementById('apps-list');
  const search = (document.getElementById('app-search')?.value || '').toLowerCase();
  appPageSize = parseInt(document.getElementById('app-page-size')?.value) || appPageSize;

  const filtered = allApps.filter((a) => {
    const name = (a.name || '').toLowerCase();
    const id = (a.appId || '').toLowerCase();
    return name.includes(search) || id.includes(search);
  });

  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / appPageSize));
  if (currentAppPage > pages) currentAppPage = pages;
  const start = (currentAppPage - 1) * appPageSize;
  const pageItems = filtered.slice(start, start + appPageSize);

  if (!pageItems || pageItems.length === 0) {
    container.innerHTML = '<p>No applications found.</p>';
  } else {
    container.innerHTML = pageItems
      .map((app) => `
                    <div class="app-card">
                        <div class="app-info">
                            <h3>${app.name}</h3>
                            <p><strong>ID:</strong> ${app.appId}</p>
                            <p><strong>Version:</strong> ${app.version || 'N/A'}</p>
                            <p><strong>Description:</strong> ${app.description || 'No description'}</p>
                            <p><strong>Intents:</strong> ${app.intents ? app.intents.join(', ') : 'None'}</p>
                        </div>
                        <div>
                            <span class="status status-stopped">Not Running</span>
                        </div>
                    </div>
                `)
      .join('');
  }

  document.getElementById('app-page-info').textContent = `Page ${currentAppPage} of ${pages} (${total} apps)`;
  document.getElementById('app-prev').disabled = currentAppPage <= 1;
  document.getElementById('app-next').disabled = currentAppPage >= pages;
  const stats = document.getElementById('app-stats');
  if (stats) stats.textContent = `${total} result${total === 1 ? '' : 's'}`;
}

// Load apps on page load
document.addEventListener('DOMContentLoaded', loadApps);
