    // KAI local route patch start
    function oe_force_kai_full_navigation()
    {
        if(!oe_is_connected_via_oe())
        {
            return;
        }

        var kaiHref = @@PREFIX@@;
        var kaiHrefNoSlash = kaiHref.endsWith("/") ? kaiHref.substring(0, kaiHref.length - 1) : kaiHref;
        var kaiDirectHref = kaiHref + "direct";

        async function oe_fetch_kai_html(reason)
        {
            var directUrl = new URL(kaiDirectHref, window.location.origin);
            directUrl.searchParams.set(reason, String(Date.now()));
            var response = await fetch(directUrl.toString(), {
                cache: "no-store",
                credentials: "same-origin",
                headers: {
                    "Accept": "text/html",
                    "X-KAI-Route-Rescue": "1"
                }
            });

            if(!response.ok)
            {
                throw new Error("KAI direct route returned status " + response.status);
            }

            var html = await response.text();
            if(html.indexOf("data-api-base=") === -1 || html.indexOf("KAI") === -1)
            {
                throw new Error("KAI direct route returned non-KAI HTML.");
            }
            return html;
        }

        async function oe_open_kai_popup_directly(popup, visibleUrl)
        {
            try
            {
                var html = await oe_fetch_kai_html("_kai_direct_open");
                try
                {
                    popup.history.replaceState(null, "KAI", visibleUrl.toString());
                }
                catch(_historyError)
                {
                    // A real navigation keeps relative API URLs usable if URL replacement fails.
                    popup.location.replace(visibleUrl.toString());
                    return;
                }
                popup.document.open();
                popup.document.write(html);
                popup.document.close();
            }
            catch(error)
            {
                oe_log("KAI direct popup load failed: " + error);
                popup.location.replace(visibleUrl.toString());
            }
        }

        function oe_reset_kai_nav_state(link)
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

        function oe_kai_route_needs_rescue()
        {
            if(document.body instanceof HTMLElement && document.body.dataset && document.body.dataset.apiBase)
            {
                return false;
            }

            var currentPath = window.location.pathname || "";
            return currentPath === kaiHrefNoSlash || currentPath === kaiHref;
        }

        async function oe_rescue_kai_route_if_needed()
        {
            if(!oe_kai_route_needs_rescue())
            {
                return;
            }

            oe_log("Rescuing /kai route from Mainsail shell.");

            try
            {
                var html = await oe_fetch_kai_html("_kai_direct");
                document.open();
                document.write(html);
                document.close();
            }
            catch(error)
            {
                oe_log("KAI route rescue failed: " + error);
            }
        }

        document.addEventListener("click", function(event)
        {
            var target = event.target;
            if(!(target instanceof Element))
            {
                return;
            }

            var selector = 'a[href="' + kaiHrefNoSlash + '"], a[href="' + kaiHref + '"]';
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
            oe_reset_kai_nav_state(link);
            if (@@TARGET@@ === "_blank") {
            oe_log("Opening KAI in a new tab.");
            var resolvedUrl = new URL(kaiHref, window.location.origin);
            resolvedUrl.searchParams.set("_kai_nav", String(Date.now()));
            var popup = window.open("about:blank", "_blank");
            if(popup == null)
            {
                oe_log("Browser blocked the KAI popup.");
                window.location.assign(resolvedUrl.toString());
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
                oe_open_kai_popup_directly(popup, resolvedUrl);
                if(typeof popup.focus === "function")
                {
                    popup.focus();
                }
            }
            } else {
            oe_log("Forcing full navigation for KAI link.");
            window.location.assign(kaiHref);
            }

        }, true);

        oe_rescue_kai_route_if_needed();
    }
    oe_force_kai_full_navigation();
    // KAI local route patch end
