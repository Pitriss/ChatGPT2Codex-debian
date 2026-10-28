#pragma once
// Shared, read-only interpretation of Konsole profile files for diagnostics and
// the QTermWidget fallback. No dependency on either terminal backend.
#include <QApplication>
#include <QDir>
#include <QFileInfo>
#include <QFontDatabase>
#include <QGuiApplication>
#include <QImage>
#include <QImageReader>
#include <QPainter>
#include <QPalette>
#include <QPixmap>
#include <QPointF>
#include <QSettings>
#include <QStandardPaths>
#include <QVariant>
#include <QMetaType>

namespace g2ctheme {
struct TerminalAppearance {
    QString scheme;
    QFont font = QFontDatabase::systemFont(QFontDatabase::FixedFont);
    QString source = QStringLiteral("qt_palette");
    qreal opacity = 1.0;
    QString wallpaper;
    QString wallpaperStatus = QStringLiteral("none");
    QString backgroundColor = QStringLiteral("unknown"); // From Konsole [Background], diagnostic only.
    QString wallpaperFillStyle = QStringLiteral("Tile");
    QPointF wallpaperAnchor = QPointF(0.5, 0.5);
    QString wallpaperFlip = QStringLiteral("NoFlip");
    qreal wallpaperOpacity = 1.0;
};

// Treat profile/scheme identifiers as file *names*, never untrusted paths.
inline bool safeKonsoleFileName(const QString &name) {
    return !name.isEmpty() && name.size() <= 128 && name != QStringLiteral(".")
        && name != QStringLiteral("..") && !name.contains(QLatin1Char('/'))
        && !name.contains(QLatin1Char('\\')) && !name.contains(QChar::Null)
        && !name.contains(QLatin1Char('\n')) && !name.contains(QLatin1Char('\r'));
}

inline QString konsoleFile(const QString &name) {
    if (!safeKonsoleFileName(name)) { return {}; }
    for (const QString &root : QStandardPaths::standardLocations(QStandardPaths::GenericDataLocation)) {
        const QFileInfo path(QDir(root).filePath(QStringLiteral("konsole/") + name));
        if (path.isFile() && path.isReadable()) { return path.absoluteFilePath(); }
    }
    return {};
}

inline QString platformTerminalScheme() {
    const bool dark = QGuiApplication::palette().color(QPalette::Base).lightnessF() < 0.5;
    // Stock QTermWidget fallbacks. Validated against availableColorSchemes()
    // in the optional QTermWidget backend before applying them.
    return dark ? QStringLiteral("WhiteOnBlack") : QStringLiteral("BlackOnWhite");
}

inline TerminalAppearance terminalAppearance() {
    TerminalAppearance result;
    result.scheme = platformTerminalScheme();

    const QString xdgConfigHome = qEnvironmentVariable("XDG_CONFIG_HOME");
    const QString configHome = QFileInfo(xdgConfigHome).isAbsolute()
        ? xdgConfigHome : QDir::homePath() + QStringLiteral("/.config");
    const QFileInfo rc(QDir(configHome).filePath(QStringLiteral("konsolerc")));
    if (!rc.isFile() || !rc.isReadable()) { return result; }

    const QSettings config(rc.absoluteFilePath(), QSettings::IniFormat);
    const QString profileName = config.value(QStringLiteral("Desktop Entry/DefaultProfile"))
        .toString().trimmed();
    if (!safeKonsoleFileName(profileName) || !profileName.endsWith(QStringLiteral(".profile"))) {
        return result;
    }
    const QString profilePath = konsoleFile(profileName);
    if (profilePath.isEmpty()) { return result; }
    const QSettings profile(profilePath, QSettings::IniFormat);

    const QVariant fontSetting = profile.value(QStringLiteral("Appearance/Font"));
    if (fontSetting.isValid()) {
        const QString encodedFont = fontSetting.metaType().id() == QMetaType::QStringList
            ? fontSetting.toStringList().join(QLatin1Char(',')) : fontSetting.toString();
        QFont profileFont;
        if (profileFont.fromString(encodedFont) && profileFont.pointSize() > 0) {
            result.font = profileFont;
        }
    }
    const QString schemeName = profile.value(QStringLiteral("Appearance/ColorScheme"))
        .toString().trimmed();
    if (safeKonsoleFileName(schemeName)) {
        const QString schemeFile = schemeName.endsWith(QStringLiteral(".colorscheme"))
            ? schemeName : schemeName + QStringLiteral(".colorscheme");
        const QString path = konsoleFile(schemeFile);
        if (!path.isEmpty()) {
            result.scheme = path; // QTermWidget accepts a Konsole .colorscheme path.
            result.source = QStringLiteral("konsole_profile");
            const QSettings colors(path, QSettings::IniFormat);
            // QSettings::IniFormat maps the literal INI section [General]
            // to ROOT-level keys. "General/Opacity" reads [%General], which
            // never matched Konsole's files (and broke the background test).
            bool validOpacity = false;
            const qreal opacity = colors.value(QStringLiteral("Opacity"), 1.0)
                .toString().toDouble(&validOpacity);
            if (validOpacity && opacity >= 0.0 && opacity <= 1.0) {
                result.opacity = opacity;
            }

            // Report the configured solid background separately from a
            // wallpaper. The value is source metadata, not a rendering claim.
            const QVariant rawBackground = colors.value(QStringLiteral("Background/Color"));
            const QString encodedBackground = rawBackground.metaType().id() == QMetaType::QStringList
                ? rawBackground.toStringList().join(QLatin1Char(',')) : rawBackground.toString();
            const QStringList rgbParts = encodedBackground.split(QLatin1Char(','));
            if (rgbParts.size() == 3) {
                bool okR = false, okG = false, okB = false;
                const int r = rgbParts.at(0).trimmed().toInt(&okR);
                const int g = rgbParts.at(1).trimmed().toInt(&okG);
                const int b = rgbParts.at(2).trimmed().toInt(&okB);
                if (okR && okG && okB && r >= 0 && r <= 255 && g >= 0 && g <= 255 && b >= 0 && b <= 255) {
                    result.backgroundColor = QStringLiteral("#%1%2%3")
                        .arg(r, 2, 16, QLatin1Char('0'))
                        .arg(g, 2, 16, QLatin1Char('0'))
                        .arg(b, 2, 16, QLatin1Char('0'));
                }
            }

            // Konsole puts the wallpaper in [General] of the .colorscheme,
            // not in the .profile. QTermWidget does not apply it automatically.
            const QString wallpaper = colors.value(QStringLiteral("Wallpaper"))
                .toString().trimmed();
            if (!wallpaper.isEmpty()) {
                result.wallpaperStatus = QStringLiteral("missing");
                QString imagePath;
                if (wallpaper.startsWith(QStringLiteral("~/"))) {
                    imagePath = QDir::home().filePath(wallpaper.mid(2));
                } else if (QDir::isAbsolutePath(wallpaper)) {
                    imagePath = wallpaper;
                } else {
                    imagePath = QFileInfo(path).absoluteDir().filePath(wallpaper);
                }
                const QFileInfo image(imagePath);
                // Only accept a readable local image; never open URLs or run
                // shell commands from Konsole's theme configuration.
                if (imagePath.size() <= 4096 && image.isFile() && image.isReadable()
                    && QImageReader(image.absoluteFilePath()).canRead()) {
                    result.wallpaper = image.absoluteFilePath();
                    result.wallpaperStatus = QStringLiteral("available");
                    // Konsole's fill styles are not the QTermWidget integer
                    // background modes. We compose to a viewport-sized image
                    // below, preserving Tile/Crop/Adapt/NoScaling and Anchor.
                    result.wallpaperFillStyle = colors.value(QStringLiteral("FillStyle"), QStringLiteral("Tile"))
                        .toString().trimmed();
                    if (result.wallpaperFillStyle.isEmpty()) {
                        result.wallpaperFillStyle = QStringLiteral("Tile");
                    }
                    const QVariant rawAnchor = colors.value(QStringLiteral("Anchor"), QStringLiteral("0.5,0.5"));
                    const QString anchorValue = rawAnchor.metaType().id() == QMetaType::QStringList
                        ? rawAnchor.toStringList().join(QLatin1Char(',')) : rawAnchor.toString();
                    const QStringList anchorParts = anchorValue.split(QLatin1Char(','));
                    if (anchorParts.size() == 2) {
                        bool validX = false, validY = false;
                        const qreal x = anchorParts.at(0).trimmed().toDouble(&validX);
                        const qreal y = anchorParts.at(1).trimmed().toDouble(&validY);
                        if (validX && validY && x >= 0.0 && x <= 1.0 && y >= 0.0 && y <= 1.0) {
                            result.wallpaperAnchor = QPointF(x, y);
                        }
                    }
                    bool validWallpaperOpacity = false;
                    const qreal wallpaperOpacity = colors.value(QStringLiteral("WallpaperOpacity"), 1.0)
                        .toString().toDouble(&validWallpaperOpacity);
                    if (validWallpaperOpacity && wallpaperOpacity >= 0.0 && wallpaperOpacity <= 1.0) {
                        result.wallpaperOpacity = wallpaperOpacity;
                    }
                    result.wallpaperFlip = colors.value(QStringLiteral("WallpaperFlipType"), QStringLiteral("NoFlip"))
                        .toString().trimmed();
                }
            }
        }
    }
    return result;
}

// Qt's QTermWidget (Debian 13: 2.1.0) only offers None/Stretch/Zoom/Fit/Center.
// Its None mode paints once at 0,0, whereas Konsole's Tile repeats the image.
// Composite static Konsole wallpapers at viewport size and hand QTermWidget the
// pixels using None (no second scaling or offset). No Konsole files are changed.
inline QImage renderKonsoleWallpaper(const QPixmap &source, QSize target,
                              const TerminalAppearance &appearance) {
    if (source.isNull() || target.isEmpty() || target.width() <= 0 || target.height() <= 0
        || static_cast<qint64>(target.width()) * target.height() > 12'000'000) {
        return {};
    }
    QImage composed(target, QImage::Format_ARGB32_Premultiplied);
    if (composed.isNull()) { return {}; }
    composed.fill(Qt::transparent);
    QPainter painter(&composed);
    painter.setRenderHint(QPainter::SmoothPixmapTransform);
    painter.setOpacity(appearance.wallpaperOpacity);
    const QRectF bounds(QPointF(0, 0), QSizeF(target));
    const QRectF original(source.rect());
    const QString mode = appearance.wallpaperFillStyle.trimmed().toLower();
    if (mode.isEmpty() || mode == QStringLiteral("tile")) {
        painter.drawTiledPixmap(composed.rect(), source, QPoint(0, 0));
    } else if (mode == QStringLiteral("stretch")) {
        painter.drawPixmap(bounds, source, original);
    } else {
        qreal factor = 1.0;
        if (mode == QStringLiteral("crop") || mode == QStringLiteral("zoom")) {
            factor = qMax(bounds.width() / original.width(), bounds.height() / original.height());
        } else if (mode == QStringLiteral("adapt") || mode == QStringLiteral("fit")) {
            factor = qMin(bounds.width() / original.width(), bounds.height() / original.height());
        } // NoScaling/Center, or unknown, retains original pixel dimensions.
        const QSizeF scaled(original.width() * factor, original.height() * factor);
        const QPointF offset((bounds.width() - scaled.width()) * appearance.wallpaperAnchor.x(),
                             (bounds.height() - scaled.height()) * appearance.wallpaperAnchor.y());
        painter.drawPixmap(QRectF(offset, scaled), source, original);
    }
    return composed;
}


} // namespace g2ctheme
