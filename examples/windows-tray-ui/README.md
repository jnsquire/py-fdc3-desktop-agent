# FDC3 Tray UI (Windows)

Minimal Windows tray app that exposes system-intent endpoints as menu items.

## Build

```powershell
cd examples\windows-tray-ui
dotnet build
```

## Run

```powershell
cd examples\windows-tray-ui
dotnet run
```

## Configure

Edit `appsettings.json` to point at your agent host:

```json
{
  "baseUrl": "http://localhost:8000"
}
```
