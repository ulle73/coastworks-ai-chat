from app.crawling.classification import requires_browser_rendering


def test_useful_server_rendered_html_does_not_require_browser():
    html = """
    <html><head><title>Golf</title></head><body>
      <main><h1>Golfkuponger</h1><p>{}</p></main>
    </body></html>
    """.format("Server-rendered product information. " * 12)

    assert requires_browser_rendering(html, "Server-rendered product information. " * 12) is False


def test_empty_react_root_with_module_script_requires_browser():
    html = """
    <html><body>
      <div id="root"></div>
      <script type="module" src="/assets/index-abc123.js"></script>
    </body></html>
    """

    assert requires_browser_rendering(html, "") is True


def test_empty_app_root_with_client_bundle_requires_browser():
    html = """
    <html><body>
      <div id="app"></div>
      <script src="/static/js/main.js"></script>
    </body></html>
    """

    assert requires_browser_rendering(html, "Loading") is True


def test_short_static_error_page_is_not_misclassified_as_javascript_app():
    html = "<html><body><h1>Not found</h1></body></html>"

    assert requires_browser_rendering(html, "Not found") is False
