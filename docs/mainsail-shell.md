# Mainsail integration

KlipperAI opens in a **new tab** from Mainsail's left navigation menu. Mainsail
stays open for printer controls and manual config edits. The integration uses
Mainsail's [custom-navigation format](https://github.com/mainsail-crew/docs/blob/zensical/docs/features/custom-themes/custom-navigation.md)
in `<printer-config>/.theme/navi.json`:

```json
[
  {
    "title": "KlipperAI",
    "href": "/klipperai/",
    "target": "_blank",
    "position": 85
  }
]
```

The installer preserves other navigation entries and offers automatic repair at
startup, after theme changes and every five minutes. See the
[navigation maintenance guide](../integrations/mainsail/README.md).

## Same-origin nginx routing

`deployment/installer/nginx.sh` generates `/etc/klipperai/nginx-location.conf`.
Include it **inside the Mainsail server block**, alongside its existing locations:

```nginx
server {
    # Existing listen, server_name, root, Moonraker and Mainsail locations...
    include /etc/klipperai/nginx-location.conf;
}
```

For the default prefix and port the generated locations are:

```nginx
location = /klipperai {
    absolute_redirect off;
    return 308 /klipperai/$is_args$args;
}

location ^~ /klipperai/ {
    access_log off;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
    proxy_set_header Connection "";
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Host "";
    proxy_set_header Forwarded "";
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_pass http://127.0.0.1:8811/;
}
```

The bare-prefix redirect is relative, preserving the browser's origin (including
HTTPS and nonstandard ports) and query string. nginx's
[`^~` prefix matching](https://nginx.org/en/docs/http/ngx_http_core_module.html#location)
keeps generic Mainsail JavaScript/CSS regex locations from intercepting assistant
assets. The trailing slash in
[`proxy_pass`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)
strips `/klipperai/` before forwarding. Streaming responses are unbuffered and
proxy caching is disabled, including inherited cache settings.

Keep the service's `root_path`, the nginx prefix, the navigation `href` and any
OctoEverywhere prefix aligned. Custom nested prefixes such as `/assistant/printer`
are supported. Keep the upstream port aligned with the daemon's loopback port.
The route uses the existing printer UI's trust boundary; see [security](security.md).

The guided installer adds the include idempotently at server scope, runs
`nginx -t`, and reloads only after validation succeeds. If patching, validation or
reload fails, it restores both the prior server file and prior proxy snippet
(or removes a newly created snippet). It rejects files without a complete
multiline server block. Review unusual nginx layouts manually.

For existing installs, rerun the guided installer with the current paths/options
to regenerate the snippet, or update the snippet manually to match the example,
then test and reload nginx. The sidebar repair hook only maintains `navi.json`;
it does not update proxy configuration. Do not add duplicate locations alongside
an older manually inlined KlipperAI route.

## Standalone page

The full page uses compact printer/connection badges beneath a clear KlipperAI
header. Printer knowledge, printer memory and provider settings sit below chat
history. On narrow screens the menu opens history and settings; choosing a panel
closes that menu, and Escape dismisses it. The composer is compact and drafts
remain saved when switching chats or reloading.

The menu link continues to use `_blank`. No return-navigation button is needed.
Root, `/direct` and `/embed` still serve the same inline page so remote popup
recovery and existing session clients continue to work.

## Drawer decision

The old optional source patch added a **topbar** button and right-hand iframe
drawer by modifying Mainsail's Vue files. It was separate from the left-menu
link. Its duplicate UI and version-specific rebuild/patch maintenance did not
justify retaining it. The source patch and apply helper have been removed.

Existing custom builds are unaffected by deleting the patch here. Users who
actually installed it can return to an official Mainsail build through their
normal updater while retaining the theme navigation entry.

## Verification

Automated tests cover default/custom prefixes, queries, streaming settings,
server-scope include placement, repeat installs, rollback and API/assets/session
behavior. JavaScript checks cover chat drafts, session renewal and mobile menu
actions. Rendered browser checks use local fixtures, not live printer evidence.

On the deployed printer:

1. Run `nginx -t` and reload nginx after updating the snippet.
2. Open `/klipperai?check=1` on the Mainsail origin. Confirm the redirect ends at
   `/klipperai/?check=1`, preserving scheme, hostname and port.
3. Click KlipperAI in Mainsail's left menu. Confirm a new tab opens and Mainsail
   stays open. Check desktop and narrow-screen settings/history navigation.
4. Ask a question and check streamed activity, a follow-up, restored history
   after reload, manual proposal recheck and deletion.
5. If using OctoEverywhere, repeat through its portal with the separately
   maintained [remote integration](../integrations/octoeverywhere/README.md).

Automated and local-browser checks do not prove the deployed nginx, Mainsail,
printer, model provider or remote tunnel works.
