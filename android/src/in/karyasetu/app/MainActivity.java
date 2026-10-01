package in.karyasetu.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.text.InputType;
import android.view.KeyEvent;
import android.view.ViewGroup;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;

/**
 * KaryaSetu — Android wrapper.
 * Loads the team's KaryaSetu server in a full-screen WebView. The server
 * address is asked once on first launch (default: the office server) and can
 * be changed any time from the connection dialog.
 */
public class MainActivity extends Activity {

    private static final String DEFAULT_URL = "https://workhubapp.pythonanywhere.com";

    private WebView web;
    private SharedPreferences prefs;
    private boolean dialogShowing = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("karyasetu", MODE_PRIVATE);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (request.isForMainFrame()) {
                    showServerDialog("Could not reach the server.\n\n"
                        + "Check that you are connected to the same Wi-Fi network "
                        + "as the server, and that the address below is correct.");
                }
            }
        });

        setContentView(web, new ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        // Connects straight to the team server; the address can still be
        // changed from the Back-button menu or the connection-error dialog.
        web.loadUrl(prefs.getString("server", DEFAULT_URL));
    }

    private void showServerDialog(String message) {
        if (dialogShowing) return;
        dialogShowing = true;

        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(prefs.getString("server", DEFAULT_URL));
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        input.setPadding(pad, pad / 2, pad, pad / 2);

        new AlertDialog.Builder(this)
            .setTitle("WorkHub server")
            .setMessage(message)
            .setView(input)
            .setCancelable(false)
            .setPositiveButton("Connect", (d, w) -> {
                dialogShowing = false;
                String url = input.getText().toString().trim();
                if (!url.startsWith("http://") && !url.startsWith("https://")) {
                    url = "http://" + url;
                }
                prefs.edit().putString("server", url).apply();
                web.loadUrl(url);
            })
            .setNegativeButton("Retry", (d, w) -> {
                dialogShowing = false;
                String saved = prefs.getString("server", DEFAULT_URL);
                web.loadUrl(saved);
            })
            .show();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (web.canGoBack()) {
                web.goBack();
                return true;
            }
            if (!dialogShowing) {
                dialogShowing = true;
                new AlertDialog.Builder(this)
                    .setTitle("WorkHub")
                    .setItems(new CharSequence[]{"Change server address", "Exit"},
                        (d, which) -> {
                            dialogShowing = false;
                            if (which == 0) {
                                showServerDialog("Enter the WorkHub server address.");
                            } else {
                                finish();
                            }
                        })
                    .setOnCancelListener(d -> dialogShowing = false)
                    .show();
                return true;
            }
        }
        return super.onKeyDown(keyCode, event);
    }
}
