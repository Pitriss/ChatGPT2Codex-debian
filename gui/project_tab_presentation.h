// Presentation only: roots come from the existing read-only project registry.
#pragma once

#include <QBuffer>
#include <QIconEngine>
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace g2ctabs {

constexpr int iconPixels = 20;
// Empty layout space between the icon and native tab text. No status object,
// status painting or data source exists yet; a future indicator can use it.
constexpr int futureIndicatorPixels = 8;
constexpr int maxIconBytes = 1024 * 1024;
constexpr int maxIconDimension = 1024;
inline QSize decorationSize() { return {iconPixels + futureIndicatorPixels, iconPixels}; }

class OwnedFd final {
public:
    explicit OwnedFd(int fd = -1) : fd_(fd) {}
    ~OwnedFd() { if (fd_ >= 0) { ::close(fd_); } }
    OwnedFd(const OwnedFd &) = delete;
    OwnedFd &operator=(const OwnedFd &) = delete;
    int get() const { return fd_; }
    void reset(int fd) { if (fd_ >= 0) { ::close(fd_); } fd_ = fd; }
private:
    int fd_;
};

// Traverse every component using directory descriptors, never a symlink. A
// renamed/replaced path cannot redirect the final open outside this directory.
inline QImage readProjectIcon(const QString &registeredRoot) {
    if (!QDir::isAbsolutePath(registeredRoot) || QDir::cleanPath(registeredRoot) != registeredRoot
        || registeredRoot == QStringLiteral("/") || registeredRoot.contains(QChar::Null)) { return {}; }
    OwnedFd root(::open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC));
    for (const QString &component : registeredRoot.split(QLatin1Char('/'), Qt::SkipEmptyParts)) {
        if (root.get() < 0) { return {}; }
        const QByteArray name = QFile::encodeName(component);
        root.reset(::openat(root.get(), name.constData(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
    }
    if (root.get() < 0) { return {}; }
    OwnedFd source(::openat(root.get(), ".icon.png", O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC));
    struct stat before{};
    if (source.get() < 0 || ::fstat(source.get(), &before) != 0 || !S_ISREG(before.st_mode)
        || before.st_size <= 0 || before.st_size > maxIconBytes) { return {}; }
    QFile file;
    if (!file.open(source.get(), QIODevice::ReadOnly, QFileDevice::DontCloseHandle)) { return {}; }
    const QByteArray data = file.read(maxIconBytes + 1);
    struct stat after{};
    if (::fstat(source.get(), &after) != 0 || data.size() != before.st_size || data.size() > maxIconBytes
        || before.st_size != after.st_size || before.st_mtim.tv_sec != after.st_mtim.tv_sec
        || before.st_mtim.tv_nsec != after.st_mtim.tv_nsec
        || !data.startsWith(QByteArray::fromHex("89504e470d0a1a0a"))) { return {}; }
    QBuffer buffer;
    buffer.setData(data);
    if (!buffer.open(QIODevice::ReadOnly)) { return {}; }
    QImageReader reader(&buffer, "png");
    reader.setAutoDetectImageFormat(false);
    const QSize size = reader.size();
    if (!size.isValid() || size.width() > maxIconDimension || size.height() > maxIconDimension) { return {}; }
    QImage image = reader.read();
    if (image.isNull() || image.size() != size) { return {}; }
    // A fully transparent PNG is not a usable visible project icon.
    for (int y = 0; y < image.height(); ++y) {
        for (int x = 0; x < image.width(); ++x) {
            if (image.pixelColor(x, y).alpha() != 0) { return image; }
        }
    }
    return {};
}

// Keep native tab text, elision, close buttons and keyboard behavior. Only the
// icon rectangle includes an empty future-indicator slot; artwork stays 20x20.
class TabIconEngine final : public QIconEngine {
public:
    explicit TabIconEngine(QIcon icon) : icon_(std::move(icon)) {}
    QIconEngine *clone() const override { return new TabIconEngine(icon_); }
    void paint(QPainter *painter, const QRect &rect, QIcon::Mode mode, QIcon::State state) override {
        const QSize area = decorationSize().scaled(rect.size(), Qt::KeepAspectRatio);
        const int side = area.height();
        const int x = rect.x() + (rect.width() - area.width()) / 2
            + (QGuiApplication::layoutDirection() == Qt::RightToLeft ? area.width() - side : 0);
        icon_.paint(painter, QRect(x, rect.y() + (rect.height() - side) / 2, side, side), Qt::AlignCenter, mode, state);
    }
    QSize actualSize(const QSize &size, QIcon::Mode, QIcon::State) override {
        return decorationSize().scaled(size, Qt::KeepAspectRatio);
    }
    QPixmap pixmap(const QSize &size, QIcon::Mode mode, QIcon::State state) override {
        QPixmap result(size);
        result.fill(Qt::transparent);
        QPainter painter(&result);
        paint(&painter, result.rect(), mode, state);
        return result;
    }
private:
    QIcon icon_;
};

inline QIcon tabIcon(const QImage &custom, bool bridge, QWidget *widget) {
    QIcon icon;
    if (!custom.isNull()) {
        // Keep enough source pixels for high-DPI screens, with transparent
        // square padding so wide/tall artwork keeps its original proportions.
        QPixmap square(80, 80);
        square.fill(Qt::transparent);
        QPainter painter(&square);
        const QImage fit = custom.scaled(square.size(), Qt::KeepAspectRatio, Qt::SmoothTransformation);
        painter.drawImage(QPoint((80 - fit.width()) / 2, (80 - fit.height()) / 2), fit);
        painter.end();
        icon = QIcon(square);
    } else {
        icon = QIcon::fromTheme(bridge ? QStringLiteral("network-connect") : QStringLiteral("utilities-terminal"),
            widget->style()->standardIcon(bridge ? QStyle::SP_DriveNetIcon : QStyle::SP_ComputerIcon));
    }
    return QIcon(new TabIconEngine(icon));
}

// Parse only the existing registry listing, not session labels or preferences.
// Locate an unambiguous root field even when a display name contains ' root='.
inline bool parseProjectRoots(const QByteArray &raw, QHash<QString, QString> &roots) {
    roots.clear();
    if (raw.isEmpty() || raw.size() > 65536) { return false; }
    const QString text = QString::fromUtf8(raw);
    for (const QChar ch : text) {
        if (ch == QChar::ReplacementCharacter || (ch.category() == QChar::Other_Control && ch != QLatin1Char('\n'))) { return false; }
    }
    QStringList lines = text.split(QLatin1Char('\n'), Qt::SkipEmptyParts);
    if (lines.isEmpty() || lines.size() > 201 || !lines.first().startsWith(QStringLiteral("project_dir="))) { return false; }
    const QString parent = lines.takeFirst().mid(12);
    if (!QDir::isAbsolutePath(parent) || QDir::cleanPath(parent) != parent) { return false; }
    static const QRegularExpression prefix(QStringLiteral(R"(^id=([a-z0-9_-]{1,64}) name=)"));
    QHash<QString, QString> parsed;
    QSet<QString> paths;
    for (const QString &line : lines) {
        const auto match = prefix.match(line);
        if (!match.hasMatch() || parsed.contains(match.captured(1))) { return false; }
        QString root;
        int candidates = 0;
        int position = match.capturedLength();
        while ((position = line.indexOf(QStringLiteral(" root="), position)) >= 0) {
            const int nameLength = position - match.capturedLength();
            const QString candidate = line.mid(position + 6);
            if (nameLength > 0 && nameLength <= 80 && QDir::isAbsolutePath(candidate)
                && QDir::cleanPath(candidate) == candidate && QFileInfo(candidate).path() == parent) {
                root = candidate;
                ++candidates;
            }
            ++position;
        }
        if (candidates != 1 || paths.contains(root)) { return false; }
        paths.insert(root);
        parsed.insert(match.captured(1), root);
    }
    roots = parsed;
    return true;
}

class Presentation final {
public:
    void setRoots(const QHash<QString, QString> &roots) { roots_ = roots; icons_.clear(); }
    void invalidateIcons() { icons_.clear(); }
    void apply(QTabWidget *tabs, QWidget *page, const QString &id, const QString &actualMultiplexer,
               const QString &title, const QString &task) {
        const int index = tabs->indexOf(page);
        if (index < 0) { return; }
        const bool bridge = id == QStringLiteral("bridge");
        const QString root = roots_.value(bridge ? QStringLiteral("gpt2codex") : id);
        if (!icons_.contains(id)) { icons_.insert(id, tabIcon(readProjectIcon(root), bridge, tabs)); }
        tabs->setIconSize(decorationSize());
        tabs->setTabIcon(index, icons_.value(id));
        tabs->setTabText(index, title);
        const QString tooltip = id + QStringLiteral(" | ") + task
            + QStringLiteral(" [%1]\nProjekt: %2").arg(actualMultiplexer,
                root.isEmpty() ? QStringLiteral("cesta není ověřena v registru") : root);
        // Paths/labels are text, never tooltip HTML capable of loading images.
        tabs->setTabToolTip(index, QStringLiteral("<qt>") + tooltip.toHtmlEscaped().replace(QLatin1Char('\n'), QStringLiteral("<br/>")) + QStringLiteral("</qt>"));
    }
private:
    QHash<QString, QString> roots_;
    QHash<QString, QIcon> icons_;
};

} // namespace g2ctabs
