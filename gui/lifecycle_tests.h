#pragma once
#include <QtTest/QtTest>

namespace {

// No PTYs, screen clients or Codex processes: exercise the actual SessionPage
// and Qt shortcut delivery with a memory-only backend.
class MemoryTerminal final : public QWidget {
    Q_OBJECT
public:
    using QWidget::QWidget;
    Q_INVOKABLE bool pasteClipboardText() { ++pastes; return true; }
    void finish() { Q_EMIT terminalFinished(); }
    int pastes = 0;
protected:
    bool event(QEvent *event) override {
        if (event->type() == QEvent::ShortcutOverride) {
            // Emulate TerminalDisplay claiming keys before window shortcuts.
            event->accept();
            return true;
        }
        return QWidget::event(event);
    }
Q_SIGNALS:
    void terminalFinished();
};

class MemoryBackend final : public Gpt2CodexTerminalBackend {
public:
    QString id() const override { return QStringLiteral("konsole"); }
    bool usable() const override { return true; }
    QWidget *create(QWidget *parent, const QString &, const QStringList &args, const QString &) override {
        arguments = args;
        ++creates;
        last = new MemoryTerminal(parent);
        return last;
    }
    void start(QWidget *) override { ++starts; }
    void refreshAppearance(QWidget *) override {}
    QPointer<MemoryTerminal> last;
    QStringList arguments;
    int creates = 0;
    int starts = 0;
};

class GuiLifecycleTests final : public QObject {
    Q_OBJECT
    Session live{QStringLiteral("bridge"), QStringLiteral("g2c-bridge"),
        QStringLiteral("detached"), QStringLiteral("123.g2c-bridge"), QStringLiteral("Bridge")};
    Session missing{QStringLiteral("bridge"), QStringLiteral("g2c-bridge"),
        QStringLiteral("not_registered"), QStringLiteral("-"), QStringLiteral("Bridge")};

    static QString fixtureTemplate() {
        return QString::fromUtf8(G2C_GUI_TEST_WORK_DIR) + QStringLiteral("/tab-icons-XXXXXX");
    }
    static QRect opaqueBounds(const QImage &image) {
        QRect bounds;
        for (int y = 0; y < image.height(); ++y) {
            for (int x = 0; x < image.width(); ++x) {
                if (image.pixelColor(x, y).alpha() > 0) { bounds |= QRect(x, y, 1, 1); }
            }
        }
        return bounds;
    }
private Q_SLOTS:
    void projectIconSafety_data() {
        QTest::addColumn<QString>("scenario");
        for (const char *name : {"valid", "missing", "corrupt", "jpeg", "transparent", "file-limit", "dimension-limit",
                 "file-symlink-outside", "file-symlink-inside", "root-symlink", "ancestor-symlink", "directory", "fifo", "traversal", "relative"}) {
            QTest::newRow(name) << QString::fromLatin1(name);
        }
    }
    void projectIconSafety() {
        QFETCH(QString, scenario);
        QTemporaryDir fixture(fixtureTemplate());
        QVERIFY(fixture.isValid());
        const QString base = QDir(fixture.path()).canonicalPath();
        QVERIFY(QDir().mkpath(base + "/repos/demo"));
        QString root = base + "/repos/demo";
        const QString path = root + "/.icon.png";
        QImage image(32, 16, QImage::Format_ARGB32);
        image.fill(Qt::red);
        if (scenario == "valid") { QVERIFY(image.save(path, "PNG")); }
        else if (scenario == "corrupt") {
            QFile file(path); QVERIFY(file.open(QIODevice::WriteOnly));
            file.write(QByteArray::fromHex("89504e470d0a1a0a") + "invalid PNG");
        } else if (scenario == "jpeg") { QVERIFY(image.save(path, "BMP")); }
        else if (scenario == "transparent") { image.fill(Qt::transparent); QVERIFY(image.save(path, "PNG")); }
        else if (scenario == "file-limit") {
            QFile file(path); QVERIFY(file.open(QIODevice::WriteOnly)); QVERIFY(file.resize(g2ctabs::maxIconBytes + 1));
        } else if (scenario == "dimension-limit") {
            image = QImage(g2ctabs::maxIconDimension + 1, 1, QImage::Format_ARGB32);
            image.fill(Qt::red); QVERIFY(image.save(path, "PNG"));
        } else if (scenario.startsWith("file-symlink")) {
            const QString target = scenario.endsWith("outside") ? base + "/outside.png" : root + "/inside.png";
            QVERIFY(image.save(target, "PNG"));
            QVERIFY(QFile::link(target, path));
        } else if (scenario == "root-symlink") {
            QVERIFY(image.save(path, "PNG"));
            QVERIFY(QFile::link(root, base + "/repos/link"));
            root = base + "/repos/link";
        } else if (scenario == "ancestor-symlink") {
            QVERIFY(image.save(path, "PNG"));
            QVERIFY(QFile::link(base + "/repos", base + "/alias"));
            root = base + "/alias/demo";
        } else if (scenario == "directory") { QVERIFY(QDir().mkdir(path)); }
        else if (scenario == "fifo") { QCOMPARE(::mkfifo(QFile::encodeName(path).constData(), 0600), 0); }
        else if (scenario == "traversal") { root += "/../demo"; }
        else if (scenario == "relative") { root = "repos/demo"; }
        const QImage loaded = g2ctabs::readProjectIcon(root);
        QCOMPARE(!loaded.isNull(), scenario == "valid");
        if (!loaded.isNull()) { QCOMPARE(loaded, image); }
        QTabWidget tabs;
        const QIcon icon = g2ctabs::tabIcon(loaded, false, &tabs);
        QVERIFY(!icon.pixmap(g2ctabs::decorationSize()).isNull()); // Also verifies fallback in every rejected case.
    }
    void projectRootMetadata() {
        QHash<QString, QString> roots;
        const QByteArray good = "project_dir=/registered\nid=demo name=Display root=not-a-path root=/registered/project with spaces\nid=gpt2codex name=Bridge root=/registered/bridge\n";
        QVERIFY(g2ctabs::parseProjectRoots(good, roots));
        QCOMPARE(roots.value("demo"), QStringLiteral("/registered/project with spaces"));
        for (const QByteArray &bad : {QByteArray(), QByteArray("id=demo name=Demo root=/registered/demo\n"),
                 QByteArray("project_dir=/registered\nid=demo name=Demo root=/outside/demo\n"),
                 QByteArray("project_dir=/registered\nid=demo name=Demo root=/registered/../outside\n"),
                 good + "id=demo name=Other root=/registered/other\n", good + "id=other name=Other root=/registered/bridge\n",
                 good + QByteArray("\0", 1), QByteArray(65537, 'x')}) {
            QVERIFY(!g2ctabs::parseProjectRoots(bad, roots));
            QVERIFY(roots.isEmpty());
        }
    }
    void tabIconGeometryAndFallback() {
        QTabWidget tabs;
        QWidget page;
        tabs.addTab(&page, "Title");
        const int plainHeight = tabs.tabBar()->sizeHint().height();
        for (const QSize &size : {QSize(80, 40), QSize(20, 80)}) {
            QImage image(size, QImage::Format_ARGB32);
            image.fill(Qt::red);
            const QIcon icon = g2ctabs::tabIcon(image, false, &tabs);
            for (qreal dpr : {1.0, 2.0}) {
                const QPixmap pixmap = icon.pixmap(g2ctabs::decorationSize(), dpr, QIcon::Normal, QIcon::Off);
                const QRect bounds = opaqueBounds(pixmap.toImage());
                QVERIFY(!bounds.isEmpty());
                QVERIFY(bounds.width() <= qRound(20 * dpr));
                QVERIFY(bounds.height() <= qRound(20 * dpr));
                QVERIFY(bounds.right() < qRound(20 * dpr)); // The future indicator area stays empty.
                QVERIFY(qAbs(double(bounds.width()) / bounds.height() - double(size.width()) / size.height()) < 0.12);
            }
        }
        const QString oldTheme = QIcon::themeName();
        QIcon::setThemeName("g2c-missing-test-theme");
        for (bool dark : {false, true}) {
            QPalette palette = tabs.palette();
            palette.setColor(QPalette::Window, dark ? Qt::black : Qt::white);
            tabs.setPalette(palette);
            for (bool bridge : {false, true}) {
                const QIcon icon = g2ctabs::tabIcon({}, bridge, &tabs);
                QVERIFY(!opaqueBounds(icon.pixmap(g2ctabs::decorationSize()).toImage()).isEmpty());
                tabs.setIconSize(g2ctabs::decorationSize());
                tabs.setTabIcon(0, icon);
            }
        }
        QIcon::setThemeName(oldTheme);
        QVERIFY(tabs.tabBar()->sizeHint().height() <= plainHeight + 8);
    }
    void tabPresentationPreservesSessionViews() {
        QTemporaryDir fixture(fixtureTemplate());
        QVERIFY(fixture.isValid());
        const QString base = QDir(fixture.path()).canonicalPath();
        for (const QString &name : {QStringLiteral("demo"), QStringLiteral("bridge")}) {
            QVERIFY(QDir().mkdir(base + "/" + name));
            QImage image(20, 20, QImage::Format_ARGB32);
            image.fill(name == "demo" ? Qt::red : Qt::blue);
            QVERIFY(image.save(base + "/" + name + "/.icon.png", "PNG"));
        }
        MemoryBackend backend;
        BackendRegistry registry(backend);
        QTabWidget tabs;
        Session screen = live;
        screen.id = "demo"; screen.screenName = "g2c-demo"; screen.sessionId = "123.g2c-demo";
        Session tmux = screen;
        tmux.multiplexer = "tmux"; tmux.sessionId = "321.$0.123456";
        auto *first = new SessionPage({}, registry, "konsole", screen, &tabs);
        auto *second = new SessionPage({}, registry, "konsole", tmux, &tabs);
        tabs.addTab(first, displayName(screen)); tabs.addTab(second, displayName(tmux));
        const auto terminal = backend.last;
        g2ctabs::Presentation presentation;
        presentation.setRoots({{"demo", base + "/demo"}, {"gpt2codex", base + "/bridge"}});
        for (int i = 0; i < 3; ++i) {
            presentation.apply(&tabs, first, screen.id, screen.multiplexer, displayName(screen), "<img src=/private/file>");
            presentation.apply(&tabs, second, tmux.id, tmux.multiplexer, displayName(tmux), tmux.task);
            tabs.setCurrentWidget(i % 2 ? first : second);
            first->update(screen); second->update(tmux);
        }
        QCOMPARE(backend.starts, 2);
        QVERIFY(terminal);
        QVERIFY(second->containsTerminal(terminal));
        QCOMPARE(tabs.tabText(0), displayName(screen));
        QCOMPARE(tabs.tabText(1), displayName(tmux));
        QVERIFY(tabs.tabToolTip(0).contains(base + "/demo"));
        QVERIFY(tabs.tabToolTip(0).contains("[screen]"));
        QVERIFY(tabs.tabToolTip(1).contains("[tmux]"));
        QVERIFY(!tabs.tabToolTip(0).contains("<img"));
        QCOMPARE(tabs.tabIcon(0).pixmap(g2ctabs::decorationSize()).toImage().pixelColor(10, 10), QColor(Qt::red));
        backend.last->finish();
        second->activateTerminal(); second->update(tmux);
        presentation.apply(&tabs, second, tmux.id, tmux.multiplexer, displayName(tmux), tmux.task);
        QCOMPARE(backend.starts, 3);
        QCOMPARE(tabs.tabIcon(1).pixmap(g2ctabs::decorationSize()).toImage().pixelColor(10, 10), QColor(Qt::red));
        QVERIFY(!backend.arguments.contains("start"));
        // A registry lookup failure must drop a previously loaded custom image.
        presentation.setRoots({});
        presentation.apply(&tabs, first, screen.id, screen.multiplexer, displayName(screen), screen.task);
        QVERIFY(!tabs.tabToolTip(0).contains(base));
        QVERIFY(tabs.tabToolTip(0).contains("cesta není ověřena"));
    }
    void windowRefreshKeepsProjectIconsAndActualMultiplexers() {
        QTemporaryDir fixture(fixtureTemplate());
        QVERIFY(fixture.isValid());
        const QString base = QDir(fixture.path()).canonicalPath();
        for (const QString &project : {QStringLiteral("demo"), QStringLiteral("other"), QStringLiteral("bridge")}) {
            QVERIFY(QDir().mkpath(base + "/repos/" + project));
            QImage image(20, 20, QImage::Format_ARGB32);
            image.fill(project == "demo" ? Qt::red : project == "other" ? Qt::green : Qt::blue);
            QVERIFY(image.save(base + "/repos/" + project + "/.icon.png", "PNG"));
        }
        auto write = [](const QString &path, const QByteArray &bytes) {
            QFile file(path);
            return file.open(QIODevice::WriteOnly | QIODevice::Truncate) && file.write(bytes) == bytes.size();
        };
        const QByteArray roots = ("project_dir=" + base + "/repos\n"
            + "id=demo name=Demo root=" + base + "/repos/demo\n"
            + "id=other name=Other root=" + base + "/repos/other\n"
            + "id=gpt2codex name=Bridge root=" + base + "/repos/bridge\n").toUtf8();
        QVERIFY(write(base + "/roots", roots));
        const QByteArray listing =
            "multiplexer=screen generation=- project_id=bridge screen_name=g2c-bridge state=not_registered session_id=- task=Bridge\n"
            "multiplexer=screen generation=123 project_id=demo screen_name=g2c-demo state=interrupted session_id=123.g2c-demo task=Original\n"
            "multiplexer=tmux generation=456 project_id=demo screen_name=g2c-demo state=interrupted session_id=321.$0.123456 task=Original\n"
            "multiplexer=screen generation=789 project_id=other screen_name=g2c-other state=interrupted session_id=789.g2c-other task=Other\n";
        QVERIFY(write(base + "/sessions", listing));
        const QString cli = base + "/fixture-cli";
        QVERIFY(write(cli, "#!/bin/sh\nbase=${0%/*}\nprintf '%s/%s\\n' \"$1\" \"$2\" >> \"$base/calls\"\ncase \"$1/$2\" in\nprojects/list) /bin/cat \"$base/roots\";;\nsession/list) /bin/cat \"$base/sessions\";;\nsession/prefer) printf 'project_id=demo preferred=tmux\\n';;\n*) exit 89;;\nesac\n"));
        QVERIFY(QFile::setPermissions(cli, QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner));
        Options options; options.bridgeCli = cli; options.config = base + "/fixture-config";
        MainWindow window(options);
        auto *tabs = window.findChild<QTabWidget *>();
        QVERIFY(tabs);
        QTRY_COMPARE(tabs->count(), 4);
        QTRY_VERIFY(tabs->tabToolTip(1).contains(base + "/repos/demo"));
        auto *screen = qobject_cast<SessionPage *>(tabs->widget(1));
        auto *tmux = qobject_cast<SessionPage *>(tabs->widget(2));
        auto *other = qobject_cast<SessionPage *>(tabs->widget(3));
        QVERIFY(screen && tmux && other);
        const QString originalId = screen->session().sessionId;
        QCOMPARE(tabs->tabIcon(0).pixmap(g2ctabs::decorationSize()).toImage().pixelColor(10, 10), QColor(Qt::blue));
        QVERIFY(!tabs->tabBar()->tabButton(0, QTabBar::RightSide));
        auto checkPage = [&](SessionPage *page, const QString &root, const QColor &color) {
            const int index = tabs->indexOf(page);
            return index >= 0 && tabs->tabToolTip(index).contains(root)
                && tabs->tabToolTip(index).contains("[" + page->session().multiplexer + "]")
                && tabs->tabIcon(index).pixmap(g2ctabs::decorationSize()).toImage().pixelColor(10, 10) == color;
        };
        auto action = [&](const QString &text) -> QAction * {
            for (auto *item : window.findChildren<QAction *>()) { if (item->text() == text) { return item; } }
            return nullptr;
        };
        QAction *refresh = action("Obnovit seznam");
        QVERIFY(refresh);
        QVERIFY(checkPage(screen, base + "/repos/demo", Qt::red));
        QVERIFY(checkPage(tmux, base + "/repos/demo", Qt::red));
        QVERIFY(checkPage(other, base + "/repos/other", Qt::green));
        tabs->tabBar()->moveTab(3, 1);
        tabs->setCurrentWidget(tmux);
        // A real preference save uses only its existing local CLI operation;
        // actual session multiplexer/identity and tab artwork remain unchanged.
        ProjectMultiplexerSettings settings(options, nullptr, false);
        QVERIFY(settings.loadProjects("project_id=demo preferred=screen\n"));
        settings.setAvailable(true, true);
        settings.findChild<QComboBox *>("projectMultiplexer")->setCurrentIndex(1);
        settings.findChild<QPushButton *>("saveProjectMultiplexer")->click();
        QTRY_VERIFY(settings.findChild<QComboBox *>("projectMultiplexer")->isEnabled());
        QVERIFY(write(base + "/sessions", QByteArray(listing).replace("task=Original", "task=Refreshed")));
        refresh->trigger();
        QTRY_COMPARE(screen->session().task, QStringLiteral("Refreshed"));
        QCOMPARE(screen->session().sessionId, originalId);
        QCOMPARE(screen->session().multiplexer, QStringLiteral("screen"));
        QVERIFY(checkPage(screen, base + "/repos/demo", Qt::red));
        QVERIFY(checkPage(tmux, base + "/repos/demo", Qt::red));
        QVERIFY(checkPage(other, base + "/repos/other", Qt::green));
        // Closing/restoring a tab must rederive the icon from its project, not index.
        const int otherIndex = tabs->indexOf(other);
        tabs->tabCloseRequested(otherIndex);
        QTRY_COMPARE(tabs->count(), 3);
        QAction *restore = action("Zobrazit skryté záložky");
        QVERIFY(restore); restore->trigger();
        QTRY_COMPARE(tabs->count(), 4);
        auto *restored = qobject_cast<SessionPage *>(tabs->widget(3));
        QVERIFY(restored);
        QVERIFY(checkPage(restored, base + "/repos/other", Qt::green));
        QVERIFY(write(base + "/roots", "invalid registry\n"));
        refresh->trigger();
        QTRY_VERIFY(tabs->tabToolTip(tabs->indexOf(screen)).contains("cesta není ověřena"));
        QFile calls(base + "/calls");
        QVERIFY(calls.open(QIODevice::ReadOnly));
        const QByteArray called = calls.readAll();
        QVERIFY(called.contains("session/prefer\n"));
        for (const QByteArray &line : called.split('\n')) {
            QVERIFY(line.isEmpty() || line == "projects/list" || line == "session/list" || line == "session/prefer");
        }
    }
    void exitedProgramKeepsVerifiedTerminal() {
        const QByteArray listing = "multiplexer=tmux generation=456 project_id=bridge screen_name=g2c-bridge state=detached session_id=321.$0.123456 program=exited exit_code=23 exit_signal=- exited_at=123457 task=Bridge\n";
        QList<Session> parsed;
        QString error;
        QVERIFY(parseSessions(listing, parsed, error));
        QCOMPARE(parsed[0].programState, QStringLiteral("exited"));
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", parsed[0]);
        QCOMPARE(backend.starts, 1);
        QVERIFY(page.findChild<QLabel *>("sessionStatus")->text().contains("ukončen (exit 23"));
        for (int i=0; i<5; ++i) { page.update(parsed[0]); page.activateTerminal(); }
        QCOMPARE(backend.starts, 1);
        backend.last->finish();
        page.activateTerminal();
        page.update(parsed[0]);
        QCOMPARE(backend.starts, 2); // Reconnect only; no start/respawn arguments.
        QVERIFY(!backend.arguments.contains("start"));
        parsed.clear();
        QVERIFY(!parseSessions(QByteArray(listing).replace("program=exited", "program=running"), parsed, error));
        parsed.clear();
        QVERIFY(!parseSessions(QByteArray(listing).replace("exit_code=23", "exit_code=999"), parsed, error));
    }
    void bridgeStartup() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", missing);
        QCOMPARE(backend.starts, 0);
        page.update(live);
        QCOMPARE(backend.starts, 1);
        QCOMPARE(backend.arguments, QStringList({"session", "attach", "--multiplexer", "screen",
            "--expect-session-id", "123.g2c-bridge", "--bridge"}));
        for (int i = 0; i < 5; ++i) { page.update(live); page.activateTerminal(); }
        QCOMPARE(backend.starts, 1);
    }
    void missingBridgeNeverStarts() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", missing);
        page.update(missing);
        page.activateTerminal();
        QCOMPARE(backend.starts, 0);
    }
    void bridgeStartupChoosesExistingMultiplexer() {
        Session tmux = live;
        tmux.multiplexer = "tmux";
        tmux.sessionId = "321.$0.123456";
        QCOMPARE(startupBridgeKey({missing, tmux}), QStringLiteral("tmux:bridge"));
        QCOMPARE(startupBridgeKey({live, tmux}), QStringLiteral("screen:bridge"));
        QCOMPARE(startupBridgeKey({missing}), QStringLiteral("screen:bridge"));
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", tmux);
        QCOMPARE(backend.starts, 1);
        QVERIFY(backend.arguments.contains("tmux"));
    }
    void activationReconnectIsBoundedAndVerified() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", live);
        int queries = 0;
        page.setRefreshRequested([&] { ++queries; });
        backend.last->finish();
        for (int i = 0; i < 5; ++i) { page.update(live); }
        QCOMPARE(backend.starts, 1);
        page.activateTerminal();
        page.activateTerminal();
        QCOMPARE(queries, 1);
        QCOMPARE(backend.starts, 1); // No attach before a new validated listing.
        page.update(live);
        QCOMPARE(backend.starts, 2);
        backend.last->finish();
        for (int i = 0; i < 5; ++i) { page.update(live); }
        QCOMPARE(backend.starts, 2); // Failed reconnect cannot loop.
    }
    void replacementBlocksAutomaticReconnect() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", live);
        backend.last->finish();
        page.activateTerminal();
        Session replacement = live;
        replacement.sessionId = "456.g2c-bridge";
        page.update(replacement);
        page.activateTerminal();
        page.update(replacement);
        QCOMPARE(backend.starts, 1);
        page.findChild<QPushButton *>()->click();
        page.update(replacement);
        QCOMPARE(backend.starts, 2);
    }
    void intentionalDetachSurvivesActivationAndBackendChange() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", live);
        page.disconnectTerminal();
        page.activateTerminal();
        page.update(live);
        page.prepareBackendChange("konsole");
        page.update(live);
        QCOMPARE(backend.starts, 1);
        page.findChild<QPushButton *>()->click();
        page.update(live);
        QCOMPARE(backend.starts, 2);
    }
    void unavailableIdentityRequiresManualReconnect() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", live);
        Session unavailable = live;
        unavailable.state = "unconfirmed";
        page.update(unavailable);
        page.update(live);
        page.activateTerminal();
        page.update(live);
        QCOMPARE(backend.starts, 1);
    }
    void backendChangeReattachesOnlyConfirmedLiveViews() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", live);
        page.prepareBackendChange("konsole");
        QCOMPARE(backend.starts, 1);
        page.update(live);
        QCOMPARE(backend.starts, 2);
        page.prepareBackendChange("konsole");
        Session replacement = live;
        replacement.sessionId = "456.g2c-bridge";
        page.update(replacement);
        QCOMPARE(backend.starts, 2);
    }
    void reusedPidBlocksReconnect() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        Session original = live;
        original.generation = "12345";
        SessionPage page({}, registry, "konsole", original);
        QVERIFY(backend.arguments.contains("--expect-process-start-ticks"));
        backend.last->finish();
        page.activateTerminal();
        Session reused = original;
        reused.generation = "23456";
        page.update(reused);
        page.activateTerminal();
        page.update(reused);
        QCOMPARE(backend.starts, 1);
    }
    void screenDetachIsRespected() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage page({}, registry, "konsole", live);
        QTest::keyClick(backend.last, Qt::Key_A, Qt::ControlModifier);
        QTest::keyClick(backend.last, Qt::Key_D);
        backend.last->finish();
        page.activateTerminal();
        page.update(live);
        QCOMPARE(backend.starts, 1);
    }
    void tmuxReconnectAndDetach() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        Session tmux = live;
        tmux.multiplexer = "tmux";
        tmux.sessionId = "321.$0.123456";
        SessionPage page({}, registry, "konsole", tmux);
        QVERIFY(backend.arguments.contains("tmux"));
        QVERIFY(backend.arguments.contains(tmux.sessionId));
        backend.last->finish();
        page.activateTerminal();
        page.update(tmux);
        QCOMPARE(backend.starts, 2);
        QTest::keyClick(backend.last, Qt::Key_B, Qt::ControlModifier);
        QTest::keyClick(backend.last, Qt::Key_D);
        backend.last->finish();
        page.activateTerminal();
        page.update(tmux);
        QCOMPARE(backend.starts, 2);
        QVERIFY(!sameLiveSessionIdentity(live, tmux));
    }
    void multiplexersHaveDistinctSlots() {
        const QByteArray raw =
            "multiplexer=screen generation=123 project_id=bridge screen_name=g2c-bridge state=detached session_id=123.g2c-bridge task=Bridge\n"
            "multiplexer=tmux generation=456 project_id=bridge screen_name=g2c-bridge state=attached session_id=321.$0.123456 task=Bridge\n";
        QList<Session> parsed;
        QString error;
        QVERIFY(parseSessions(raw, parsed, error));
        QCOMPARE(parsed.size(), 2);
        QVERIFY(parsed[0].key() != parsed[1].key());
        QVERIFY(displayName(parsed[0]).contains("screen"));
        QVERIFY(displayName(parsed[1]).contains("tmux"));
        parsed.clear();
        QVERIFY(!parseSessions(raw + raw, parsed, error));
        parsed.clear();
        QByteArray swapped = raw;
        swapped.replace("321.$0.123456", "321.g2c-bridge");
        QVERIFY(!parseSessions(swapped, parsed, error));
    }
    void projectPreferenceAvailability() {
        ProjectMultiplexerSettings settings({}, nullptr, false);
        QVERIFY(settings.loadProjects("project_id=demo preferred=screen\nproject_id=other preferred=tmux\n"));
        settings.setAvailable(true, false);
        auto *projects = settings.findChild<QComboBox *>("multiplexerProject");
        auto *mux = settings.findChild<QComboBox *>("projectMultiplexer");
        auto *save = settings.findChild<QPushButton *>("saveProjectMultiplexer");
        QCOMPARE(mux->currentData().toString(), QStringLiteral("screen"));
        auto *model = qobject_cast<QStandardItemModel *>(mux->model());
        QVERIFY(model->item(0)->isEnabled());
        QVERIFY(!model->item(1)->isEnabled());
        QVERIFY(!model->item(1)->toolTip().isEmpty());
        projects->setCurrentIndex(projects->findData("other"));
        QCOMPARE(mux->currentData().toString(), QStringLiteral("tmux")); // Preserve an unavailable stored choice.
        QVERIFY(!save->isEnabled());
        mux->setCurrentIndex(0);
        QVERIFY(save->isEnabled());
        settings.setAvailable(true, true);
        QVERIFY(model->item(1)->isEnabled());
        QVERIFY(!settings.loadProjects("project_id=demo preferred=screen\nproject_id=demo preferred=tmux\n"));
    }
    void inactiveTerminalsArePreserved() {
        MemoryBackend backend;
        BackendRegistry registry(backend);
        SessionPage first({}, registry, "konsole", live);
        QPointer<MemoryTerminal> original = backend.last;
        SessionPage second({}, registry, "konsole", live);
        first.hide();
        second.activateTerminal();
        first.update(live);
        QVERIFY(original);
        QVERIFY(first.containsTerminal(original));
        QCOMPARE(backend.starts, 2);
    }
    void pasteOverridesConflictingActions_data() {
        QTest::addColumn<int>("key");
        QTest::addColumn<Qt::KeyboardModifiers>("modifiers");
        QTest::newRow("ctrl-shift-v") << int(Qt::Key_V) << Qt::KeyboardModifiers(Qt::ControlModifier | Qt::ShiftModifier);
        QTest::newRow("shift-insert") << int(Qt::Key_Insert) << Qt::KeyboardModifiers(Qt::ShiftModifier);
    }
    void pasteOverridesConflictingActions() {
        QFETCH(int, key);
        QFETCH(Qt::KeyboardModifiers, modifiers);
        QWidget window;
        MemoryTerminal terminal(&window);
        terminal.setFocusPolicy(Qt::StrongFocus);
        QWidget settings(&window);
        QAction menuPaste(&window), kpartPaste(&window);
        const QKeySequence shortcut(modifiers.toInt() | key);
        menuPaste.setShortcut(shortcut);
        kpartPaste.setShortcut(shortcut);
        window.addAction(&menuPaste);
        window.addAction(&kpartPaste);
        int kpartCalls = 0;
        connect(&menuPaste, &QAction::triggered, &terminal, [&] { terminal.pasteClipboardText(); });
        connect(&kpartPaste, &QAction::triggered, &terminal, [&] { ++kpartCalls; });
        PasteShortcutFilter router(&window,
            [&](QWidget *target) { return target == &terminal; }, [&] { menuPaste.trigger(); });
        window.show();
        window.activateWindow();
        terminal.setFocus();
        QCoreApplication::processEvents();
        QTest::keyClick(&terminal, Qt::Key(key), modifiers);
        QCOMPARE(terminal.pastes, 1);
        QCOMPARE(kpartCalls, 0);
        menuPaste.trigger();
        QCOMPARE(terminal.pastes, 2); // Menu and keys reach exactly the same operation.
        QKeyEvent override(QEvent::ShortcutOverride, key, modifiers);
        override.ignore();
        QCoreApplication::sendEvent(&settings, &override);
        QVERIFY(!override.isAccepted());
        QTest::keyClick(&terminal, Qt::Key_V, Qt::ControlModifier);
        QCOMPARE(terminal.pastes, 2); // Ctrl+V remains available to Codex.
    }
};

} // namespace
QTEST_MAIN(GuiLifecycleTests)
