# typed: strict
# frozen_string_literal: true

class Webpage2pdf < Formula
  include Language::Python::Virtualenv

  desc "Turn web pages into clean A4 PDFs that read like typeset essays"
  homepage "https://github.com/Nornchan/webpage2pdf"
  url "https://github.com/Nornchan/webpage2pdf/archive/refs/tags/v0.1.4.tar.gz"
  sha256 "08034bcf91dad40390deacb95d6ec5d8daa51bc000c314ea1589c87eb3ad72b3"
  license "MIT"
  head "https://github.com/Nornchan/webpage2pdf.git", branch: "main"

  # Alphabetical within each group, as brew style requires — build-time
  # dependencies sort as their own group, ahead of runtime ones. Three groups
  # are doing the real work:
  #
  #   cmake, ninja (build-time only) — Pillow's sdist build needs both to run
  #            its own meson/scikit-build-core backend. Without a real one on
  #            PATH, pip tries to bootstrap ninja from source *inside*
  #            Homebrew's sandboxed build environment, whose "superenv" PATH
  #            carries a shim script for ninja rather than a real binary
  #            (used to intercept and log tool invocations). That bootstrap's
  #            own build step runs `lipo` against the shim to check its
  #            architecture, `lipo` expects a Mach-O binary and gets a shell
  #            script, and the whole build fails with "can't figure out the
  #            architecture type of ... shims/mac/super/bin/ninja" — a real,
  #            reproducible failure for anyone building from source without a
  #            cached bottle, not a fluke of one test run. Declaring both here
  #            puts Homebrew's real binaries on PATH first, and Pillow's build
  #            backend finds them via shutil.which() before ever trying to
  #            build its own.
  #
  #   pango  — WeasyPrint does not bundle its text engine; it dlopen()s Pango at
  #            runtime, and dyld's default search path never includes
  #            /opt/homebrew/lib on Apple Silicon, Homebrew build or not —
  #            _bootstrap.py's DYLD_FALLBACK_LIBRARY_PATH re-exec still runs
  #            here exactly as it does for a source install (confirmed by
  #            tracing it against this formula's own installed interpreter).
  #            What declaring pango here actually buys you: the library is
  #            *guaranteed present and correctly linked*, so that re-exec
  #            always finds it and always succeeds — a source install depends
  #            on the user having separately run `brew install pango`
  #            themselves and the venv having been built from that same
  #            Homebrew Python rather than Anaconda's, which is what the
  #            "cannot load library libpango-1.0-0" error actually is.
  #
  #   pkg-config (build-time only) — declaring jpeg-turbo, freetype and the
  #            rest supplies their .pc files, but not a real pkg-config binary
  #            to read them with. Without it, Homebrew's sandboxed superenv
  #            still shims the pkg-config *command* on PATH, and that shim
  #            execs a real binary at a fixed path that doesn't exist —
  #            failing with "cannot execute: No such file or directory" —
  #            which sends Pillow's own build down a path where it can't find
  #            libjpeg at all and dies with RequiredDependencyException: jpeg.
  #            A genuinely easy one to miss, since every *library* dependency
  #            is declared correctly; it's the tool that reads them that was
  #            absent.
  #
  #   the rest — freetype, jpeg-turbo, libpng, libxml2, libxslt, little-cms2,
  #            openjpeg and webp are what Pillow and lxml build against.
  depends_on "cmake" => :build
  depends_on "ninja" => :build
  depends_on "pkg-config" => :build
  depends_on "freetype"
  depends_on "jpeg-turbo"
  depends_on "libpng"
  depends_on "libxml2"
  depends_on "libxslt"
  depends_on "little-cms2"
  depends_on "openjpeg"
  depends_on "pango"
  depends_on "python@3.13"
  depends_on "webp"

  uses_from_macos "libffi"
  uses_from_macos "zlib"

  resource "beautifulsoup4" do
    url "https://files.pythonhosted.org/packages/43/65/318323f98dbee45d42dff61d8f047181bc6f2268a9068cfad035a46be5af/beautifulsoup4-4.15.0.tar.gz"
    sha256 "288e3ca7d54b06f2ac191970bc275c1939cb46d450b255bf6718b04aa37ab4f7"
  end

  resource "brotli" do
    url "https://files.pythonhosted.org/packages/f7/16/c92ca344d646e71a43b8bb353f0a6490d7f6e06210f8554c8f874e454285/brotli-1.2.0.tar.gz"
    sha256 "e310f77e41941c13340a95976fe66a8a95b01e783d430eeaf7a2f87e0a57dd0a"
  end

  resource "certifi" do
    url "https://files.pythonhosted.org/packages/a3/c2/24167ea9858356b47a87a50d39908bfdb72ceeefe0041586e704e5376b3a/certifi-2026.7.22.tar.gz"
    sha256 "741e2c3b351ddf169a738da9f2c048608ff7f2c5cc02f1ebc6b118bb090d5d55"
  end

  resource "cffi" do
    url "https://files.pythonhosted.org/packages/9e/ef/008a1939e372c06329a3fce4279c02f328488f3526744906eeec3da7ad5f/cffi-2.1.1.tar.gz"
    sha256 "dd31f52ea1086513bb9df30f8fcee9b8918323ae067a3d5b78bc826a000712be"
  end

  resource "charset-normalizer" do
    url "https://files.pythonhosted.org/packages/bd/2a/23f34ec9d04624958e137efdc394888716353190e75f25dd22c7a2c7a8aa/charset_normalizer-3.4.9.tar.gz"
    sha256 "673611bbd43f0810bec0b0f028ddeaaa501190339cac411f347ac76917c3ae7b"
  end

  resource "cssselect2" do
    url "https://files.pythonhosted.org/packages/e0/20/92eaa6b0aec7189fa4b75c890640e076e9e793095721db69c5c81142c2e1/cssselect2-0.9.0.tar.gz"
    sha256 "759aa22c216326356f65e62e791d66160a0f9c91d1424e8d8adc5e74dddfc6fb"
  end

  resource "fonttools" do
    url "https://files.pythonhosted.org/packages/84/69/c97f2c18e0db87d2c7b15da1974dace76ae938f1cfa22e2727a648b7ed43/fonttools-4.63.0.tar.gz"
    sha256 "caeb583deeb5168e694b65cda8b4ee62abedfa66cf88488734466f2366b9c4e0"
  end

  resource "idna" do
    url "https://files.pythonhosted.org/packages/cd/63/9496c57188a2ee585e0f1db071d75089a11e98aa86eb99d9d7618fc1edce/idna-3.18.tar.gz"
    sha256 "ffb385a7e039654cef1ab9ef32c6fafe283c0c0467bba1d9029738ce4a14a848"
  end

  resource "lxml" do
    url "https://files.pythonhosted.org/packages/05/3b/aab6728cae887456f409b4d75e8a01856e4f04bd510de38052a47768b680/lxml-6.1.1.tar.gz"
    sha256 "ba96ae44888e0185281e937633a743ea90d5a196c6000f82565ebb0580012d40"
  end

  resource "pillow" do
    url "https://files.pythonhosted.org/packages/1c/3d/bb7fca845737cf9d7dbde16ed1843984665ff2e0a518f5db43e77ec540b9/pillow-12.3.0.tar.gz"
    sha256 "3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce"
  end

  resource "pycparser" do
    url "https://files.pythonhosted.org/packages/1b/7d/92392ff7815c21062bea51aa7b87d45576f649f16458d78b7cf94b9ab2e6/pycparser-3.0.tar.gz"
    sha256 "600f49d217304a5902ac3c37e1281c9fe94e4d0489de643a9504c5cdfdfc6b29"
  end

  resource "pydyf" do
    url "https://files.pythonhosted.org/packages/36/ee/fb410c5c854b6a081a49077912a9765aeffd8e07cbb0663cfda310b01fb4/pydyf-0.12.1.tar.gz"
    sha256 "fbd7e759541ac725c29c506612003de393249b94310ea78ae44cb1d04b220095"
  end

  resource "pyphen" do
    url "https://files.pythonhosted.org/packages/69/56/e4d7e1bd70d997713649c5ce530b2d15a5fc2245a74ca820fc2d51d89d4d/pyphen-0.17.2.tar.gz"
    sha256 "f60647a9c9b30ec6c59910097af82bc5dd2d36576b918e44148d8b07ef3b4aa3"
  end

  resource "requests" do
    url "https://files.pythonhosted.org/packages/ac/c3/e2a2b89f2d3e2179abd6d00ebd70bff6273f37fb3e0cc209f48b39d00cbf/requests-2.34.2.tar.gz"
    sha256 "f288924cae4e29463698d6d60bc6a4da69c89185ad1e0bcc4104f584e960b9ed"
  end

  resource "soupsieve" do
    url "https://files.pythonhosted.org/packages/69/99/a6ca3beb3ccacb41fb3321d8a60e5566f9e6467601ef8eba6a17e1b89778/soupsieve-2.9.2.tar.gz"
    sha256 "4a55d8cf158a9c2e587fa4922f1bbb91d68ac829e2d6f25403a85747c71daf74"
  end

  resource "tinycss2" do
    url "https://files.pythonhosted.org/packages/a3/ae/2ca4913e5c0f09781d75482874c3a95db9105462a92ddd303c7d285d3df2/tinycss2-1.5.1.tar.gz"
    sha256 "d339d2b616ba90ccce58da8495a78f46e55d4d25f9fd71dfd526f07e7d53f957"
  end

  resource "tinyhtml5" do
    url "https://files.pythonhosted.org/packages/b1/1f/cfe2f6b30557c92b3f31d41707e09cef5c1efbd87392bc6c0430c46b0e4d/tinyhtml5-2.1.0.tar.gz"
    sha256 "60a50ec3d938a37e491efa01af895853060943dcebb5627de5b10d188b338a67"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/f6/cc/6253133b5bb138fc3306cebfbda2c520f545d36b5be2c7255cc528bb45d6/typing_extensions-4.16.0.tar.gz"
    sha256 "dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5"
  end

  resource "urllib3" do
    url "https://files.pythonhosted.org/packages/53/0c/06f8b233b8fd13b9e5ee11424ef85419ba0d8ba0b3138bf360be2ff56953/urllib3-2.7.0.tar.gz"
    sha256 "231e0ec3b63ceb14667c67be60f2f2c40a518cb38b03af60abc813da26505f4c"
  end

  resource "weasyprint" do
    url "https://files.pythonhosted.org/packages/59/53/dcc3885c2f7a47faa45f6b8b801412f5f9e055173a52801ef01c09943c5a/weasyprint-69.0.tar.gz"
    sha256 "a7a32f39ca16bd82ef11de99c92ea4b5f14951c9033af035e451ce4f4ee0a88c"
  end

  resource "webencodings" do
    url "https://files.pythonhosted.org/packages/0b/02/ae6ceac1baeda530866a85075641cec12989bd8d31af6d5ab4a3e8c92f47/webencodings-0.5.1.tar.gz"
    sha256 "b36a1c245f2d304965eb4e0a82848379241dc04b865afcc4aab16748587e1923"
  end

  resource "zopfli" do
    url "https://files.pythonhosted.org/packages/74/21/3b6af43a663b22b00e738bb0642931a2579e15da6852613d56c6aa535d28/zopfli-0.4.3.tar.gz"
    sha256 "d3a50f91a13cea9bafe025de8fd87a005eb26de02a4f0c193127ddbf23ac8ebe"
  end
  def install
    virtualenv_install_with_resources

    man1.install "man/webpage2pdf.1"
    man1.install "man/webpage2pdf-server.1"

    bash_completion.install "completions/webpage2pdf.bash" => "webpage2pdf"
    zsh_completion.install  "completions/_webpage2pdf"
    fish_completion.install "completions/webpage2pdf.fish"
  end

  def caveats
    <<~EOS
      Two commands are installed, plus a short alias:
        webpage2pdf <url-or-file>     w2p <url-or-file>
        webpage2pdf-server            local drag-and-drop web app

      If a conversion ever fails to load its native libraries:
        webpage2pdf --doctor
    EOS
  end

  test do
    # A page wrapped in the usual furniture: nav, sidebar, ads, comments.
    (testpath/"article.html").write <<~HTML
      <!DOCTYPE html>
      <html lang="en"><head><meta charset="utf-8">
      <title>A Test Article</title></head>
      <body>
        <nav><a href="/">Home</a><a href="/about">About</a></nav>
        <aside class="sidebar"><a href="/x">Related</a></aside>
        <article>
          <h1>A Test Article</h1>
          #{"<p>Sentence with sufficient prose, commas, and length to register " \
            "as a real paragraph rather than a list of links.</p>" * 12}
        </article>
        <footer>Copyright</footer>
      </body></html>
    HTML

    system bin/"webpage2pdf", testpath/"article.html",
           "-o", testpath/"out.pdf", "--quiet"

    assert_path_exists testpath/"out.pdf"
    assert_equal "%PDF", (testpath/"out.pdf").read(4)

    # The furniture must be gone and the article kept.
    system bin/"webpage2pdf", testpath/"article.html",
           "-o", testpath/"out2.pdf", "--keep-html", testpath/"clean.html", "--quiet"
    cleaned = (testpath/"clean.html").read
    assert_match "sufficient prose", cleaned
    refute_match "Copyright", cleaned

    # The page's own "hide when printing" markup is honoured: a recommended-
    # articles rail marked print:hidden must not survive, even sitting inside
    # <main> beside the article (v0.1.4, Aeon support). The companion fix —
    # a hero image shipped once per responsive breakpoint collapsing to a
    # single <img> — needs a real downloadable image and so is covered by the
    # offline fixtures in tests/, which CI runs on every push.
    (testpath/"responsive.html").write <<~HTML
      <!DOCTYPE html>
      <html lang="en"><head><meta charset="utf-8">
      <title>Responsive</title></head><body><main>
        <article>
          <h1>Responsive</h1>
          <div class="hero md:hidden print:hidden"><img src="hero.jpg" alt="lead image on small screens"></div>
          <div class="hero hidden md:block print:hidden"><img src="hero.jpg" alt="lead image on large screens"></div>
          #{"<p>Real article prose with commas, clauses and enough length to " \
            "read as a genuine paragraph rather than a caption.</p>" * 12}
        </article>
        <div class="recirc print:hidden">
          <h2>More from us</h2>
          <a href="/a">A recommended piece nobody asked to print</a>
          <p>Teaser copy for the recommendation rail.</p>
        </div>
      </main></body></html>
    HTML

    system bin/"webpage2pdf", testpath/"responsive.html", "--no-images",
           "-o", testpath/"r.pdf", "--keep-html", testpath/"r.html", "--quiet"
    r = (testpath/"r.html").read
    assert_match "Real article prose", r
    refute_match "recommendation rail", r
    refute_match "More from us", r

    assert_match version.to_s, shell_output("#{bin}/w2p --version")
    assert_match "essay", shell_output("#{bin}/webpage2pdf --list-styles")
    assert_match "remarkable", shell_output("#{bin}/webpage2pdf --list-presets")
    assert_match "booklet", shell_output("#{bin}/webpage2pdf --list-profiles")

    # Every output format must produce a file of the right shape.
    system bin/"webpage2pdf", testpath/"article.html", "-o", testpath/"a.epub", "--quiet"
    assert_equal "PK", (testpath/"a.epub").read(2)

    system bin/"webpage2pdf", testpath/"article.html", "-o", testpath/"a.md", "--quiet"
    assert_match "title:", (testpath/"a.md").read

    system bin/"webpage2pdf", testpath/"article.html", "-o", testpath/"a.html", "--quiet"
    assert_match "<!DOCTYPE html>", (testpath/"a.html").read

    # Reads from stdin and writes to stdout, so it composes in a pipeline.
    piped = pipe_output("#{bin}/webpage2pdf - -o - --quiet",
                        (testpath/"article.html").read)
    assert_equal "%PDF", piped[0, 4]

    # A preset must change the page geometry, not just be accepted.
    system bin/"webpage2pdf", testpath/"article.html",
           "-o", testpath/"a5.pdf", "--preset", "a5", "--quiet"
    assert_path_exists testpath/"a5.pdf"
    refute_equal (testpath/"out.pdf").size, (testpath/"a5.pdf").size
  end
end
