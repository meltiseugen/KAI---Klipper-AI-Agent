    // KlipperAI local route patch start
    function oe_force_klipperai_full_navigation()
    {
        if(!oe_is_connected_via_oe())
        {
            return;
        }

        var klipperAiHref = @@PREFIX@@;
        var klipperAiHrefNoSlash = klipperAiHref.endsWith("/") ? klipperAiHref.substring(0, klipperAiHref.length - 1) : klipperAiHref;
        var klipperAiDirectHref = klipperAiHref + "direct";

        async function oe_fetch_klipperai_html(reason)
        {
            var directUrl = new URL(klipperAiDirectHref, window.location.origin);
            directUrl.searchParams.set(reason, String(Date.now()));
            var response = await fetch(directUrl.toString(), {
                cache: "no-store",
                credentials: "same-origin",
                headers: {
                    "Accept": "text/html",
                    "X-KlipperAI-Route-Rescue": "1"
                }
            });

            if(!response.ok)
            {
                throw new Error("KlipperAI direct route returned status " + response.status);
            }

            var html = await response.text();
            if(html.indexOf("data-api-base=") === -1 || html.indexOf("KlipperAI") === -1)
            {
                throw new Error("KlipperAI direct route returned non-KlipperAI HTML.");
            }
            return html;
        }

        async function oe_open_klipperai_popup_directly(popup, visibleUrl)
        {
            try
            {
                var html = await oe_fetch_klipperai_html("_klipperai_direct_open");
                try
                {
                    popup.history.replaceState(null, "KlipperAI", visibleUrl.toString());
                }
                catch(_historyError)
                {
                    // Keep about:blank if the browser refuses a synthetic URL.
                }
                popup.document.open();
                popup.document.write(html);
                popup.document.close();
            }
            catch(error)
            {
                oe_log("KlipperAI direct popup load failed: " + error);
                popup.location.replace(visibleUrl.toString());
            }
        }

        function oe_reset_klipperai_nav_state(link)
        {
            if(!(link instanceof HTMLElement))
            {
                return;
            }

            var clearClasses = function(element)
            {
                if(!(element instanceof HTMLElement))
                {
                    return;
                }
                if(typeof element.blur === "function")
                {
                    element.blur();
                }
                element.removeAttribute("aria-current");
                element.classList.remove(
                    "router-link-active",
                    "router-link-exact-active",
                    "v-list-item--active",
                    "v-item--active",
                    "primary--text",
                    "text--accent-4",
                    "focus-visible"
                );
            };

            var listItem = link.closest(".v-list-item, li");
            var clearAll = function()
            {
                clearClasses(link);
                clearClasses(listItem);
            };

            clearAll();
            window.requestAnimationFrame(function()
            {
                clearAll();
                window.requestAnimationFrame(clearAll);
            });
            window.setTimeout(clearAll, 0);
            window.setTimeout(clearAll, 100);
        }

        function oe_klipperai_route_needs_rescue()
        {
            if(document.body instanceof HTMLElement && document.body.dataset && document.body.dataset.apiBase)
            {
                return false;
            }

            var currentPath = window.location.pathname || "";
            return currentPath === klipperAiHrefNoSlash || currentPath === klipperAiHref;
        }

        async function oe_rescue_klipperai_route_if_needed()
        {
            if(!oe_klipperai_route_needs_rescue())
            {
                return;
            }

            oe_log("Rescuing /klipperai route from Mainsail shell.");

            try
            {
                var html = await oe_fetch_klipperai_html("_klipperai_direct");
                document.open();
                document.write(html);
                document.close();
            }
            catch(error)
            {
                oe_log("KlipperAI route rescue failed: " + error);
            }
        }

        document.addEventListener("click", function(event)
        {
            var target = event.target;
            if(!(target instanceof Element))
            {
                return;
            }

            var selector = 'a[href="' + klipperAiHrefNoSlash + '"], a[href="' + klipperAiHref + '"]';
            var link = target.closest(selector);
            if(link == null)
            {
                return;
            }

            if(link instanceof HTMLAnchorElement)
            {
                link.target = @@TARGET@@;
                if(@@TARGET@@ === "_blank")
                {
                    link.rel = "noopener noreferrer";
                }
            }

            event.preventDefault();
            event.stopPropagation();
            if(typeof event.stopImmediatePropagation === "function")
            {
                event.stopImmediatePropagation();
            }
            event.cancelBubble = true;
            event.returnValue = false;
            oe_reset_klipperai_nav_state(link);
            if (@@TARGET@@ === "_blank") {
            oe_log("Opening KlipperAI in a new tab.");
            var resolvedUrl = new URL(klipperAiHref, window.location.origin);
            resolvedUrl.searchParams.set("_klipperai_nav", String(Date.now()));
            var popup = window.open("about:blank", "_blank");
            if(popup == null)
            {
                oe_log("Browser blocked the KlipperAI popup.");
            }
            else
            {
                try
                {
                    popup.opener = null;
                }
                catch(_error)
                {
                    // Ignore cross-window opener assignment issues.
                }
                oe_open_klipperai_popup_directly(popup, resolvedUrl);
                if(typeof popup.focus === "function")
                {
                    popup.focus();
                }
            }
            } else {
            oe_log("Forcing full navigation for KlipperAI link.");
            window.location.assign(klipperAiHref);
            }

        }, true);

        oe_rescue_klipperai_route_if_needed();
    }
    oe_force_klipperai_full_navigation();
    // KlipperAI local route patch end
