#include "backend_interface.h"
#include "paste_shortcut_filter.h"
#include "terminal_theme.h"
#include <QtTest/QtTest>
#include <QAction>
#include <QBackingStore>
#include <QClipboard>
#include <QDir>
#include <QFile>
#include <QImage>
#include <QPluginLoader>
#include <QTemporaryDir>
#include <QVBoxLayout>
#include <QFontMetricsF>
#include <QFontInfo>
#include <memory>
#ifdef G2C_TEST_KONSOLE
#include <KSharedConfig>
#endif

// Native widgets; normal regression tests start no process. Opt-in managed
// fixtures attach only to root-helper-owned synthetic sessions (never Codex).
class BackendTests final : public QObject {
    Q_OBJECT
    QTemporaryDir fixture_{QStringLiteral(G2C_TEST_WORK_DIR) + "/backend-fixture-XXXXXX"};
    std::unique_ptr<QPluginLoader> loader_;
    const QByteArray config_ = "[Desktop Entry]\nDefaultProfile=Fixture.profile\n[TabBar]\nSearchTabsButton=1\nCloseTabButton=2\n";
    QFont diagnosticFont_;
    bool write(const QString &name, const QByteArray &bytes) {
        QFile file(fixture_.filePath(name));
        return file.open(QIODevice::WriteOnly) && file.write(bytes) == bytes.size();
    }
    Gpt2CodexTerminalBackend *load(const QString &name) {
        loader_ = std::make_unique<QPluginLoader>(QCoreApplication::applicationDirPath()
            + "/gpt2codex-backends/libgpt2codex-backend-" + name + ".so");
        return qobject_cast<Gpt2CodexTerminalBackend *>(loader_->instance());
    }
    QByteArray scheme(bool wallpaper) {
        QByteArray result = "[General]\nDescription=Fixture\nOpacity=1\nFillStyle=Stretch\nWallpaperOpacity=0.4\nWallpaper=";
        if (wallpaper) { result += fixture_.filePath("wallpaper.png").toUtf8(); }
        result += "\n[Background]\nColor=16,24,32\n[BackgroundIntense]\nColor=16,24,32\n"
            "[Foreground]\nColor=220,220,220\n[ForegroundIntense]\nColor=255,255,255\n";
        const QList<QByteArray> colors{"0,0,0", "255,0,0", "0,255,0", "255,220,0",
            "0,0,255", "255,0,255", "0,255,255", "255,255,255"};
        for (int i = 0; i < colors.size(); ++i) {
            for (const QByteArray &suffix : {QByteArray(), QByteArray("Intense")}) {
                result += "[Color" + QByteArray::number(i) + suffix + "]\nColor=" + colors[i] + "\n";
            }
        }
        return result;
    }
private Q_SLOTS:
    void initTestCase() {
        if (qEnvironmentVariableIsSet("G2C_DIAG_ROOT")) {
            const auto appearance = g2ctheme::terminalAppearance();
            diagnosticFont_ = appearance.font;
            const QFontMetricsF metrics(appearance.font);
            qInfo("HOST_THEME opacity=%.2f wallpaper=%d font_pt=%.2f fixed=%d weight=%d underline=%d overline=%d cell0=%.2f cellM=%.2f height=%.2f",
                double(appearance.opacity), !appearance.wallpaper.isEmpty(), double(appearance.font.pointSizeF()),
                QFontInfo(appearance.font).fixedPitch(), int(appearance.font.weight()), appearance.font.underline(),
                appearance.font.overline(), double(metrics.horizontalAdvance(QLatin1Char('0'))),
                double(metrics.horizontalAdvance(QLatin1Char('M'))), double(metrics.height()));
        }
        QVERIFY(fixture_.isValid());
        QVERIFY(QDir().mkpath(fixture_.filePath("config")));
        QVERIFY(QDir().mkpath(fixture_.filePath("data/konsole")));
        qputenv("XDG_CONFIG_HOME", fixture_.filePath("config").toUtf8());
        qputenv("XDG_DATA_HOME", fixture_.filePath("data").toUtf8());
        QVERIFY(write("config/konsolerc", config_));
        const QByteArray font = qEnvironmentVariableIsSet("G2C_DIAG_ROOT")
            ? diagnosticFont_.toString().toUtf8() : QByteArray("Monospace,12,-1,5,400,0,0,0,0,0");
        QVERIFY(write("data/konsole/Fixture.profile",
            "[General]\nName=Fixture\n[Appearance]\nColorScheme=Fixture\nFont=" + font + "\n"));
        QImage wallpaper(170, 190, QImage::Format_RGB32);
        for (int y = 0; y < wallpaper.height(); ++y) {
            for (int x = 0; x < wallpaper.width(); ++x) {
                wallpaper.setPixelColor(x, y, QColor(x, y, (x + y) % 256));
            }
        }
        QVERIFY(wallpaper.save(fixture_.filePath("wallpaper.png")));
        QVERIFY(write("data/konsole/Fixture.colorscheme", scheme(false)));
    }
    void konsoleShortcutsAndLayout() {
        auto *backend = load("konsole");
        QVERIFY2(backend, qPrintable(loader_->errorString()));
        QTest::failOnWarning(QRegularExpression(".*(Cannot add a null widget|Ambiguous shortcut).*"));
        QWidget window;
        auto *layout = new QVBoxLayout(&window);
        QWidget *view = backend->create(&window, "/bin/true", {}, {});
        QVERIFY(view);
        layout->addWidget(view);
        QWidget *inactive = backend->create(&window, "/bin/true", {}, {});
        QVERIFY(inactive);
        inactive->hide();
        QAction menuPaste(&window);
        const QList<QKeySequence> keys{QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_V),
            QKeySequence(Qt::SHIFT | Qt::Key_Insert)};
        menuPaste.setShortcuts(keys);
        window.addAction(&menuPaste);
        int calls = 0;
        bool accepted = false;
        connect(&menuPaste, &QAction::triggered, &window, [&] {
            ++calls;
            QVERIFY(QMetaObject::invokeMethod(view, "pasteClipboardText", Qt::DirectConnection,
                Q_RETURN_ARG(bool, accepted)));
        });
        PasteShortcutFilter router(&window, [view](QWidget *target) {
            return target == view || view->isAncestorOf(target);
        }, [&] { menuPaste.trigger(); });
        window.show();
        window.activateWindow();
        QWidget *input = view->focusProxy();
        QVERIFY(input);
        input->setFocus();
        QCoreApplication::processEvents();
        int nativeActions = 0;
        for (QWidget *widget : window.findChildren<QWidget *>()) {
            for (QAction *action : widget->actions()) {
                if (action->objectName() == QStringLiteral("edit_paste")) { ++nativeActions; }
                for (const auto &key : keys) { QVERIFY(!action->shortcuts().contains(key)); }
                if (action->objectName() == QStringLiteral("edit_paste")) {
                    const auto original = action->shortcuts();
                    const QKeySequence other(Qt::CTRL | Qt::ALT | Qt::Key_P);
                    action->setShortcuts({keys[0], keys[1], other});
                    QCOMPARE(action->shortcuts(), QList<QKeySequence>{other});
                    action->setShortcuts(original);
                }
            }
        }
        QVERIFY(nativeActions > 0);
        QGuiApplication::clipboard()->setText(QStringLiteral("fixture"));
        menuPaste.trigger();
        QVERIFY(accepted);
        QTest::keyClick(input, Qt::Key_V, Qt::ControlModifier | Qt::ShiftModifier);
        QCOMPARE(calls, 2);
        QVERIFY(accepted);
        QTest::keyClick(input, Qt::Key_Insert, Qt::ShiftModifier);
        QCOMPARE(calls, 3);
#ifdef G2C_TEST_KONSOLE
        auto sharedConfig = KSharedConfig::openConfig(QStringLiteral("konsolerc"));
        QVERIFY(!sharedConfig->isDirty());
        QVERIFY(sharedConfig->sync());
#endif
        QVERIFY(accepted);
        QTest::keyClick(input, Qt::Key_V, Qt::ControlModifier);
        QCOMPARE(calls, 3);
        QFile config(fixture_.filePath("config/konsolerc"));
        QVERIFY(config.open(QIODevice::ReadOnly));
        QCOMPARE(config.readAll(), config_);
    }
    void renderQTerm_data() {
        QTest::addColumn<bool>("wallpaper");
        QTest::newRow("wallpaper") << true;
        QTest::newRow("solid") << false;
    }
    void renderQTerm() {
        QFETCH(bool, wallpaper);
        QVERIFY(write("data/konsole/Fixture.colorscheme", scheme(wallpaper)));
        QTest::failOnWarning(QRegularExpression(".*Invalid color value.*"));
        auto *backend = load("qtermwidget");
        QVERIFY2(backend, qPrintable(loader_->errorString()));
        std::unique_ptr<QWidget> view(backend->create(nullptr, "/bin/true", {}, {}));
        QVERIFY(view);
        view->resize(800, 500);
        view->show();
        QTest::qWait(200);
        QObject *session = nullptr;
        for (auto *child : view->findChildren<QObject *>()) {
            if (QString::fromLatin1(child->metaObject()->className()) == QStringLiteral("Konsole::Session")) { session = child; }
        }
        QVERIFY(session);
        auto feed = [&](const QByteArray &data) {
            QVERIFY(QMetaObject::invokeMethod(session, "onReceiveBlock", Qt::DirectConnection,
                Q_ARG(const char *, data.constData()), Q_ARG(int, int(data.size()))));
            QTest::qWait(30);
        };
        auto compareBacking = [&] {
            auto *device = view->backingStore()->paintDevice();
            QVERIFY(device->devType() == QInternal::Image);
            const auto actual = *static_cast<QImage *>(device);
            const auto full = view->grab().toImage().convertToFormat(actual.format());
            QCOMPARE(actual.size(), full.size());
            QCOMPARE(actual, full);
        };
        feed("\033[?25l\033[2J\033[H\033[33mHello ANSI \342\224\200\342\224\202\342\224\214\033[0m");
        int yellow = 0;
        const auto colored = view->grab().toImage();
        for (int y = 0; y < colored.height(); ++y) {
            for (int x = 0; x < colored.width(); ++x) {
                const auto color = colored.pixelColor(x, y);
                if (color.red() > 180 && color.green() > 160 && color.blue() < 50) { ++yellow; }
            }
        }
        QVERIFY(yellow > 20);
        QByteArray scroll;
        for (int i = 0; i < 50; ++i) { scroll += "\r\n\033[33mLine " + QByteArray::number(i) + "\033[0m"; }
        feed(scroll);
        compareBacking();
        feed("\033[0m\033[2J\033[H");
        compareBacking();
        view->resize(930, 560);
        QTest::qWait(200);
        compareBacking();
        feed("\033[?1049h\033[2J\033[H\033[33m\033(0l" + QByteArray(65, 'q') + "k\033(B\033[0m");
        feed("\033[0m\033[2J\033[H\033[33mwide: \346\274\242\345\255\227 \360\237\230\200 \033[0m\r\nnormal");
        for (int i = 0; i < 8; ++i) {
            feed("\033[H\033[33;4m" + QByteArray(70, ' ') + "\033[0m\r\ntext\033[J");
            feed("\033[H\033[0mshort\033[K\r\nnew\033[J");
        }
        compareBacking();
    }
    void managedMultiplexerAttachment() {
        const QString root = qEnvironmentVariable("G2C_MUX_FIXTURE");
        if (root.isEmpty()) { QSKIP("Run the root multiplexer helper for isolated managed PTY tests."); }
        QFile marker(root + "/fixture.marker");
        QVERIFY(marker.open(QIODevice::ReadOnly));
        QCOMPARE(marker.readAll(), QByteArray("gpt2codex-isolated-multiplexer-v1\n"));
        const QString config = qEnvironmentVariable("G2C_MUX_CONFIG");
        QCOMPARE(config, root + "/c/config.toml");
        QCOMPARE(qEnvironmentVariable("SCREENDIR"), root + "/sockets");
        const QString mux = qEnvironmentVariable("G2C_MUX");
        QVERIFY(mux == "screen" || mux == "tmux");
        const QString name = qEnvironmentVariable("G2C_MUX_BACKEND");
        QVERIFY(name == "konsole" || name == "qtermwidget");
        auto *backend = load(name);
        QVERIFY2(backend, qPrintable(loader_->errorString()));
        const QStringList args{"session", "attach", "--id", qEnvironmentVariable("G2C_MUX_PROJECT"),
            "--multiplexer", mux, "--expect-session-id", qEnvironmentVariable("G2C_MUX_IDENTITY"), "--config", config};
        std::unique_ptr<QWidget> view(backend->create(nullptr,
            QCoreApplication::applicationDirPath() + "/gpt2codex", args, root));
        QVERIFY(view);
        QSignalSpy finished(view.get(), SIGNAL(terminalFinished()));
        backend->start(view.get());
        for (const QSize &size : {QSize(800, 500), QSize(930, 560), QSize(800, 500)}) {
            view->resize(size);
            view->show();
            QTest::qWait(550);
            QCOMPARE(finished.count(), 0);
            const auto full = view->grab().toImage();
            int yellow = 0, red = 0, green = 0, blue = 0;
            for (int y = 0; y < full.height(); ++y) {
                for (int x = 0; x < full.width(); ++x) {
                    const QColor c = full.pixelColor(x, y);
                    yellow += c.red() > 180 && c.green() > 160 && c.blue() < 60;
                    red += c.red() > 180 && c.green() < 60 && c.blue() < 60;
                    green += c.green() > 180 && c.red() < 60 && c.blue() < 60;
                    blue += c.blue() > 180 && c.red() < 60 && c.green() < 60;
                }
            }
            QVERIFY(yellow > 20);
            QVERIFY(red > 5);
            QVERIFY(green > 5);
            QVERIFY(blue > 5);
        }
        // Destruction closes only our transient fixture attachment.
    }
    void screenPtyDiagnostics() {
        const QString root = qEnvironmentVariable("G2C_DIAG_ROOT");
        if (root.isEmpty()) { QSKIP("Run the root terminal diagnostics helper for isolated screen/PTY tests."); }
        const QString backendName = qEnvironmentVariable("G2C_DIAG_BACKEND");
        QVERIFY(backendName == "konsole" || backendName == "qtermwidget");
        auto *backend = load(backendName);
        QVERIFY2(backend, qPrintable(loader_->errorString()));
        const QStringList args{qEnvironmentVariable("G2C_DIAG_HELPER"), "--attach-fixture", root,
            qEnvironmentVariable("G2C_DIAG_SESSION")};
        std::unique_ptr<QWidget> view(backend->create(nullptr, qEnvironmentVariable("G2C_DIAG_PYTHON"), args, root));
        QVERIFY(view);
        view->setWindowTitle(QStringLiteral("gpt2codex: isolated synthetic screen — ") + backendName);
        QSignalSpy finished(view.get(), SIGNAL(terminalFinished()));
        // Match SessionPage: start before insertion/show, then exercise resize.
        backend->start(view.get());
        const QList<QSize> sizes{QSize(800, 500), QSize(930, 560), QSize(800, 500)};
        int stage = 0;
        for (const QSize &size : sizes) {
            view->resize(size);
            view->show();
            QTest::qWait(qEnvironmentVariableIsSet("G2C_DIAG_VISUAL") ? 2500 : 450);
            QCOMPARE(finished.count(), 0);
            auto *device = view->backingStore()->paintDevice();
            QVERIFY(device->devType() == QInternal::Image);
            const QImage incremental = *static_cast<QImage *>(device);
            const auto full = view->grab().toImage().convertToFormat(incremental.format());
            QCOMPARE(incremental.size(), full.size());
            int differences = 0, yellowPixels = 0;
            for (int y = 0; y < full.height(); ++y) {
                for (int x = 0; x < full.width(); ++x) {
                    differences += incremental.pixel(x, y) != full.pixel(x, y);
                    const QColor color = full.pixelColor(x, y);
                    yellowPixels += color.red() > 180 && color.green() > 160 && color.blue() < 50;
                }
            }
            qInfo("PTY_STAGE stage=%d width=%d height=%d dpr=%.2f paint_difference=%d yellow_pixels=%d",
                stage, size.width(), size.height(), double(view->devicePixelRatioF()), differences, yellowPixels);
            const QString prefix = qEnvironmentVariable("G2C_DIAG_OUTPUT") + "/" + backendName + QString::number(stage++);
            QVERIFY(incremental.save(prefix + "-incremental.png"));
            QVERIFY(full.save(prefix + "-full.png"));
            QCOMPARE(differences, 0);
            QVERIFY(yellowPixels > 20);
        }
    }
};

QTEST_MAIN(BackendTests)
#include "backend_tests.moc"
