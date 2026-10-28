// Optional QTermWidget6 backend. Qt6 UI itself does not link QTermWidget.
#include "backend_interface.h"
#include "terminal_theme.h"
#include <qtermwidget.h>
#include <QEvent>
#include <QFile>
#include <QImageReader>
#include <QPointer>
#include <QResizeEvent>
#include <QShowEvent>
#include <QTemporaryDir>
#include <QTimer>
#include <memory>
using namespace g2ctheme;

class ThemedTerminal final : public QTermWidget {
    Q_OBJECT
public:
    explicit ThemedTerminal(QWidget *parent = nullptr) : QTermWidget(0, parent) {
        renderTimer_.setSingleShot(true);
        renderTimer_.setInterval(120); // Coalesce resize events; no disk writes for each pixel.
        connect(&renderTimer_, &QTimer::timeout, this, [this] { refreshWallpaper(); });
        connect(this, &QTermWidget::finished, this, &ThemedTerminal::terminalFinished);
    }

    void startAttachedProcess() { startShellProgram(); }

    // Use the emulator's native paste path. It understands bracketed paste
    // and never turns clipboard content into synthetic keypresses.
    Q_INVOKABLE bool pasteClipboardText() {
        pasteClipboard();
        return true;
    }

    void applyAppearance() {
        appearance_ = terminalAppearance();
        setTerminalFont(appearance_.font);
        setColorScheme(appearance_.scheme);
        setTerminalOpacity(appearance_.opacity);
        setTerminalBackgroundMode(0); // Already composed at the final viewport size.
        source_ = QPixmap();
        if (!appearance_.wallpaper.isEmpty()) {
            QImageReader reader(appearance_.wallpaper);
            reader.setAutoTransform(true);
            const QSize sourceSize = reader.size();
            if (!sourceSize.isValid() || static_cast<qint64>(sourceSize.width()) * sourceSize.height() <= 32'000'000) {
                QImage original = reader.read();
                if (!original.isNull() && static_cast<qint64>(original.width()) * original.height() <= 32'000'000) {
                    const QString flip = appearance_.wallpaperFlip;
                    const bool horizontal = flip.compare(QStringLiteral("Horizontal"), Qt::CaseInsensitive) == 0
                        || flip.compare(QStringLiteral("Both"), Qt::CaseInsensitive) == 0;
                    const bool vertical = flip.compare(QStringLiteral("Vertical"), Qt::CaseInsensitive) == 0
                        || flip.compare(QStringLiteral("Both"), Qt::CaseInsensitive) == 0;
                    if (horizontal || vertical) { original = original.mirrored(horizontal, vertical); }
                    source_ = QPixmap::fromImage(original);
                }
            }
        }
        if (source_.isNull()) {
            renderTimer_.stop();
            setTerminalBackgroundImage(QString());
            observeViewport();
            if (viewport_) { viewport_->update(); }
        } else {
            observeViewport();
            renderTimer_.start(0);
        }
    }

Q_SIGNALS:
    void terminalFinished();

protected:
    void resizeEvent(QResizeEvent *event) override {
        QTermWidget::resizeEvent(event);
        observeViewport();
        if (!source_.isNull()) { renderTimer_.start(); }
    }

    void showEvent(QShowEvent *event) override {
        QTermWidget::showEvent(event);
        observeViewport();
        if (!source_.isNull()) { renderTimer_.start(0); }
    }

    bool eventFilter(QObject *watched, QEvent *event) override {
        if (watched == viewport_ && (event->type() == QEvent::Resize || event->type() == QEvent::Show)
            && !source_.isNull()) {
            renderTimer_.start();
        }
        return QTermWidget::eventFilter(watched, event);
    }

private:
    void observeViewport() {
        // QTermWidget wraps the actual painted TerminalDisplay. Its size can
        // differ from this widget because of the scroll bar and search area.
        for (QWidget *child : findChildren<QWidget *>()) {
            if (QString::fromLatin1(child->metaObject()->className()).endsWith(QStringLiteral("TerminalDisplay"))) {
                if (viewport_ != child) {
                    if (viewport_) { viewport_->removeEventFilter(this); }
                    viewport_ = child;
                    viewport_->installEventFilter(this);
                }
                return;
            }
        }
    }

    void refreshWallpaper() {
        if (source_.isNull()) { return; }
        observeViewport();
        const QSize target = viewport_ ? viewport_->size() : size();
        if (!target.isValid() || target.isEmpty()) { return; }
        // Refuse unexpectedly large targets instead of allocating unbounded
        // memory/disk just because a malformed profile references a wallpaper.
        if (static_cast<qint64>(target.width()) * target.height() > 12'000'000) { return; }
        const QImage pixels = renderKonsoleWallpaper(source_, target, appearance_);
        if (pixels.isNull()) { return; }
        if (!wallpaperDir_) {
            wallpaperDir_ = std::make_unique<QTemporaryDir>(QDir::tempPath()
                + QStringLiteral("/gpt2codex-gui-wallpaper-XXXXXX"));
        }
        if (!wallpaperDir_->isValid()) { return; }
        const QString generated = wallpaperDir_->filePath(QStringLiteral("wallpaper-%1.png").arg(++generation_));
        if (!pixels.save(generated, "PNG")) { return; }
        setTerminalBackgroundMode(0);
        setTerminalBackgroundImage(generated);
        // QTermWidget 2.1 only replaces its pixmap here; it does not invalidate
        // the backing store. After resize, old wallpaper strips would survive
        // until output happens to damage them. Repaint once per new image.
        if (viewport_) { viewport_->update(); }
        if (!previousGenerated_.isEmpty()) { QFile::remove(previousGenerated_); }
        previousGenerated_ = generated;
    }

    TerminalAppearance appearance_;
    QPixmap source_;
    QTimer renderTimer_;
    QPointer<QWidget> viewport_;
    std::unique_ptr<QTemporaryDir> wallpaperDir_;
    QString previousGenerated_;
    quint64 generation_ = 0;
};


class QTermBackend final : public QObject, public Gpt2CodexTerminalBackend {
    Q_OBJECT
    Q_PLUGIN_METADATA(IID GPT2CODEX_TERMINAL_BACKEND_IID)
    Q_INTERFACES(Gpt2CodexTerminalBackend)
public:
    QString id() const override { return QStringLiteral("qtermwidget"); }
    bool usable() const override { return true; }
    QWidget *create(QWidget *parent, const QString &program,
                    const QStringList &args, const QString &directory) override {
        auto *view = new ThemedTerminal(parent);
        view->setShellProgram(program);
        view->setArgs(args);
        view->setWorkingDirectory(directory);
        view->setAutoClose(true);
        view->applyAppearance();
        return view;
    }
    void start(QWidget *view) override { static_cast<ThemedTerminal *>(view)->startAttachedProcess(); }
    void refreshAppearance(QWidget *view) override { static_cast<ThemedTerminal *>(view)->applyAppearance(); }
};
#include "backend_qtermwidget.moc"
