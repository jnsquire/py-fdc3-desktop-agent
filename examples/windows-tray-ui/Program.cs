using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Web.WebView2.WinForms;

namespace Fdc3TrayUi;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();

        var settings = AppSettings.Load("appsettings.json");
        var baseUrl = settings.BaseUrl?.TrimEnd('/') ?? "http://localhost:8000";

        using var context = new TrayAppContext(baseUrl);
        Application.Run(context);
    }
}

internal static class AppMenu
{
    public static readonly (string Text, string Path)[] Items = new[]
    {
        ("Open App Directory", "/app-directory"),
        ("Manage Apps", "/manage-apps"),
        ("System Settings", "/system-settings"),
        ("Channels", "/channels"),
        ("Diagnostics", "/diagnostics"),
        ("Search", "/search"),
        ("Alert", "/alert")
    };
}

internal sealed class TrayAppContext : ApplicationContext
{
    private readonly NotifyIcon _trayIcon;
    private readonly string _baseUrl;

    public TrayAppContext(string baseUrl)
    {
        _baseUrl = baseUrl;

        var menu = new ContextMenuStrip();

        foreach (var (text, path) in AppMenu.Items)
            menu.Items.Add(text, null, (_, _) => Open(path));

        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Exit", null, (_, _) => ExitThread());

        _trayIcon = new NotifyIcon
        {
            Text = "FDC3 Desktop Agent",
            Visible = true,
            ContextMenuStrip = menu,
            Icon = SystemIcons.Application
        };
    }

    private void Open(string path)
    {
        var url = $"{_baseUrl}{path}";
        var form = new WebViewWindow(url);
        form.Show();
        form.BringToFront();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _trayIcon.Visible = false;
            _trayIcon.Dispose();
        }

        base.Dispose(disposing);
    }
}

internal sealed class AppSettings
{
    [JsonPropertyName("baseUrl")]
    public string? BaseUrl { get; set; }

    public static AppSettings Load(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return new AppSettings();
            }

            var json = File.ReadAllText(path);
            return JsonSerializer.Deserialize<AppSettings>(json) ?? new AppSettings();
        }
        catch
        {
            return new AppSettings();
        }
    }
}

internal sealed class WebViewWindow : Form
{
    private readonly string _url;
    private readonly WebView2 _webView;

    public WebViewWindow(string url)
    {
        _url = url;
        Text = "FDC3 Desktop Agent";
        Width = 1100;
        Height = 800;

        _webView = new WebView2
        {
            Dock = DockStyle.Fill
        };

        Controls.Add(_webView);
        Load += OnLoadAsync;
    }

    private async void OnLoadAsync(object? sender, EventArgs e)
    {
        await _webView.EnsureCoreWebView2Async();
        _webView.Source = new Uri(_url);
    }
}
